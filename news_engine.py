import calendar
import html
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup


CATEGORIES = [
    "State Government, Legislature & Elections",
    "Taxes, Budget & Economy",
    "Education",
    "Energy, Minerals & Utilities",
    "Public Lands, Water & Agriculture",
    "Health Care",
    "Local Government, Housing & Development",
    "Courts, Criminal Justice & Civil Liberties",
    "Transparency, Regulation & Accountability",
]

DEFAULT_FEEDS = [
    {"source": "WyoFile", "url": "https://wyofile.com/feed/"},
    {"source": "Wyoming Public Media", "url": "https://www.wyomingpublicmedia.org/rss.xml"},
    {"source": "Cowboy State Daily", "url": "https://cowboystatedaily.com/rss.xml"},
    {"source": "Wyoming Tribune Eagle", "url": "https://www.wyomingnews.com/search/?f=rss&t=article&c=news/local&l=50&s=start_time&sd=desc"},
    {"source": "Casper Star-Tribune", "url": "https://trib.com/search/?f=rss&t=article&l=50&s=start_time&sd=desc"},
    {"source": "Oil City News", "url": "https://oilcity.news/feed/"},
    {"source": "Cap City News", "url": "https://capcity.news/feed/"},
    {"source": "Jackson Hole News&Guide", "url": "https://www.jhnewsandguide.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc"},
    {"source": "Gillette News Record", "url": "https://www.gillettenewsrecord.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc"},
    {"source": "Sheridan Media", "url": "https://sheridanmedia.com/feed/"},
]

CATEGORY_KEYWORDS = {
    CATEGORIES[0]: (
        "legislature", "legislative", "lawmakers", "state senate", "state house", "house district",
        "senate district", "governor", "secretary of state", "state auditor", "state treasurer",
        "superintendent of public instruction", "election", "primary", "candidate", "campaign", "ballot",
        "voter", "voting", "recount", "redistricting", "crossover voting", "appointment", "state board",
    ),
    CATEGORIES[1]: (
        "budget", "appropriation", "property tax", "sales tax", "tax relief", "revenue", "state spending",
        "public spending", "grant", "bond", "economic development", "economy", "workforce", "business council",
        "subsidy", "incentive", "compensation", "fiscal", "revenue forecast", "severance tax",
    ),
    CATEGORIES[2]: (
        "education", "school", "school district", "school board", "teacher", "student", "curriculum",
        "charter school", "school choice", "education savings account", "esa", "recalibration",
        "university of wyoming", "community college", "accreditation", "tuition", "school funding",
    ),
    CATEGORIES[3]: (
        "energy", "oil", "natural gas", "coal", "mining", "mineral", "uranium", "nuclear", "wind", "solar",
        "electricity", "utility", "power plant", "transmission", "pipeline", "drilling", "royalty",
        "public service commission", "rate case", "terrapower", "rare earth", "critical minerals", "data center power",
    ),
    CATEGORIES[4]: (
        "public lands", "bureau of land management", "blm", "forest service", "water rights", "reservoir", "river",
        "drought", "agriculture", "ranch", "rancher", "livestock", "grazing", "wildlife", "game and fish",
        "grizzly", "wolf", "endangered species", "habitat", "conservation", "reclamation", "fishing", "hunting",
    ),
    CATEGORIES[5]: (
        "health care", "healthcare", "medicaid", "medicare", "health insurance", "hospital", "clinic", "physician",
        "provider", "nursing home", "rural health", "public health", "behavioral health", "mental health", "vaccine",
        "measles", "reimbursement", "health department", "hospital district", "health authority",
    ),
    CATEGORIES[6]: (
        "county commission", "county commissioners", "city council", "town council", "municipal", "annexation",
        "zoning", "land use", "planning commission", "housing", "affordable housing", "workforce housing",
        "development agreement", "subdivision", "local government", "city budget", "county budget", "infrastructure",
        "data center", "building permit", "master plan",
    ),
    CATEGORIES[7]: (
        "criminal justice", "criminal law", "sentencing", "corrections", "prison", "jail", "parole", "probation",
        "public defender", "prosecutor", "law enforcement", "police", "sheriff", "use of force", "body camera",
        "bail", "supreme court", "district court", "court ruling", "lawsuit", "injunction", "appeal",
        "first amendment", "free speech", "civil liberties", "due process", "constitutional",
    ),
    CATEGORIES[8]: (
        "public records", "open records", "open meetings", "transparency", "government accountability", "ethics",
        "audit", "regulation", "regulatory", "rulemaking", "administrative rule", "licensing", "oversight",
        "public information", "records request", "administrative law", "inspector general", "disclosure",
    ),
}

POLICY_SIGNALS = (
    "bill", "law", "legislation", "legislature", "legislative", "committee", "governor", "election", "primary",
    "candidate", "campaign", "ballot", "voter", "budget", "appropriation", "funding", "tax", "revenue", "grant",
    "bond", "rule", "regulation", "regulatory", "rulemaking", "ordinance", "resolution", "permit", "license",
    "zoning", "public records", "open meeting", "audit", "ethics", "lawsuit", "court", "judge", "injunction",
    "appeal", "department", "agency", "commission", "board", "county commission", "city council", "town council",
    "school board", "board of trustees", "public hearing", "public meeting", "public comment", "approved", "denied",
    "adopted", "proposed", "proposal", "waiver", "rate case", "medicaid", "public health", "school funding",
    "curriculum", "public lands", "water rights", "management plan", "lease", "royalty", "utility",
    "economic development", "housing", "infrastructure", "annexation", "development agreement",
)

JUNK_PHRASES = (
    "obituary", "obituaries", "death notice", "funeral service", "marriage licenses", "marriages and divorces",
    "letter to the editor", "letters to the editor", "guest opinion", "guest column", "editorial:", "opinion:",
    "sports roundup", "game recap", "high school sports", "weather forecast", "weather advisory", "red flag warning",
    "garage sale", "swap shop", "fundraiser", "community calendar", "arts festival", "music festival", "live music",
    "sponsored content", "advertisement", "recent arrests", "arrest log", "jail bookings", "police blotter",
)

ROUTINE_CRIME = (
    "arrested for", "charged with", "pleads guilty", "pleaded guilty", "sentenced to", "booking", "mugshot",
)

JUSTICE_POLICY = (
    "court ruling", "supreme court", "appeal", "injunction", "policy", "reform", "use of force", "accountability",
    "public defender", "legislation", "constitutional", "civil liberties", "first amendment",
)

WYOMING_SIGNALS = (
    "wyoming", "cheyenne", "casper", "laramie", "sheridan", "gillette", "rock springs", "green river", "jackson",
    "cody", "riverton", "rawlins", "evanston", "torrington", "powell", "thermopolis", "wheatland", "lander",
    "douglas", "buffalo", "newcastle", "worland", "kemmerer", "pinedale", "sundance", "afton", "star valley",
    "wind river", "natrona county", "laramie county", "sheridan county", "campbell county", "fremont county",
    "albany county", "carbon county", "converse county", "crook county", "goshen county", "hot springs county",
    "johnson county", "lincoln county", "niobrara county", "park county", "platte county", "sublette county",
    "sweetwater county", "teton county", "uinta county", "washakie county", "weston county", "university of wyoming",
)

STOP_WORDS = {
    "the", "and", "for", "from", "with", "this", "that", "into", "after", "amid", "over", "under", "more",
    "new", "says", "said", "say", "state", "local", "wyoming", "will", "would", "could", "about", "their",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 WyomingPolicyNewsTracker/3.0",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).replace("\u200b", "").strip()


def contains_phrase(text: str, value: str) -> bool:
    escaped = re.escape(value.lower()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.lower()) is not None


def contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(contains_phrase(text, value) for value in values)


def configured_feeds() -> list[dict[str, str]]:
    feeds = [] if os.getenv("RSS_APP_ONLY", "").lower() in {"1", "true", "yes"} else list(DEFAULT_FEEDS)
    raw = os.getenv("RSS_APP_FEEDS_JSON", "").strip()
    if not raw:
        return feeds

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return feeds

    if not isinstance(items, list):
        return feeds

    for item in items:
        if not isinstance(item, dict):
            continue
        source = clean_text(item.get("source", "RSS.app")) or "RSS.app"
        url = str(item.get("url", "")).strip()
        category = clean_text(item.get("category", ""))
        if url.startswith("http://") or url.startswith("https://"):
            feeds.append({"source": source, "url": url, "category": category})
    return feeds


def entry_datetime(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed") or entry.get("created_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def entry_summary(entry: Any) -> str:
    candidates: list[str] = []
    for content_item in entry.get("content", []) or []:
        value = clean_text(content_item.get("value", ""))
        if value:
            candidates.append(value)
    for key in ("summary", "description", "subtitle"):
        value = clean_text(entry.get(key, ""))
        if value:
            candidates.append(value)
    if not candidates:
        return "Open the linked coverage for full details."
    return max(candidates, key=len)[:1800]


def canonical_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        query = [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
        ]
        return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", urlencode(query), ""))
    except Exception:
        return ""


def fetch_one(feed: dict[str, str], now: datetime, hours: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = feed["source"]
    diag = {"source": source, "status": "ok", "accepted": 0, "message": ""}
    try:
        response = requests.get(feed["url"], headers=REQUEST_HEADERS, timeout=(5, 15))
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        entries = list(parsed.entries or [])
        if not entries:
            raise RuntimeError("feed returned no entries")

        articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for entry in entries[:60]:
            title = clean_text(entry.get("title", ""))
            link = canonical_url(str(entry.get("link", "")).strip())
            published = entry_datetime(entry)
            if not title or not link or published is None:
                continue
            age = (now - published).total_seconds() / 3600
            if age < -6 or age > hours:
                continue
            if link in seen_urls:
                continue
            seen_urls.add(link)
            articles.append(
                {
                    "title": title,
                    "summary": entry_summary(entry),
                    "source": source,
                    "link": link,
                    "published_at": published.isoformat(),
                    "category_hint": feed.get("category", ""),
                }
            )
        diag["accepted"] = len(articles)
        return articles, diag
    except Exception as exc:
        diag["status"] = "error"
        diag["message"] = str(exc)[:240]
        return [], diag


def title_tokens(article: dict[str, Any]) -> list[str]:
    words = re.findall(r"[a-z0-9]+", clean_text(article.get("title", "")).lower())
    return [word for word in words if len(word) > 2 and word not in STOP_WORDS]


def evidence_tokens(article: dict[str, Any]) -> set[str]:
    words = re.findall(r"[a-z0-9]+", f"{article.get('title', '')} {article.get('summary', '')[:500]}".lower())
    return {word for word in words if len(word) > 3 and word not in STOP_WORDS}


def timestamp(article: dict[str, Any]) -> float:
    try:
        return datetime.fromisoformat(str(article.get("published_at", ""))).timestamp()
    except Exception:
        return 0.0


def same_story(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if canonical_url(first.get("link", "")) == canonical_url(second.get("link", "")):
        return True
    if abs(timestamp(first) - timestamp(second)) > 72 * 3600:
        return False

    first_tokens = title_tokens(first)
    second_tokens = title_tokens(second)
    if not first_tokens or not second_tokens:
        return False

    a, b = set(first_tokens), set(second_tokens)
    shared = a & b
    overlap = len(shared) / max(1, min(len(a), len(b)))
    ratio = SequenceMatcher(None, " ".join(first_tokens), " ".join(second_tokens)).ratio()
    if len(shared) >= 3 and overlap >= 0.60:
        return True
    if ratio >= 0.80 and len(shared) >= 2:
        return True

    ea, eb = evidence_tokens(first), evidence_tokens(second)
    common = ea & eb
    evidence_overlap = len(common) / max(1, min(len(ea), len(eb)))
    return len(shared) >= 2 and len(common) >= 6 and evidence_overlap >= 0.48


def cluster_articles(articles: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for article in sorted(articles, key=timestamp, reverse=True):
        cluster = next((items for items in clusters if any(same_story(article, item) for item in items[:4])), None)
        if cluster is None:
            clusters.append([article])
            continue

        source = article["source"].lower()
        existing = next((item for item in cluster if item["source"].lower() == source), None)
        if existing is None:
            cluster.append(article)
        elif timestamp(article) > timestamp(existing):
            cluster.remove(existing)
            cluster.append(article)
        cluster.sort(key=timestamp, reverse=True)
    return clusters


def classify_cluster(cluster: list[dict[str, Any]]) -> str | None:
    text = " ".join(f"{item['title']} {item['summary']}" for item in cluster).lower()
    if contains_any(text, JUNK_PHRASES):
        return None
    if not contains_any(text, WYOMING_SIGNALS):
        return None
    if contains_any(text, ROUTINE_CRIME) and not contains_any(text, JUSTICE_POLICY):
        return None

    scores: dict[str, int] = {category: 0 for category in CATEGORIES}
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if contains_phrase(text, keyword):
                scores[category] += 4 if " " in keyword else 1

    for item in cluster:
        hint = item.get("category_hint", "")
        if hint in scores:
            scores[hint] += 6

    if contains_any(text, ("city council", "county commission", "annexation", "zoning", "housing", "data center")):
        scores[CATEGORIES[6]] += 5
    if contains_any(text, ("public records", "open meetings", "audit", "ethics", "rulemaking")):
        scores[CATEGORIES[8]] += 5
    if contains_any(text, ("election", "candidate", "campaign", "primary", "ballot", "voter")):
        scores[CATEGORIES[0]] += 5

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]
    if best_score < 3:
        return None
    if not contains_any(text, POLICY_SIGNALS) and best_score < 7:
        return None
    return best_category


def representative_title(cluster: list[dict[str, Any]]) -> str:
    if len(cluster) == 1:
        return cluster[0]["title"]
    frequency = Counter(token for item in cluster for token in set(title_tokens(item)))
    return max(
        cluster,
        key=lambda item: (sum(frequency[token] for token in set(title_tokens(item))), timestamp(item)),
    )["title"]


def representative_summary(cluster: list[dict[str, Any]]) -> str:
    summaries = [clean_text(item.get("summary", "")) for item in cluster]
    summaries = [summary for summary in summaries if len(summary) >= 40]
    if not summaries:
        return "Open the linked coverage for full details."
    summary = max(summaries, key=len)
    if len(summary) > 700:
        summary = summary[:700].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    return summary


def story_card(cluster: list[dict[str, Any]], category: str) -> dict[str, Any]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in sorted(cluster, key=timestamp, reverse=True):
        source_key = item["source"].lower()
        if source_key in seen:
            continue
        seen.add(source_key)
        sources.append({"name": item["source"], "url": item["link"], "published_at": item["published_at"]})

    return {
        "title": representative_title(cluster),
        "summary": representative_summary(cluster),
        "category": category,
        "published_at": max(item["published_at"] for item in cluster),
        "sources": sources,
        "source_count": len(sources),
    }


def build_digest(hours: int = 120) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    feeds = configured_feeds()
    articles: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(feeds)))) as pool:
        futures = {pool.submit(fetch_one, feed, now, hours): feed for feed in feeds}
        for future in as_completed(futures):
            items, diag = future.result()
            diagnostics[diag["source"]] = diag
            articles.extend(items)

    unique_articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for article in sorted(articles, key=timestamp, reverse=True):
        url = canonical_url(article["link"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_articles.append(article)

    clusters = cluster_articles(unique_articles)
    categories = {category: [] for category in CATEGORIES}
    for cluster in clusters:
        category = classify_cluster(cluster)
        if category is None:
            continue
        categories[category].append(story_card(cluster, category))

    for stories in categories.values():
        stories.sort(key=lambda story: story["published_at"], reverse=True)

    outlet_names = {source["name"] for stories in categories.values() for story in stories for source in story["sources"]}
    story_count = sum(len(stories) for stories in categories.values())
    multi_source_count = sum(1 for stories in categories.values() for story in stories if story["source_count"] > 1)

    return {
        "categories": categories,
        "metadata": {
            "story_count": story_count,
            "outlet_count": len(outlet_names),
            "multi_source_count": multi_source_count,
            "article_count": len(unique_articles),
            "cluster_count": len(clusters),
            "failed_sources": sum(1 for diag in diagnostics.values() if diag["status"] == "error"),
            "processing_mode": "source-faithful deterministic v3",
        },
        "diagnostics": diagnostics,
    }
