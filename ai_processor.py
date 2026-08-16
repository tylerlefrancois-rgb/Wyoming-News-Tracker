import html
import json
from difflib import SequenceMatcher
import os
import re
import time
from typing import Any

from dotenv import load_dotenv
from google import genai


load_dotenv()

POLICY_TRACKER_SPEED_MODE_V7 = True
POLICY_TRACKER_TEXT_CLEANUP_V7_2 = True
POLICY_TRACKER_TEXT_CLEANUP_V7_2_1 = True
POLICY_TRACKER_TEXT_CLEANUP_V7_2_2 = True

MODEL_NAME = (
    os.getenv("POLICY_TRACKER_MODEL", "gemini-3.6-flash").strip()
    or "gemini-3.6-flash"
)
THINKING_LEVEL = (
    os.getenv("POLICY_TRACKER_THINKING_LEVEL", "low").strip().lower()
    or "low"
)
MAX_ATTEMPTS = max(1, min(3, int(os.getenv("POLICY_TRACKER_MAX_ATTEMPTS", "2"))))
POLICY_BATCH_SIZE = max(4, min(20, int(os.getenv("POLICY_TRACKER_BATCH_SIZE", "20"))))
FALLBACK_MODEL_NAMES = tuple(
    name.strip()
    for name in os.getenv(
        "POLICY_TRACKER_FALLBACK_MODELS",
        "gemini-3.5-flash,gemini-2.5-flash",
    ).split(",")
    if name.strip()
)

POLICY_AREAS = [
    "Energy & Natural Resources",
    "Economics & State Budget",
    "Government Transparency, Regulation & Legal Reform",
    "Education",
    "Marijuana / THC",
    "Health Care",
    "Campaign Finance & Election Integrity",
    "Criminal Justice",
]

TOP_STORIES_SCHEMA = {
    "type": "array",
    "minItems": 0,
    "maxItems": 5,
    "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "article_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"type": "string"},
            },
        },
        "required": ["title", "summary", "article_ids"],
    },
}

def _policy_items_schema(max_items: int) -> dict[str, Any]:
    # Keep the response schema deliberately small. Gemini structured-output
    # serving can reject schemas with large array limits as having too many
    # possible states. The classifier therefore uses a schema sized to each
    # small article batch instead of a global maxItems=80 schema.
    limit = max(1, min(POLICY_BATCH_SIZE, int(max_items)))
    return {
        "type": "array",
        "minItems": 0,
        "maxItems": limit,
        "items": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": POLICY_AREAS},
                "article_id": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["category", "article_id", "summary"],
        },
    }


# Retained for compatibility with any local diagnostics that import the name.
POLICY_ITEMS_SCHEMA = _policy_items_schema(POLICY_BATCH_SIZE)

FALLBACK_KEYWORDS = {
    "Marijuana / THC": (
        "marijuana",
        "cannabis",
        "thc",
        "hemp",
    ),
    "Campaign Finance & Election Integrity": (
        "election",
        "campaign",
        "candidate",
        "ballot",
        "voter",
        "voting",
        "primary election",
        "campaign finance",
    ),
    "Education": (
        "school",
        "education",
        "teacher",
        "student",
        "university",
        "college",
        "school district",
        "curriculum",
    ),
    "Health Care": (
        "health care",
        "healthcare",
        "hospital",
        "medicaid",
        "medicare",
        "insurance",
        "clinic",
        "physician",
        "doctor",
        "medical",
        "public health",
        "vaccine",
        "measles",
    ),
    "Criminal Justice": (
        "criminal justice",
        "sentencing",
        "corrections",
        "prison",
        "jail",
        "parole",
        "probation",
        "prosecution",
        "prosecutor",
        "policing policy",
        "law enforcement policy",
    ),
    "Energy & Natural Resources": (
        "energy",
        "oil",
        "natural gas",
        "coal",
        "mining",
        "mineral",
        "uranium",
        "nuclear",
        "wind power",
        "solar",
        "electricity",
        "utility",
        "public lands",
        "water rights",
        "wildlife",
        "grizzly",
        "wolf",
        "forest",
        "drilling",
    ),
    "Economics & State Budget": (
        "budget",
        "tax",
        "revenue",
        "economy",
        "economic",
        "business",
        "housing",
        "workforce",
        "grant",
        "spending",
        "appropriation",
        "development",
    ),
    "Government Transparency, Regulation & Legal Reform": (
        "public records",
        "transparency",
        "regulation",
        "regulatory",
        "rulemaking",
        "lawsuit",
        "court ruling",
        "supreme court",
        "attorney general",
        "legislature",
        "legislative",
        "governor",
        "state agency",
        "county commission",
        "city council",
        "permit",
        "zoning",
        "ordinance",
    ),
}


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Processing service is not configured.")
    return genai.Client(api_key=api_key)


def _article_payload(articles: list[dict[str, Any]]) -> str:
    payload = []

    for article in articles:
        payload.append(
            {
                "article_id": article["article_id"],
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "published_at": article.get("published_at", ""),
                "rss_description": article.get("summary", "")[:1000],
            }
        )

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _is_temporary_error(exc: Exception) -> bool:
    text = str(exc).lower()
    temporary_markers = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "resource_exhausted",
        "unavailable",
        "high demand",
        "rate limit",
        "temporarily",
        "timeout",
        "deadline exceeded",
        "connection reset",
    )
    return any(marker in text for marker in temporary_markers)


def _is_schema_complexity_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "too many states",
        "schema produces a constraint",
        "schema complexity",
        "maximum allowed nesting depth",
    )
    return any(marker in text for marker in markers)


def _is_model_specific_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "model not found",
        "model is not found",
        "model is not available",
        "not supported for this model",
        "unsupported model",
        "permission_denied",
        "permission denied",
    )
    return any(marker in text for marker in markers)


def _model_candidates() -> list[str]:
    ordered = [MODEL_NAME, *FALLBACK_MODEL_NAMES]
    unique: list[str] = []
    for model in ordered:
        model = str(model or "").strip()
        if model and model not in unique:
            unique.append(model)
    return unique


def _thinking_config_for_model(model: str) -> dict[str, Any]:
    model_name = str(model or "").lower()

    # Gemini 2.5 uses thinkingBudget, not thinkingLevel. For the V7 category-only
    # task, zero keeps fallback latency low without asking the model to reason deeply.
    if "gemini-2.5" in model_name:
        return {"thinking_budget": 0}

    # Gemini 3.x uses thinkingLevel.
    if re.search(r"gemini-3(?:\.|-|$)", model_name):
        level = THINKING_LEVEL
        if level not in {"minimal", "low", "medium", "high"}:
            level = "medium"
        return {"thinking_level": level}

    # Unknown/custom models are safest with no explicit thinking option.
    return {}


class PolicySchemaTooComplex(RuntimeError):
    pass


def _generate_structured(prompt: str, schema: dict[str, Any]) -> Any:
    last_error: Exception | None = None

    for model in _model_candidates():
        for attempt in range(MAX_ATTEMPTS):
            try:
                client = _get_client()
                config: dict[str, Any] = {
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "max_output_tokens": 8192,
                }

                thinking_config = _thinking_config_for_model(model)
                if thinking_config:
                    config["thinking_config"] = thinking_config

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )

                if not response.text:
                    raise RuntimeError("Processing returned an empty response.")

                return json.loads(response.text)

            except Exception as exc:
                last_error = exc

                # A schema-state error is structural. Switching models or retrying
                # the same oversized schema wastes requests; the batch classifier
                # will split the batch and construct a smaller schema instead.
                if _is_schema_complexity_error(exc):
                    raise PolicySchemaTooComplex(
                        "Gemini rejected the structured-output schema as too complex."
                    ) from exc

                if _is_temporary_error(exc):
                    if attempt < MAX_ATTEMPTS - 1:
                        time.sleep(2 ** attempt)
                        continue
                    # Traffic/capacity problem: move to the next configured model.
                    break

                if _is_model_specific_error(exc):
                    # Access/model-specific issue: try the next configured model.
                    break

                # Other request errors may still be model/version specific. Do not
                # repeatedly hammer the same model; move to the next candidate once.
                break

    raise RuntimeError("Policy processing is temporarily unavailable.") from last_error


def _verified_article_ids(
    requested_ids: list[str],
    article_lookup: dict[str, dict[str, Any]],
    limit: int,
) -> list[str]:
    verified: list[str] = []

    for article_id in requested_ids:
        if article_id in article_lookup and article_id not in verified:
            verified.append(article_id)
        if len(verified) >= limit:
            break

    return verified


def _clean_display_text(value: object) -> str:
    """
    Normalize text coming directly from RSS feeds for human display.

    V7.2.2 decodes HTML entities, repairs common UTF-8/Windows-1252
    mojibake, removes HTML markup and invisible characters, and
    normalizes Unicode whitespace such as non-breaking spaces.
    """
    text = str(value or "")

    # Decode nested HTML entities such as &amp;amp;, &#8217;, and &nbsp;.
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded

    # Repair common malformed smart punctuation before attempting a codec repair.
    mojibake_replacements = {
        "â€™": "’",
        "â€˜": "‘",
        "â€œ": "“",
        "â€\u009d": "”",
        "â€": "”",
        "â€“": "–",
        "â€”": "—",
        "â€¦": "…",
        "â€¢": "•",
        "â„¢": "™",
        "Â\u00a0": " ",
    }

    for broken, fixed in mojibake_replacements.items():
        text = text.replace(broken, fixed)

    suspicious = ("Ã", "Â", "â€", "â€™", "â€œ", "ðŸ")
    if any(marker in text for marker in suspicious):
        try:
            repaired = text.encode("cp1252").decode("utf-8")
            old_score = sum(text.count(marker) for marker in suspicious)
            new_score = sum(repaired.count(marker) for marker in suspicious)
            if new_score < old_score:
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    for broken, fixed in mojibake_replacements.items():
        text = text.replace(broken, fixed)

    # Stray Â characters are a common RSS encoding artifact.
    text = text.replace("Â", "")

    # Remove markup first, then normalize invisible characters and whitespace.
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # str.split() recognizes Unicode whitespace, including NBSP.
    return " ".join(text.split()).strip()


def _clean_summary(value: object, limit: int = 500) -> str:
    text = _clean_display_text(value)
    text = text.removesuffix("...").strip()

    if not text:
        return "Open the verified source for the full report."

    if len(text) <= limit:
        return text

    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return clipped + "..."


def _fallback_top_stories(
    articles: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    stories: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for article in articles:
        title = str(article.get("title", "")).strip()
        normalized = re.sub(r"\W+", " ", title.lower()).strip()

        if not title or normalized in seen_titles:
            continue

        stories.append(
            {
                "title": title,
                "summary": _clean_summary(article.get("summary")),
                "article_ids": [article.get("article_id", "")],
                "links": [article.get("link", "")],
                "sources": [article.get("source", "Unknown source")],
                "latest_published_at": article.get("published_at", ""),
            }
        )
        seen_titles.add(normalized)

        if len(stories) >= limit:
            break

    return stories


def _fallback_category(article: dict[str, Any]) -> str | None:
    evidence = (
        f"{article.get('title', '')} {article.get('summary', '')}"
    ).lower()

    for category, keywords in FALLBACK_KEYWORDS.items():
        if _contains_any(evidence, keywords):
            return category

    return None


def _fallback_policy_areas(
    articles: list[dict[str, Any]],
    per_category_limit: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    policy_areas: dict[str, list[dict[str, Any]]] = {
        area: [] for area in POLICY_AREAS
    }
    seen_ids: set[str] = set()

    for article in articles:
        article_id = str(article.get("article_id", "")).strip()
        if not article_id or article_id in seen_ids:
            continue

        category = _fallback_category(article)
        if not category:
            continue

        if len(policy_areas[category]) >= per_category_limit:
            continue

        policy_areas[category].append(
            {
                "title": article.get("title", "Headline"),
                "summary": _clean_summary(article.get("summary")),
                "link": article.get("link", ""),
                "source": article.get("source", "Unknown source"),
                "published_at": article.get("published_at", ""),
                "article_id": article_id,
            }
        )
        seen_ids.add(article_id)

    return policy_areas



# POLICY_TRACKER_STRICT_POLICY_GATE_V1
STRICT_EXCLUSION_PHRASES = (
    # Community / lifestyle filler.
    "arts festival",
    "music festival",
    "community festival",
    "live music",
    "performances and more",
    "award recipient",
    "awarded the",
    "recognizes",
    "recognized",
    "honors",
    "honored",
    "swap shop",
    "garage sale",
    "fundraiser",
    "charity event",
    "charity dinner",
    "benefit dinner",
    "register now",
    "sponsored content",
    "advertisement",

    # Routine crime / weather / sports.
    "recent arrests",
    "arrest log",
    "jail bookings",
    "police blotter",
    "crime roundup",
    "sports roundup",
    "sports calendar",
    "high school sports",
    "game recap",
    "weather forecast",
    "red flag warning",
    "heat advisory",
    "weather advisory",
    "winter storm warning",
    "high wind warning",
    "fire weather watch",
    "air quality alert",

    # Obituaries and personal notices.
    "obituary",
    "obituaries",
    "death notice",
    "funeral service",
    "funeral services",
    "memorial service",
    "celebration of life",
    "passed away",
    "surrounded by family",

    # Marriage / divorce / social notices. These are intentionally specific so
    # a genuine policy story about marriage or divorce law is not rejected.
    "marriages and divorces",
    "marriage and divorce",
    "marriage licenses",
    "marriage license applications",
    "divorce filings",
    "divorce decrees",
    "wedding announcements",
    "weddings and engagements",
    "engagement announcements",

    # Opinion / letters are not straight policy news.
    "letter to the editor",
    "letters to the editor",
    "guest opinion",
    "guest column",
    "(opinion)",
    "opinion |",
    "opinion -",
    "editorial:",
    "opinion:",
)

GENERIC_CRIME_PHRASES = (
    "arrested for",
    "charged with",
    "pleads guilty",
    "pleaded guilty",
    "sentenced to",
    "suspect",
    "mugshot",
    "booking",
)

COMMON_POLICY_ACTION_TERMS = (
    "bill",
    "law",
    "legislation",
    "legislature",
    "rule",
    "regulation",
    "policy",
    "ordinance",
    "resolution",
    "budget",
    "appropriation",
    "funding",
    "tax",
    "taxation",
    "revenue",
    "grant",
    "program",
    "hearing",
    "public meeting",
    "board meeting",
    "commission meeting",
    "agenda",
    "vote",
    "voted",
    "approved",
    "denied",
    "adopted",
    "proposed",
    "proposal",
    "lawsuit",
    "court ruling",
    "ruling",
    "injunction",
    "appeal",
    "permit",
    "zoning",
    "license",
    "licensing",
    "agency",
    "department",
    "governor",
    "attorney general",
    "county commission",
    "city council",
    "school board",
    "board of trustees",
)

CATEGORY_POLICY_RULES = {
    "Energy & Natural Resources": {
        "subjects": (
            "energy",
            "oil",
            "natural gas",
            "coal",
            "mining",
            "mineral",
            "rare earth",
            "uranium",
            "nuclear",
            "wind",
            "solar",
            "electricity",
            "utility",
            "power plant",
            "transmission",
            "public lands",
            "water rights",
            "water resources",
            "wildlife management",
            "grizzly",
            "wolf",
            "forest management",
            "drilling",
            "pipeline",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "lease",
            "leasing",
            "royalty",
            "environmental review",
            "conservation plan",
            "delisting",
            "management plan",
        ),
    },
    "Economics & State Budget": {
        "subjects": (
            "budget",
            "tax",
            "revenue",
            "appropriation",
            "state spending",
            "public spending",
            "economic development",
            "business council",
            "housing",
            "workforce housing",
            "property tax",
            "sales tax",
            "grant",
            "subsidy",
            "bond",
            "infrastructure",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "site plan",
            "development agreement",
            "economic impact",
            "fiscal",
        ),
    },
    "Government Transparency, Regulation & Legal Reform": {
        "subjects": (
            "public records",
            "open meetings",
            "transparency",
            "government accountability",
            "ethics",
            "regulation",
            "regulatory",
            "rulemaking",
            "administrative rule",
            "lawsuit",
            "court ruling",
            "supreme court",
            "attorney general",
            "ordinance",
            "zoning",
            "permit",
            "licensing",
            "state agency",
            "county commission",
            "city council",
            "legislature",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS,
    },
    "Education": {
        "subjects": (
            "education",
            "school district",
            "school board",
            "public school",
            "charter school",
            "teacher",
            "student",
            "curriculum",
            "university",
            "community college",
            "superintendent",
            "school funding",
            "education savings account",
            "esa",
            "accreditation",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "recalibration",
            "enrollment policy",
            "governance",
            "closure",
            "consolidation",
            "tuition",
        ),
    },
    "Marijuana / THC": {
        "subjects": (
            "marijuana",
            "cannabis",
            "thc",
            "hemp",
            "delta-8",
            "delta 8",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "ban",
            "legalization",
            "possession limit",
            "testing standard",
        ),
    },
    "Health Care": {
        "subjects": (
            "health care",
            "healthcare",
            "medicaid",
            "medicare",
            "health insurance",
            "hospital",
            "clinic",
            "public health",
            "health department",
            "physician",
            "provider",
            "nursing home",
            "rural health",
            "mental health",
            "vaccine",
            "disease outbreak",
            "measles",
            "reimbursement",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "coverage",
            "benefit",
            "reimbursement",
            "waiver",
            "eligibility",
            "rate setting",
            "public health order",
        ),
    },
    "Campaign Finance & Election Integrity": {
        "subjects": (
            "election",
            "campaign finance",
            "campaign contribution",
            "candidate filing",
            "ballot",
            "voter",
            "voting",
            "primary election",
            "general election",
            "recount",
            "secretary of state",
            "political action committee",
            "pac",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "filing deadline",
            "certification",
            "petition",
            "redistricting",
            "districting",
            "crossover voting",
        ),
    },
    "Criminal Justice": {
        "subjects": (
            "criminal justice",
            "sentencing policy",
            "sentencing reform",
            "corrections",
            "prison",
            "jail policy",
            "parole",
            "probation",
            "prosecution policy",
            "prosecutorial",
            "policing policy",
            "law enforcement policy",
            "court administration",
            "public defender",
            "criminal law",
            "juvenile justice",
        ),
        "actions": COMMON_POLICY_ACTION_TERMS + (
            "sentencing standard",
            "court procedure",
            "charging standard",
            "use of force",
            "body camera",
            "bail reform",
            "pretrial",
        ),
    },
}


# POLICY_TRACKER_BALANCED_COVERAGE_GATE_V3
# Gemini chooses the primary category. The local gate is a sanity check, not a
# second classifier. Keep hard junk exclusions, but do not require short RSS
# descriptions to contain one exact keyword from two separate rigid lists.
BALANCED_CATEGORY_SUBJECT_EXPANSIONS = {
    "Energy & Natural Resources": (
        "water",
        "reservoir",
        "hydroelectric",
        "hydropower",
        "rancher",
        "ranchers",
        "ranching",
        "agriculture",
        "agricultural",
        "livestock",
        "grazing",
        "drought",
        "fishing",
        "angler",
        "anglers",
        "fisheries",
        "game and fish",
        "game and fish department",
        "endangered species",
        "threatened species",
        "species protection",
        "habitat",
        "wildlife",
        "bureau of land management",
        "blm",
        "forest service",
        "land management",
        "conservation",
        "reclamation",
    ),
    "Economics & State Budget": (
        "economy",
        "economic",
        "compensation",
        "compensation agreement",
        "development",
        "workforce",
        "employment",
        "tax relief",
        "revenue forecast",
        "state budget",
        "county budget",
        "city budget",
        "public finance",
        "capital project",
        "public infrastructure",
    ),
    "Government Transparency, Regulation & Legal Reform": (
        "records",
        "records request",
        "unreleased records",
        "public information",
        "freedom of information",
        "foia",
        "open records",
        "government oversight",
        "public board",
        "state board",
        "state commission",
        "agency director",
        "agency head",
        "department director",
        "game and fish department",
        "sheriff",
        "public official",
        "government official",
        "administrative law",
        "legal reform",
    ),
    "Education": (
        "board of education",
        "education board",
        "education department",
        "department of education",
        "school trustees",
        "higher education",
        "uw",
        "university of wyoming",
    ),
    "Marijuana / THC": (
        "cannabinoid",
        "cannabinoids",
        "delta-9",
        "delta 9",
        "synthetic thc",
    ),
    "Health Care": (
        "hospital board",
        "health board",
        "medical board",
        "hospital district",
        "health system",
        "health authority",
        "behavioral health",
        "health facility",
    ),
    "Campaign Finance & Election Integrity": (
        "election administration",
        "election law",
        "election rules",
        "voter registration",
        "election certification",
        "campaign disclosure",
        "campaign spending",
        "political committee",
        "election official",
        "candidate",
        "candidates",
        "campaign",
        "campaigning",
        "legislative race",
        "legislative races",
        "house district",
        "senate district",
        "governor race",
        "governor's race",
        "statewide race",
        "primary race",
        "general election race",
        "endorsement",
        "endorsed",
    ),
    "Criminal Justice": (
        "prosecutor",
        "prosecutors",
        "district attorney",
        "county attorney",
        "law enforcement",
        "police department",
        "sheriff's office",
        "sheriff office",
        "deputy",
        "officer-involved shooting",
        "deputy-involved shooting",
        "use-of-force",
        "use of force",
        "police accountability",
        "law enforcement accountability",
    ),
}

BALANCED_ACTION_EXPANSIONS = (
    "investigation",
    "investigator",
    "investigated",
    "oversight",
    "governance",
    "authority",
    "official action",
    "official response",
    "state response",
    "emergency response",
    "executive order",
    "order",
    "directive",
    "restriction",
    "closure",
    "closed",
    "reopened",
    "standard",
    "definition",
    "agreement",
    "settlement",
    "consent decree",
    "resigns",
    "resigned",
    "resignation",
    "appointed",
    "appointment",
    "nomination",
    "review",
    "audit",
    "records request",
    "contempt order",
    "declared",
    "declaration",
    "emergency declaration",
    "waiver",
    "final warning",
    "cleared",
    "management",
    "management decision",
    "decision",
    "announced",
)

GOVERNMENT_POLICY_SIGNALS = (
    "governor",
    "legislature",
    "legislative",
    "lawmakers",
    "state senate",
    "state house",
    "state agency",
    "department",
    "commission",
    "county commission",
    "city council",
    "town council",
    "school board",
    "board of trustees",
    "public board",
    "secretary of state",
    "attorney general",
    "supreme court",
    "district court",
    "federal court",
    "judge",
    "regulator",
    "regulatory",
    "public records",
    "public hearing",
    "public meeting",
    "official",
    "officials",
    "agency",
    "permit",
    "rule",
    "law",
    "bill",
    "budget",
    "tax",
    "ordinance",
    "resolution",
)

# POLICY_TRACKER_WYOMING_NEXUS_COVERAGE_V4
# Require a material Wyoming connection before an article is sent to Gemini.
# Do not use the publisher name or URL as proof of nexus; local outlets may carry
# national syndicated stories. These signals are searched only in title + RSS text.
WYOMING_NEXUS_SIGNALS = (
    "wyoming",
    "cheyenne",
    "casper",
    "laramie",
    "sheridan",
    "gillette",
    "rock springs",
    "green river",
    "jackson hole",
    "jackson",
    "cody",
    "riverton",
    "rawlins",
    "evanston",
    "torrington",
    "powell",
    "thermopolis",
    "wheatland",
    "lander",
    "douglas",
    "buffalo",
    "newcastle",
    "worland",
    "kemmerer",
    "pinedale",
    "sundance",
    "afton",
    "star valley",
    "wind river",
    "powder river",
    "bighorn basin",
    "big horn basin",
    "natrona county",
    "laramie county",
    "sheridan county",
    "campbell county",
    "fremont county",
    "albany county",
    "carbon county",
    "converse county",
    "crook county",
    "goshen county",
    "hot springs county",
    "johnson county",
    "lincoln county",
    "niobrara county",
    "park county",
    "platte county",
    "sublette county",
    "sweetwater county",
    "teton county",
    "uinta county",
    "washakie county",
    "weston county",
    "university of wyoming",
    "wyoming legislature",
    "wyoming house",
    "wyoming senate",
    "wyoming supreme court",
    "wyoming secretary of state",
    "wyoming department of education",
    "wyoming department of health",
    "wyoming game and fish",
    "wyoming game & fish",
    "wyoming public service commission",
    "wyoming psc",
)

ELECTION_COVERAGE_SIGNALS = (
    "election",
    "elections",
    "candidate",
    "candidates",
    "campaign",
    "campaigning",
    "ballot",
    "voter",
    "voters",
    "voting",
    "primary",
    "general election",
    "legislative race",
    "legislative races",
    "statewide race",
    "house district",
    "senate district",
    "running for",
    "bid for governor",
    "governor race",
    "governor's race",
    "endorsement",
    "endorsed",
    "secretary of state",
    "superintendent of public instruction",
)

POLICY_RECOVERY_SIGNALS = (
    "legislature",
    "legislative",
    "lawmakers",
    "governor",
    "state agency",
    "department",
    "commission",
    "board",
    "public board",
    "county commission",
    "city council",
    "town council",
    "school board",
    "board of trustees",
    "public records",
    "records request",
    "court",
    "judge",
    "lawsuit",
    "complaint",
    "investigation",
    "audit",
    "regulation",
    "regulatory",
    "rule",
    "permit",
    "budget",
    "tax",
    "revenue",
    "appropriation",
    "public funding",
    "public spending",
    "hospital board",
    "health board",
    "university of wyoming",
    "game and fish",
    "public service commission",
) + ELECTION_COVERAGE_SIGNALS

CRIMINAL_JUSTICE_SYSTEM_SIGNALS = (
    "criminal justice",
    "sentencing reform",
    "sentencing standard",
    "court procedure",
    "charging standard",
    "public defender",
    "parole",
    "probation",
    "bail reform",
    "pretrial",
    "use of force",
    "use-of-force",
    "body camera",
    "officer-involved shooting",
    "deputy-involved shooting",
    "police accountability",
    "law enforcement accountability",
    "prosecutor review",
    "prosecutors cleared",
    "internal investigation",
    "department investigation",
    "court ruling",
    "supreme court",
    "appeals court",
    "policy",
    "reform",
    "legislation",
)


def _strict_policy_text(article: dict[str, Any]) -> str:
    return re.sub(
        r"\s+",
        " ",
        (
            f"{article.get('title', '')} "
            f"{article.get('summary', '')}"
        ).lower(),
    ).strip()


def _contains_phrase(
    text: str,
    phrase: str,
) -> bool:
    """
    Match a word or phrase without allowing accidental substring hits.

    Examples this prevents:
    - "pac" matching "impact"
    - "wind" matching "window"
    - "law" matching "Lawrence"
    - "vote" matching "devoted"
    """
    normalized_text = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    normalized_phrase = re.sub(r"\s+", " ", str(phrase or "").lower()).strip()

    if not normalized_text or not normalized_phrase:
        return False

    escaped = re.escape(normalized_phrase).replace(r"\ ", r"\s+")
    pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def _contains_any(
    text: str,
    phrases: tuple[str, ...],
) -> bool:
    return any(
        _contains_phrase(text, phrase)
        for phrase in phrases
    )


def _has_wyoming_nexus(
    article: dict[str, Any],
) -> bool:
    """Return True only when title/RSS evidence materially points to Wyoming."""
    text = _strict_policy_text(article)
    return bool(text) and _contains_any(text, WYOMING_NEXUS_SIGNALS)


def _has_policy_candidate_signal(
    article: dict[str, Any],
) -> bool:
    """
    Identify likely policy stories that deserve a second Gemini review if the
    first pass omitted them. This is a recall helper, not a final classifier.
    """
    if _is_obvious_non_policy_content(article) or not _has_wyoming_nexus(article):
        return False

    text = _strict_policy_text(article)

    if _contains_any(text, POLICY_RECOVERY_SIGNALS):
        return True

    for category, rules in CATEGORY_POLICY_RULES.items():
        subjects = (
            tuple(rules.get("subjects", ()))
            + BALANCED_CATEGORY_SUBJECT_EXPANSIONS.get(category, ())
        )
        if _contains_any(text, subjects):
            return True

    return False


def _is_obvious_non_policy_content(
    article: dict[str, Any],
) -> bool:
    """
    Reject clearly non-policy material before it reaches Gemini or fallback
    classification. This is intentionally conservative: it targets notices and
    recurring filler, not broad policy subjects such as marriage or criminal law.
    """
    text = _strict_policy_text(article)
    if not text:
        return True

    return _contains_any(
        text,
        STRICT_EXCLUSION_PHRASES,
    )


def _passes_strict_policy_gate(
    article: dict[str, Any],
    category: str,
) -> bool:
    """
    Balanced post-Gemini validation.

    Gemini is the primary semantic classifier. This local gate protects against
    obvious junk and clearly unsupported categories without re-classifying every
    short RSS description using brittle exact-keyword requirements.
    """
    rules = CATEGORY_POLICY_RULES.get(category)

    if not rules:
        return False

    text = _strict_policy_text(article)

    if (
        not text
        or _is_obvious_non_policy_content(article)
        or not _has_wyoming_nexus(article)
    ):
        return False

    subjects = (
        tuple(rules.get("subjects", ()))
        + BALANCED_CATEGORY_SUBJECT_EXPANSIONS.get(category, ())
    )
    actions = (
        tuple(rules.get("actions", ()))
        + BALANCED_ACTION_EXPANSIONS
    )

    has_subject = _contains_any(text, subjects)
    has_action = _contains_any(text, actions)
    has_government_signal = _contains_any(text, GOVERNMENT_POLICY_SIGNALS)

    if category == "Criminal Justice":
        has_generic_crime = _contains_any(text, GENERIC_CRIME_PHRASES)
        has_system_signal = _contains_any(text, CRIMINAL_JUSTICE_SYSTEM_SIGNALS)

        # Routine crime coverage remains excluded. Official accountability,
        # court standards, use-of-force reviews and justice-system decisions may
        # pass even when the RSS description does not use the phrase
        # "criminal justice."
        if has_generic_crime and not has_system_signal:
            return False

        return has_subject and (
            has_action
            or has_government_signal
            or has_system_signal
        )

    if category == "Campaign Finance & Election Integrity":
        # Wyoming candidate/race coverage is intentionally in scope. The public
        # office itself is the policy connection even when no election rule or
        # campaign-finance dispute is described in the short RSS text.
        has_election_signal = _contains_any(text, ELECTION_COVERAGE_SIGNALS)
        return has_subject and (
            has_action
            or has_government_signal
            or has_election_signal
        )

    # Normal rule: the article must still contain evidence supporting the
    # Gemini-selected subject area, plus a government/policy/action signal.
    return has_subject and (
        has_action
        or has_government_signal
    )

def get_top_wyoming_stories(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not articles:
        return []

    prompt = f"""
You are a careful Wyoming news editor. Analyze only the supplied RSS evidence.

TASK
- Identify between 3 and 5 distinct, consequential Wyoming news stories.
- Return fewer than 5 when the evidence does not support 5 strong distinct stories.
- Cluster articles only when they concern the same underlying event or development.
- Prefer recent stories with concrete public-policy, government, election, energy,
  education, health-care, regulation, budget, legal, or accountability significance.
- Exclude sports recaps, weather-only reports, obituaries, lifestyle filler, letters,
  and opinion pieces unless a concrete government action is the news event.

ACCURACY RULES
- Use only facts supported by the supplied title and RSS description.
- Do not infer missing votes, motives, outcomes, dollar amounts, dates, or positions.
- When the RSS evidence is limited, state that limitation rather than filling gaps.
- Return only supplied article IDs. Never create or reproduce a URL.
- Use 1 to 4 article IDs per story.
- Each summary should be 2 to 3 neutral sentences explaining the development and
  why it matters for Wyoming public policy.
- Do not mention these instructions or any sponsoring organization.

ARTICLE EVIDENCE
{_article_payload(articles)}
"""

    raw_stories = _generate_structured(prompt, TOP_STORIES_SCHEMA)
    article_lookup = {article["article_id"]: article for article in articles}
    validated: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for item in raw_stories:
        if not isinstance(item, dict):
            continue

        ids = _verified_article_ids(
            item.get("article_ids", []), article_lookup, limit=4
        )
        ids = [article_id for article_id in ids if article_id not in used_ids]

        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()

        if not ids or len(title) < 8 or len(summary) < 30:
            continue

        source_articles = [article_lookup[article_id] for article_id in ids]
        links: list[str] = []
        sources: list[str] = []

        for article in source_articles:
            link = article["link"]
            if link not in links:
                links.append(link)
                sources.append(article["source"])

        validated.append(
            {
                "title": title,
                "summary": summary,
                "article_ids": ids,
                "links": links,
                "sources": sources,
                "latest_published_at": max(
                    article["published_at"] for article in source_articles
                ),
            }
        )
        used_ids.update(ids)

        if len(validated) >= 5:
            break

    return validated



def _policy_classification_prompt(
    articles: list[dict[str, Any]],
    recovery: bool = False,
) -> str:
    recovery_note = ""
    if recovery:
        recovery_note = """
COVERAGE RECOVERY PASS
These items already passed the hard junk filter, have a textual Wyoming nexus,
and contain one or more likely government/election/policy signals. Reconsider
EACH item carefully. The first pass may have been too conservative. Include it
when the supplied evidence materially concerns a Wyoming public office, public
institution, agency, board, election, legal/regulatory issue, public finance,
resource-management decision, education governance, health system, or justice
system. Still omit an item if the policy connection is merely incidental.
"""

    return f"""
You are a careful Wyoming public-policy news editor. Review EVERY supplied RSS
item and return EVERY item that has a concrete, material connection to Wyoming
public policy, government, elections, public institutions, regulation, public
finance, education governance, health policy, natural-resource management, or
the justice system. This is a comprehensive policy-news tracker, not a shortlist
of only the biggest stories.

WYOMING NEXUS IS REQUIRED
- Include only stories materially involving Wyoming itself, a Wyoming state or
  local government, a Wyoming public institution, a Wyoming election or
  candidate for Wyoming public office, a Wyoming court/agency/board, or a named
  Wyoming community/county with a public-policy issue.
- A national story is NOT Wyoming policy news merely because it appears in a
  Wyoming publication or could theoretically affect Wyoming someday.
- Federal action may qualify when the supplied evidence gives a specific Wyoming
  consequence, Wyoming institution, Wyoming official response, Wyoming land or
  resource impact, or Wyoming legal/regulatory effect.

EXACT CATEGORIES
{json.dumps(POLICY_AREAS, ensure_ascii=False)}

WHAT COUNTS AS POLICY NEWS
A story does NOT need to announce a final law or completed vote. Include stories
when the supplied title or RSS description supports a meaningful public-policy
connection such as:
- Wyoming legislative races, candidate profiles/Q&As, campaigns, endorsements,
  contests for governor/secretary of state/superintendent/legislative seats,
  election administration, voting rules, filings, certification or campaign
  finance. Candidate and race coverage is in scope because it concerns control
  of Wyoming public office;
- proposed or adopted laws, rules, ordinances, budgets, taxes or regulations;
- agency actions, leadership changes, official responses, permits, restrictions,
  closures, orders, resource-management decisions or enforcement standards;
- public-board governance, authority, funding, oversight or accountability;
- public-records disputes, official investigations, audits, litigation, court
  rulings, legal definitions, administrative disputes or government ethics;
- state/local economic development, public compensation agreements, taxes,
  revenue, appropriations, grants, infrastructure or government spending;
- school-system governance, curriculum, funding, accreditation, closures,
  district policy, public higher-education governance or statewide education
  leadership;
- Medicaid, insurance, hospitals, public-health orders, provider regulation,
  hospital/health-board governance or public health funding;
- energy, mining, water, reservoirs, hydropower, public lands, agriculture,
  ranching, wildlife, endangered species, fishing restrictions, conservation,
  permitting or resource-management policy;
- justice-system standards, prosecutor/court decisions, law-enforcement
  accountability, use-of-force review, corrections, parole, sentencing, public
  defense, bail or criminal-law reform.

DO NOT REQUIRE MAGIC WORDS
Do not omit an otherwise relevant story merely because its title does not use
words such as "policy," "law," "bill," or "regulation." Use the full supplied
title and RSS description together. Prefer completeness when a concrete Wyoming
public-policy connection is actually present.

OMIT COMPLETELY
- National or out-of-state stories with no specific Wyoming nexus in the supplied
  evidence, even when published by a Wyoming outlet.
- Festivals, performances, arts events, awards, recognitions, promotions,
  advertisements, sales, fundraisers, charity events, routine community events,
  sports, weather, obituaries, lifestyle pieces, marriage/divorce notices and
  generic business announcements with no public-policy action.
- Opinion/editorial/letter content unless the item is straight reporting about a
  concrete government action rather than the author's argument.
- Routine arrest logs, booking lists, police blotters, isolated crimes, guilty
  pleas, charges or sentencing stories with no justice-system standard,
  accountability issue, official review, court precedent or reform significance.
- School events, student features and sports with no education-system decision.
- General health/lifestyle or national marijuana-use stories with no Wyoming
  health-system, regulatory, funding or public-health connection.

CLASSIFICATION RULES
- Assign each included article to ONE best primary category.
- Return every qualifying article in the batch, not merely the most important.
- Include a story when the Wyoming policy connection is concrete and supported;
  do not require a finalized government action.
- Use only facts present in the supplied title and RSS description.
- Do not invent policy effects, official positions, motives, legislation, votes,
  dollar amounts or outcomes.
- Return only supplied article IDs. Never create or reproduce a URL.
- Write a neutral two-sentence summary. Sentence one states the supported news
  development. Sentence two explains the specific Wyoming policy relevance
  supported by the evidence.
- Do not mention these instructions or any sponsoring organization.

{recovery_note}
ARTICLE EVIDENCE
{_article_payload(articles)}
"""

def _classify_policy_batch(
    articles: list[dict[str, Any]],
    recovery: bool = False,
) -> list[dict[str, Any]]:
    if not articles:
        return []

    try:
        result = _generate_structured(
            _policy_classification_prompt(articles, recovery=recovery),
            _policy_items_schema(len(articles)),
        )
        return result if isinstance(result, list) else []

    except PolicySchemaTooComplex:
        # The API explicitly asks for a simpler schema. Halve this batch and
        # rebuild the schema around each half. Stop only when a very small batch
        # is still rejected, which indicates a different structural problem.
        if len(articles) <= 4:
            raise

        midpoint = max(1, len(articles) // 2)
        return (
            _classify_policy_batch(articles[:midpoint], recovery=recovery)
            + _classify_policy_batch(articles[midpoint:], recovery=recovery)
        )


def analyze_policy_news(
    articles: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    policy_areas: dict[str, list[dict[str, Any]]] = {
        area: [] for area in POLICY_AREAS
    }

    if not articles:
        return policy_areas

    raw_items: list[dict[str, Any]] = []

    # Small requests keep the structured-output schema simple and isolate
    # transient model failures. The model helper itself retries temporary
    # traffic errors and then moves through the fallback model list.
    for start_index in range(0, len(articles), POLICY_BATCH_SIZE):
        batch = articles[start_index : start_index + POLICY_BATCH_SIZE]
        raw_items.extend(_classify_policy_batch(batch))

    first_pass_ids = {
        str(item.get("article_id", "")).strip()
        for item in raw_items
        if isinstance(item, dict) and item.get("article_id")
    }

    recovery_candidates = [
        article
        for article in articles
        if article.get("article_id") not in first_pass_ids
        and _has_policy_candidate_signal(article)
    ]

    # A second small-batch pass recovers likely Wyoming policy stories that a
    # conservative first pass omitted. It never bypasses the local junk/nexus
    # validation below.
    for start_index in range(0, len(recovery_candidates), POLICY_BATCH_SIZE):
        batch = recovery_candidates[start_index : start_index + POLICY_BATCH_SIZE]
        raw_items.extend(_classify_policy_batch(batch, recovery=True))

    article_lookup = {
        article["article_id"]: article
        for article in articles
        if article.get("article_id")
    }

    used_ids: set[str] = set()

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        category = item.get("category")
        article_id = item.get("article_id")
        summary = str(item.get("summary", "")).strip()

        if (
            category not in policy_areas
            or article_id not in article_lookup
            or article_id in used_ids
            or len(summary) < 30
        ):
            continue

        article = article_lookup[article_id]

        if not _passes_strict_policy_gate(article, category):
            continue

        policy_areas[category].append(
            {
                "title": article["title"],
                "summary": summary,
                "link": article["link"],
                "source": article["source"],
                "published_at": article["published_at"],
                "article_id": article_id,
            }
        )
        used_ids.add(article_id)

    for stories in policy_areas.values():
        stories.sort(
            key=lambda story: story["published_at"],
            reverse=True,
        )

    return policy_areas



# POLICY_TRACKER_ORGANIZATION_HELPERS_REPAIRED_V1
def _normalized_title_tokens(value: object) -> list[str]:
    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
        "with", "wyoming", "wy",
    }

    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 2 and token not in stop_words
    ]


def _titles_are_near_duplicates(first: object, second: object) -> bool:
    first_tokens = _normalized_title_tokens(first)
    second_tokens = _normalized_title_tokens(second)

    if not first_tokens or not second_tokens:
        return False

    first_text = " ".join(first_tokens)
    second_text = " ".join(second_tokens)

    if first_text == second_text:
        return True

    first_set = set(first_tokens)
    second_set = set(second_tokens)

    overlap = len(first_set & second_set) / max(
        1,
        min(len(first_set), len(second_set)),
    )

    sequence_score = SequenceMatcher(
        None,
        first_text,
        second_text,
    ).ratio()

    return overlap >= 0.72 or sequence_score >= 0.80


def _merge_story_sources(
    target: dict[str, Any],
    incoming: dict[str, Any],
) -> None:
    article_ids = target.setdefault("article_ids", [])

    for article_id in incoming.get("article_ids", []):
        if article_id and article_id not in article_ids:
            article_ids.append(article_id)

    links = target.setdefault("links", [])
    sources = target.setdefault("sources", [])

    incoming_links = incoming.get("links") or [
        incoming.get("link", "")
    ]

    incoming_sources = incoming.get("sources") or [
        incoming.get("source", "Unknown source")
    ]

    for index, link in enumerate(incoming_links):
        if not link or link in links:
            continue

        links.append(link)

        source = (
            incoming_sources[index]
            if index < len(incoming_sources)
            else "Source"
        )

        sources.append(source)

    newest = max(
        str(
            target.get("latest_published_at")
            or target.get("published_at")
            or ""
        ),
        str(
            incoming.get("latest_published_at")
            or incoming.get("published_at")
            or ""
        ),
    )

    target["latest_published_at"] = newest

    if "published_at" in target:
        target["published_at"] = newest


def _dedupe_top_stories(
    top_stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []

    for story in top_stories:
        match = next(
            (
                existing
                for existing in deduplicated
                if _titles_are_near_duplicates(
                    existing.get("title"),
                    story.get("title"),
                )
            ),
            None,
        )

        if match is not None:
            _merge_story_sources(match, story)
            continue

        item = dict(story)

        item["article_ids"] = list(
            dict.fromkeys(item.get("article_ids", []))
        )

        original_links = list(item.get("links", []))
        original_sources = list(item.get("sources", []))

        unique_links = []
        unique_sources = []

        for index, link in enumerate(original_links):
            if not link or link in unique_links:
                continue

            unique_links.append(link)

            unique_sources.append(
                original_sources[index]
                if index < len(original_sources)
                else "Source"
            )

        item["links"] = unique_links
        item["sources"] = unique_sources

        deduplicated.append(item)

    return deduplicated[:5]


def _organize_policy_areas(
    policy_areas: dict[str, list[dict[str, Any]]],
    excluded_article_ids: set[str],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    int,
    int,
]:
    organized = {
        area: []
        for area in POLICY_AREAS
    }

    removed_top_repeats = 0
    grouped_duplicates = 0

    for policy_name in POLICY_AREAS:
        stories = sorted(
            policy_areas.get(policy_name, []),
            key=lambda story: str(
                story.get("published_at", "")
            ),
            reverse=True,
        )

        for story in stories:
            article_id = str(
                story.get("article_id", "")
            ).strip()

            if article_id and article_id in excluded_article_ids:
                removed_top_repeats += 1
                continue

            match = next(
                (
                    existing
                    for existing in organized[policy_name]
                    if _titles_are_near_duplicates(
                        existing.get("title"),
                        story.get("title"),
                    )
                ),
                None,
            )

            if match is not None:
                incoming = dict(story)

                incoming["article_ids"] = (
                    [article_id]
                    if article_id
                    else []
                )

                _merge_story_sources(match, incoming)
                grouped_duplicates += 1
                continue

            item = dict(story)

            item["article_ids"] = (
                [article_id]
                if article_id
                else []
            )

            item["links"] = (
                [item.get("link", "")]
                if item.get("link")
                else []
            )

            item["sources"] = (
                [item.get("source", "Unknown source")]
                if item.get("link")
                else []
            )

            item["source_label"] = item.get(
                "source",
                "Unknown source",
            )

            organized[policy_name].append(item)

        for item in organized[policy_name]:
            source_count = len(item.get("links", []))

            if source_count > 1:
                item["source_label"] = f"{source_count} sources"
            elif item.get("sources"):
                item["source_label"] = item["sources"][0]

    return (
        organized,
        removed_top_repeats,
        grouped_duplicates,
    )

# POLICY_TRACKER_STRICT_FALLBACK_CLEANUP_V1
def _strict_matching_categories(
    article: dict[str, Any],
) -> list[str]:
    matches = [
        category
        for category in POLICY_AREAS
        if _passes_strict_policy_gate(
            article,
            category,
        )
    ]

    government_category = (
        "Government Transparency, Regulation & Legal Reform"
    )

    specific_matches = [
        category
        for category in matches
        if category != government_category
    ]

    if specific_matches:
        return specific_matches

    return matches


def _clean_story_source_buttons(
    story: dict[str, Any],
) -> dict[str, Any]:
    cleaned = dict(story)

    links = list(cleaned.get("links", []))
    sources = list(cleaned.get("sources", []))

    unique_links: list[str] = []
    unique_sources: list[str] = []

    seen_links: set[str] = set()
    seen_sources: set[str] = set()

    for index, link in enumerate(links):
        link_text = str(link or "").strip()

        source = (
            str(sources[index]).strip()
            if index < len(sources)
            else "Source"
        )

        normalized_source = re.sub(
            r"\s+",
            " ",
            source.lower(),
        ).strip()

        if not link_text:
            continue

        if link_text in seen_links:
            continue

        if (
            normalized_source
            and normalized_source in seen_sources
        ):
            continue

        seen_links.add(link_text)

        if normalized_source:
            seen_sources.add(normalized_source)

        unique_links.append(link_text)
        unique_sources.append(source or "Source")

    cleaned["links"] = unique_links
    cleaned["sources"] = unique_sources

    if "source_label" in cleaned:
        if len(unique_sources) > 1:
            cleaned["source_label"] = (
                f"{len(unique_sources)} sources"
            )
        elif unique_sources:
            cleaned["source_label"] = (
                unique_sources[0]
            )

    return cleaned


def _clean_story_collection_sources(
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []

    for story in stories:
        item = dict(story)

        item["title"] = _clean_display_text(
            item.get("title", "Headline")
        ) or "Headline"
        item["summary"] = _clean_summary(item.get("summary", ""))

        if "source" in item:
            item["source"] = (
                _clean_display_text(item.get("source"))
                or "Unknown source"
            )

        if item.get("sources"):
            item["sources"] = [
                _clean_display_text(source) or "Source"
                for source in item.get("sources", [])
            ]

        if item.get("source_label"):
            item["source_label"] = (
                _clean_display_text(item.get("source_label"))
                or "Source"
            )

        cleaned.append(_clean_story_source_buttons(item))

    return cleaned


def _story_passes_strict_top_gate(
    story: dict[str, Any],
    article_lookup: dict[
        str,
        dict[str, Any],
    ],
) -> bool:
    article_ids = story.get(
        "article_ids",
        [],
    )

    for article_id in article_ids:
        article = article_lookup.get(
            article_id
        )

        if article is None:
            continue

        if _strict_matching_categories(article):
            return True

    return False


def _strict_fallback_top_stories(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[
        dict[str, Any]
    ] = []

    for article in sorted(
        articles,
        key=lambda item: str(
            item.get(
                "published_at",
                "",
            )
        ),
        reverse=True,
    ):
        categories = (
            _strict_matching_categories(
                article
            )
        )

        if len(categories) != 1:
            continue

        candidates.append(
            {
                "title": article.get(
                    "title",
                    "Wyoming policy update",
                ),
                "summary": article.get(
                    "summary",
                    "",
                ),
                "article_ids": [
                    article.get(
                        "article_id",
                        "",
                    )
                ],
                "links": [
                    article.get(
                        "link",
                        "",
                    )
                ],
                "sources": [
                    article.get(
                        "source",
                        "Unknown source",
                    )
                ],
                "latest_published_at": (
                    article.get(
                        "published_at",
                        "",
                    )
                ),
            }
        )

        if len(candidates) >= 12:
            break

    candidates = _dedupe_top_stories(
        candidates
    )

    return _clean_story_collection_sources(
        candidates[:5]
    )


def _strict_fallback_policy_areas(
    articles: list[dict[str, Any]],
) -> dict[
    str,
    list[dict[str, Any]],
]:
    policy_areas: dict[
        str,
        list[dict[str, Any]],
    ] = {
        area: []
        for area in POLICY_AREAS
    }

    used_ids: set[str] = set()

    for article in sorted(
        articles,
        key=lambda item: str(
            item.get(
                "published_at",
                "",
            )
        ),
        reverse=True,
    ):
        article_id = str(
            article.get(
                "article_id",
                "",
            )
        ).strip()

        if not article_id:
            continue

        if article_id in used_ids:
            continue

        categories = (
            _strict_matching_categories(
                article
            )
        )

        if len(categories) != 1:
            continue

        category = categories[0]

        policy_areas[category].append(
            {
                "title": article.get(
                    "title",
                    "Wyoming policy update",
                ),
                "summary": article.get(
                    "summary",
                    "",
                ),
                "link": article.get(
                    "link",
                    "",
                ),
                "source": article.get(
                    "source",
                    "Unknown source",
                ),
                "published_at": (
                    article.get(
                        "published_at",
                        "",
                    )
                ),
                "article_id": article_id,
            }
        )

        used_ids.add(article_id)

    return policy_areas


def _fast_top_stories_v7(
    categories: dict[str, list[dict[str, Any]]],
    max_items: int = 4,
) -> list[dict[str, Any]]:
    """
    Build the collapsed Top Wyoming Stories section without another Gemini call.

    Prefer the newest story from different policy areas first, then fill from the
    newest remaining policy stories. Other News is used only when no policy story
    is available. This keeps the feature useful while eliminating a full extra
    model request over the entire eligible article set.
    """
    max_items = max(0, int(max_items))
    if max_items == 0:
        return []

    policy_candidates: list[dict[str, Any]] = []
    other_candidates: list[dict[str, Any]] = []

    for category in NEWS_CATEGORIES:
        for story in categories.get(category, []):
            item = dict(story)
            item["_category_v7"] = category
            if category == OTHER_NEWS_CATEGORY:
                other_candidates.append(item)
            else:
                policy_candidates.append(item)

    def sort_key(story: dict[str, Any]) -> str:
        return str(story.get("published_at", ""))

    policy_candidates.sort(key=sort_key, reverse=True)
    other_candidates.sort(key=sort_key, reverse=True)

    selected: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_categories: set[str] = set()

    # First, favor category diversity among current policy stories.
    for story in policy_candidates:
        category = str(story.get("_category_v7", ""))
        article_id = str(story.get("article_id", "")).strip()
        if category in used_categories or (article_id and article_id in used_ids):
            continue
        selected.append(story)
        used_categories.add(category)
        if article_id:
            used_ids.add(article_id)
        if len(selected) >= max_items:
            break

    # Then fill with the newest remaining policy stories.
    if len(selected) < max_items:
        for story in policy_candidates:
            article_id = str(story.get("article_id", "")).strip()
            if article_id and article_id in used_ids:
                continue
            selected.append(story)
            if article_id:
                used_ids.add(article_id)
            if len(selected) >= max_items:
                break

    # If the cycle has no policy stories, still provide a few current Wyoming items.
    if not selected:
        selected = other_candidates[:max_items]

    cleaned: list[dict[str, Any]] = []
    for story in selected[:max_items]:
        item = dict(story)
        item.pop("_category_v7", None)
        item["latest_published_at"] = item.get("published_at", "")
        if not item.get("article_ids"):
            article_id = str(item.get("article_id", "")).strip()
            item["article_ids"] = [article_id] if article_id else []
        if not item.get("links") and item.get("link"):
            item["links"] = [item["link"]]
        if not item.get("sources") and item.get("source"):
            item["sources"] = [item["source"]]
        cleaned.append(item)

    return _clean_story_collection_sources(cleaned)


def process_news(
    articles: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
]:
    metadata: dict[str, Any] = {
        "errors": [],
        "used_fallback": False,
        "used_strict_fallback": False,
        "removed_top_story_repeats": 0,
        "grouped_policy_duplicates": 0,
        "strict_policy_gate": True,
        "policy_gate_mode": "wyoming_nexus_recovery_v4",
    }

    after_junk_filter = [
        article
        for article in articles
        if not _is_obvious_non_policy_content(article)
    ]

    eligible_articles = [
        article
        for article in after_junk_filter
        if _has_wyoming_nexus(article)
    ]

    metadata["prefiltered_non_policy_count"] = (
        len(articles) - len(after_junk_filter)
    )
    metadata["prefiltered_non_wyoming_count"] = (
        len(after_junk_filter) - len(eligible_articles)
    )
    metadata["wyoming_nexus_gate"] = True

    article_lookup = {
        article.get("article_id", ""): article
        for article in eligible_articles
        if article.get("article_id")
    }

    try:
        top_stories = get_top_wyoming_stories(
            eligible_articles
        )

    except Exception:
        top_stories = []
        metadata["errors"].append(
            "top_stories"
        )

    top_stories = _dedupe_top_stories(
        top_stories
    )

    top_stories = [
        story
        for story in top_stories
        if _story_passes_strict_top_gate(
            story,
            article_lookup,
        )
    ]

    top_stories = (
        _clean_story_collection_sources(
            top_stories
        )
    )

    if not top_stories and eligible_articles:
        top_stories = (
            _strict_fallback_top_stories(
                eligible_articles
            )
        )

        metadata["used_fallback"] = True
        metadata[
            "used_strict_fallback"
        ] = True

    top_article_ids = {
        article_id
        for story in top_stories
        for article_id in story.get(
            "article_ids",
            [],
        )
        if article_id
    }

    try:
        policy_areas = analyze_policy_news(
            eligible_articles
        )

        policy_item_count = sum(
            len(stories)
            for stories
            in policy_areas.values()
        )

        if (
            policy_item_count == 0
            and eligible_articles
        ):
            policy_areas = (
                _strict_fallback_policy_areas(
                    eligible_articles
                )
            )

            metadata["used_fallback"] = True
            metadata[
                "used_strict_fallback"
            ] = True

    except Exception:
        policy_areas = (
            _strict_fallback_policy_areas(
                eligible_articles
            )
        )

        metadata["errors"].append(
            "policy_breakdown"
        )
        metadata["used_fallback"] = True
        metadata[
            "used_strict_fallback"
        ] = True

    (
        policy_areas,
        removed_top_repeats,
        grouped_policy_duplicates,
    ) = _organize_policy_areas(
        policy_areas,
        top_article_ids,
    )

    for policy_name in POLICY_AREAS:
        policy_areas[policy_name] = (
            _clean_story_collection_sources(
                policy_areas.get(
                    policy_name,
                    [],
                )
            )
        )

    metadata[
        "removed_top_story_repeats"
    ] = removed_top_repeats

    metadata[
        "grouped_policy_duplicates"
    ] = grouped_policy_duplicates

    metadata["top_story_count"] = len(
        top_stories
    )

    metadata["policy_item_count"] = sum(
        len(stories)
        for stories in policy_areas.values()
    )

    return (
        top_stories,
        policy_areas,
        metadata,
    )
# POLICY_TRACKER_EIGHT_AREAS_OTHER_NEWS_V5
# The eight official policy areas remain POLICY_AREAS. Every useful Wyoming
# article that survives the hard junk + Wyoming-nexus filters is retained in
# exactly one selectable category. Stories without a well-supported policy-area
# fit go to Other News rather than being discarded or forced into a bad bucket.
OTHER_NEWS_CATEGORY = "Other News"
NEWS_CATEGORIES = [*POLICY_AREAS, OTHER_NEWS_CATEGORY]

V5_ROUTINE_OTHER_PHRASES = (
    "health and food inspections",
    "restaurant inspections",
    "food inspections",
    "inspection report",
    "wildfire update",
    "fire update",
    "percent contained",
    "acres burned",
    "black bear",
    "bear encounter",
    "bear attack",
)

V5_POLICY_ACTION_SIGNALS = tuple(dict.fromkeys(
    COMMON_POLICY_ACTION_TERMS
    + BALANCED_ACTION_EXPANSIONS
    + GOVERNMENT_POLICY_SIGNALS
    + (
        "management plan",
        "management decision",
        "public comment",
        "public input",
        "administrative action",
        "official review",
        "board action",
        "agency action",
        "funding decision",
        "rate case",
        "rate increase",
        "rate decrease",
        "standards",
        "requirement",
        "requirements",
    )
))


def _news_items_schema_v5(max_items: int) -> dict[str, Any]:
    """
    V7 speed schema: Gemini only chooses a category for each supplied article ID.
    The visible summary comes directly from the RSS source evidence, which reduces
    output tokens and avoids asking the model to rewrite every article.
    """
    limit = max(1, min(POLICY_BATCH_SIZE, int(max_items)))
    return {
        "type": "array",
        "minItems": 0,
        "maxItems": limit,
        "items": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": NEWS_CATEGORIES},
                "article_id": {"type": "string"},
            },
            "required": ["category", "article_id"],
        },
    }


def _news_classification_prompt_v5(
    articles: list[dict[str, Any]],
    recovery: bool = False,
) -> str:
    recovery_note = (
        "RECOVERY PASS: These articles were omitted from an earlier batch. "
        "Return every supplied article ID exactly once.\n"
        if recovery
        else ""
    )

    return f"""
You are a rigorous Wyoming news desk categorizer. The supplied articles already
passed a hard junk filter and a Wyoming-nexus filter. Your job is NOT to decide
whether an article is important enough to keep. Your job is to place EVERY
supplied article into exactly ONE accurate category.

RETURN EVERY ARTICLE
- Return every supplied article_id exactly once.
- Never omit an article because it is ordinary, local, or not a policy story.
- If none of the eight policy areas is clearly supported, use Other News.
- Never force an article into a policy area just to avoid Other News.

CATEGORIES
1. Energy & Natural Resources
   Energy production and utilities; oil, gas, coal, nuclear, wind, solar;
   mining/minerals; water and reservoirs; public lands; agriculture/ranching
   policy; wildlife/resource management; conservation; endangered species;
   Forest Service/BLM/Game & Fish management decisions.

2. Economics & State Budget
   State/local budgets, taxes, revenue, appropriations, public spending,
   economic-development policy, workforce policy, government compensation,
   infrastructure finance, public grants, and government fiscal decisions.

3. Government Transparency, Regulation & Legal Reform
   Public records, open meetings, ethics, audits, agency/local-government
   governance, regulations, licensing, permits, ordinances, administrative law,
   civil legal reform, official accountability, and government oversight when
   another more specific category does not fit better.

4. Education
   K-12 and higher-education governance, school finance, school choice,
   curriculum, standards, accreditation, district policy, teachers, public
   colleges, University of Wyoming governance, and education administration.

5. Marijuana / THC
   Wyoming marijuana, cannabis, THC, hemp, cannabinoid regulation,
   legalization, restrictions, testing, possession, or enforcement policy.

6. Health Care
   Medicaid/Medicare, health insurance, hospitals and health systems, provider
   regulation, public-health policy, health funding, behavioral health,
   hospital/health-board governance, and health-care access or delivery policy.

7. Campaign Finance & Election Integrity
   Wyoming candidates and campaigns, legislative/statewide races, campaign
   finance, elections, voting, ballots, election administration, filings,
   certification, voter rules, and contests for Wyoming public office.

8. Criminal Justice
   Criminal law and procedure, policing accountability, prosecution standards,
   courts in criminal matters, corrections, prisons/jails, parole/probation,
   sentencing, bail, public defense, use-of-force review, and justice reform.

9. Other News
   Wyoming-relevant straight news that does not clearly fit one of the eight
   policy areas. Examples include routine wildfire status updates, wildlife
   incidents, ordinary public-safety/community news, routine inspections, and
   other current Wyoming reporting without a direct policy-area connection.

ACCURACY / BOUNDARY RULES
- Use only the supplied title and RSS description. Do not invent missing facts.
- A subject word alone does not make a story policy news. Example: a routine
  bear incident is Other News, while a Game & Fish rule or wildlife-management
  decision is Energy & Natural Resources.
- A routine wildfire status update is Other News unless the actual news is a
  land-management rule, closure decision, funding action, regulation, or policy.
- Routine food/restaurant inspection listings are Other News, not Health Care.
- A clerk office closure is not Election Integrity unless the evidence connects
  it to voting/election administration.
- Candidate profiles, election Q&As, campaign developments, endorsements, and
  public-office races belong in Campaign Finance & Election Integrity.
- Straight reporting about an agency resignation, public-records dispute,
  government audit, regulation, or local-government action can belong in
  Government Transparency, Regulation & Legal Reform.
- Prefer Other News over a speculative policy assignment.
- Return only the category and supplied article_id required by the response schema.
- Do not write article summaries; the tracker displays the source-provided RSS description.
- Return only supplied article IDs. Never create or reproduce URLs.

{recovery_note}ARTICLE EVIDENCE
{_article_payload(articles)}
""".strip()


def _classify_news_batch_v5(
    articles: list[dict[str, Any]],
    recovery: bool = False,
) -> list[dict[str, Any]]:
    if not articles:
        return []

    try:
        result = _generate_structured(
            _news_classification_prompt_v5(articles, recovery=recovery),
            _news_items_schema_v5(len(articles)),
        )
        return result if isinstance(result, list) else []
    except PolicySchemaTooComplex:
        if len(articles) <= 4:
            raise
        midpoint = max(1, len(articles) // 2)
        return (
            _classify_news_batch_v5(articles[:midpoint], recovery=recovery)
            + _classify_news_batch_v5(articles[midpoint:], recovery=recovery)
        )


def _routine_story_belongs_in_other_v5(
    article: dict[str, Any],
    category: str,
) -> bool:
    text = _strict_policy_text(article)
    if not text or category == OTHER_NEWS_CATEGORY:
        return False

    has_policy_action = _contains_any(text, V5_POLICY_ACTION_SIGNALS)

    if category == "Health Care" and _contains_any(
        text,
        (
            "health and food inspections",
            "restaurant inspections",
            "food inspections",
            "inspection report",
        ),
    ):
        return True

    if category == "Energy & Natural Resources":
        routine_fire = _contains_any(
            text,
            (
                "wildfire update",
                "fire update",
                "percent contained",
                "acres burned",
            ),
        )
        routine_wildlife = _contains_any(
            text,
            (
                "black bear",
                "bear encounter",
                "bear attack",
            ),
        )
        if (routine_fire or routine_wildlife) and not has_policy_action:
            return True

    return False


def _policy_category_plausible_v5(
    article: dict[str, Any],
    category: str,
) -> bool:
    """Conservative local sanity check; uncertain assignments become Other News."""
    if category not in POLICY_AREAS:
        return False

    if (
        _is_obvious_non_policy_content(article)
        or not _has_wyoming_nexus(article)
        or _routine_story_belongs_in_other_v5(article, category)
    ):
        return False

    text = _strict_policy_text(article)
    rules = CATEGORY_POLICY_RULES.get(category, {})
    subjects = (
        tuple(rules.get("subjects", ()))
        + BALANCED_CATEGORY_SUBJECT_EXPANSIONS.get(category, ())
        + tuple(FALLBACK_KEYWORDS.get(category, ()))
    )

    has_subject = _contains_any(text, tuple(dict.fromkeys(subjects)))
    has_action = _contains_any(text, V5_POLICY_ACTION_SIGNALS)

    if category == "Campaign Finance & Election Integrity":
        return _contains_any(text, ELECTION_COVERAGE_SIGNALS) or has_subject

    if category == "Criminal Justice":
        if _contains_any(text, GENERIC_CRIME_PHRASES) and not _contains_any(
            text,
            CRIMINAL_JUSTICE_SYSTEM_SIGNALS,
        ):
            return False
        return has_subject and (
            has_action
            or _contains_any(text, CRIMINAL_JUSTICE_SYSTEM_SIGNALS)
        )

    if category == "Government Transparency, Regulation & Legal Reform":
        return (has_subject or _contains_any(text, GOVERNMENT_POLICY_SIGNALS)) and has_action

    return has_subject and has_action


def _validated_news_category_v5(
    article: dict[str, Any],
    requested_category: object,
) -> str:
    category = str(requested_category or "").strip()

    if category == OTHER_NEWS_CATEGORY:
        return OTHER_NEWS_CATEGORY

    if category in POLICY_AREAS and _policy_category_plausible_v5(article, category):
        return category

    return OTHER_NEWS_CATEGORY


def _fallback_news_category_v5(article: dict[str, Any]) -> str:
    candidate = _fallback_category(article)
    if candidate in POLICY_AREAS and _policy_category_plausible_v5(article, candidate):
        return candidate
    return OTHER_NEWS_CATEGORY


def analyze_policy_news(
    articles: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """V5: retain every eligible Wyoming article in one of 8 areas or Other News."""
    categories: dict[str, list[dict[str, Any]]] = {
        category: [] for category in NEWS_CATEGORIES
    }
    if not articles:
        return categories

    raw_items: list[dict[str, Any]] = []

    # First pass: categorize all eligible articles in small structured batches.
    for start_index in range(0, len(articles), POLICY_BATCH_SIZE):
        batch = articles[start_index : start_index + POLICY_BATCH_SIZE]
        try:
            raw_items.extend(_classify_news_batch_v5(batch))
        except Exception:
            # Do not lose the whole update because one model/batch is unavailable.
            # Missing articles are retried below and then locally assigned.
            continue

    returned_ids = {
        str(item.get("article_id", "")).strip()
        for item in raw_items
        if isinstance(item, dict) and item.get("article_id")
    }

    missing_articles = [
        article
        for article in articles
        if str(article.get("article_id", "")).strip() not in returned_ids
    ]

    # Second pass: every omission gets one recovery attempt, regardless of topic.
    for start_index in range(0, len(missing_articles), POLICY_BATCH_SIZE):
        batch = missing_articles[start_index : start_index + POLICY_BATCH_SIZE]
        try:
            raw_items.extend(_classify_news_batch_v5(batch, recovery=True))
        except Exception:
            continue

    article_lookup = {
        str(article.get("article_id", "")).strip(): article
        for article in articles
        if str(article.get("article_id", "")).strip()
    }

    # Keep the first valid model response for each supplied ID.
    response_by_id: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        article_id = str(item.get("article_id", "")).strip()
        if article_id in article_lookup and article_id not in response_by_id:
            response_by_id[article_id] = item

    for article in articles:
        article_id = str(article.get("article_id", "")).strip()
        if not article_id:
            continue

        response = response_by_id.get(article_id, {})
        category = _validated_news_category_v5(
            article,
            response.get("category"),
        ) if response else _fallback_news_category_v5(article)

        # V7: use the source-provided RSS description instead of generating a
        # separate AI summary for every article. This is faster and more source-faithful.
        summary = _clean_summary(article.get("summary"))

        categories[category].append(
            {
                "title": article.get("title", "Headline"),
                "summary": summary,
                "link": article.get("link", ""),
                "source": article.get("source", "Unknown source"),
                "published_at": article.get("published_at", ""),
                "article_id": article_id,
            }
        )

    for stories in categories.values():
        stories.sort(key=lambda story: str(story.get("published_at", "")), reverse=True)

    return categories


def _organize_news_categories_v5(
    categories: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Deduplicate within each category without removing Top Story articles."""
    organized = {category: [] for category in NEWS_CATEGORIES}
    grouped_duplicates = 0

    for category in NEWS_CATEGORIES:
        stories = sorted(
            categories.get(category, []),
            key=lambda story: str(story.get("published_at", "")),
            reverse=True,
        )

        for story in stories:
            article_id = str(story.get("article_id", "")).strip()
            match = next(
                (
                    existing
                    for existing in organized[category]
                    if _titles_are_near_duplicates(
                        existing.get("title"),
                        story.get("title"),
                    )
                ),
                None,
            )

            if match is not None:
                incoming = dict(story)
                incoming["article_ids"] = [article_id] if article_id else []
                _merge_story_sources(match, incoming)
                grouped_duplicates += 1
                continue

            item = dict(story)
            item["article_ids"] = [article_id] if article_id else []
            item["links"] = [item.get("link", "")] if item.get("link") else []
            item["sources"] = [item.get("source", "Unknown source")] if item.get("link") else []
            item["source_label"] = item.get("source", "Unknown source")
            organized[category].append(item)

        for item in organized[category]:
            source_count = len(item.get("links", []))
            if source_count > 1:
                item["source_label"] = f"{source_count} sources"
            elif item.get("sources"):
                item["source_label"] = item["sources"][0]

    return organized, grouped_duplicates


def _fallback_all_news_categories_v5(
    articles: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    categories = {category: [] for category in NEWS_CATEGORIES}
    for article in articles:
        article_id = str(article.get("article_id", "")).strip()
        if not article_id:
            continue
        category = _fallback_news_category_v5(article)
        categories[category].append(
            {
                "title": article.get("title", "Headline"),
                "summary": _clean_summary(article.get("summary")),
                "link": article.get("link", ""),
                "source": article.get("source", "Unknown source"),
                "published_at": article.get("published_at", ""),
                "article_id": article_id,
            }
        )
    return categories


def process_news(
    articles: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
]:
    metadata: dict[str, Any] = {
        "errors": [],
        "used_fallback": False,
        "used_strict_fallback": False,
        "grouped_policy_duplicates": 0,
        "category_mode": "eight_policy_areas_plus_other_v5",
        "hard_junk_filter": True,
        "wyoming_nexus_gate": True,
        "speed_mode": "v7_category_only_low_thinking_local_top_stories",
        "ai_top_stories": False,
        "classification_batch_size": POLICY_BATCH_SIZE,
        "classification_thinking_level": THINKING_LEVEL,
        "source_summaries": True,
    }

    after_junk_filter = [
        article for article in articles if not _is_obvious_non_policy_content(article)
    ]
    eligible_articles = [
        article for article in after_junk_filter if _has_wyoming_nexus(article)
    ]

    metadata["prefiltered_non_policy_count"] = len(articles) - len(after_junk_filter)
    metadata["prefiltered_non_wyoming_count"] = len(after_junk_filter) - len(eligible_articles)
    metadata["eligible_wyoming_news_count"] = len(eligible_articles)

    # V7 performs the required AI work only once: category assignment. The
    # categorizer still retains every eligible Wyoming story in exactly one bucket.
    try:
        categories = analyze_policy_news(eligible_articles)
    except Exception:
        categories = _fallback_all_news_categories_v5(eligible_articles)
        metadata["errors"].append("news_categories")
        metadata["used_fallback"] = True

    categories, grouped_duplicates = _organize_news_categories_v5(categories)

    for category in NEWS_CATEGORIES:
        categories[category] = _clean_story_collection_sources(
            categories.get(category, [])
        )

    # Top Stories is collapsed in the UI and no longer warrants a separate,
    # expensive model call. Build it deterministically from the categorized news.
    top_stories = _fast_top_stories_v7(categories, max_items=4)

    metadata["grouped_policy_duplicates"] = grouped_duplicates
    metadata["top_story_count"] = len(top_stories)
    metadata["categorized_story_count"] = sum(
        len(stories) for stories in categories.values()
    )
    metadata["policy_item_count"] = sum(
        len(categories.get(category, [])) for category in POLICY_AREAS
    )
    metadata["other_news_count"] = len(categories.get(OTHER_NEWS_CATEGORY, []))
    metadata["category_counts"] = {
        category: len(categories.get(category, []))
        for category in NEWS_CATEGORIES
    }

    return top_stories, categories, metadata
