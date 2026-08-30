import html
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

POLICY_CATEGORIES = [
    "Legislature, Elections & State Government",
    "Taxes, Budget & Economy",
    "Education & Schools",
    "Energy, Minerals & Utilities",
    "Public Lands, Water, Agriculture & Wildlife",
    "Health Care & Public Health",
    "Local Government, Housing & Development",
    "Courts, Crime & Civil Liberties",
    "Regulation, Transparency & Public Accountability",
]
POLICY_AREAS = NEWS_CATEGORIES = POLICY_CATEGORIES
OTHER_NEWS_CATEGORY = None

STOP = {"the","and","for","from","with","this","that","into","after","amid","over","under","more","new","says","say","state","local","wyoming"}
JUNK = (
    "obituary","obituaries","death notice","funeral service","marriage licenses","marriages and divorces",
    "letter to the editor","letters to the editor","guest opinion","guest column","editorial:","opinion:",
    "sports roundup","game recap","high school sports","weather forecast","weather advisory","red flag warning",
    "garage sale","swap shop","fundraiser","community calendar","arts festival","music festival","live music",
    "sponsored content","advertisement","recent arrests","arrest log","jail bookings","police blotter",
)
ROUTINE_CRIME = ("arrested for","charged with","pleads guilty","pleaded guilty","sentenced to","booking","mugshot")
JUSTICE_POLICY = ("court ruling","supreme court","appeal","injunction","policy","reform","use of force","accountability","public defender","legislation","constitutional")
WYOMING = (
    "wyoming","cheyenne","casper","laramie","sheridan","gillette","rock springs","green river","jackson",
    "cody","riverton","rawlins","evanston","torrington","powell","thermopolis","wheatland","lander","douglas",
    "buffalo","newcastle","worland","kemmerer","pinedale","sundance","afton","star valley","wind river",
    "natrona county","laramie county","sheridan county","campbell county","fremont county","albany county",
    "carbon county","converse county","crook county","goshen county","hot springs county","johnson county",
    "lincoln county","niobrara county","park county","platte county","sublette county","sweetwater county",
    "teton county","uinta county","washakie county","weston county","university of wyoming",
)
POLICY_ACTIONS = (
    "bill","law","legislation","legislature","legislative","lawmakers","committee","governor","election","primary",
    "candidate","campaign","ballot","voter","voting","budget","appropriation","funding","tax","revenue","grant",
    "bond","rule","regulation","regulatory","rulemaking","ordinance","resolution","permit","license","licensing",
    "zoning","public records","open meeting","audit","ethics","lawsuit","court","judge","injunction","appeal",
    "department","agency","commission","board","county commission","city council","town council","school board",
    "board of trustees","public hearing","public meeting","public comment","approved","denied","adopted","proposed",
    "proposal","waiver","rate case","rate increase","medicaid","public health","school funding","curriculum",
    "public lands","water rights","management plan","lease","royalty","utility","economic development","housing",
    "infrastructure","annexation","development agreement",
)
RULES = {
    POLICY_CATEGORIES[0]: ("legislature","legislative","lawmakers","state senate","state house","house district","senate district","governor","secretary of state","state auditor","state treasurer","superintendent","election","primary","candidate","campaign","ballot","voter","voting","recount","redistricting","crossover voting","appointment"),
    POLICY_CATEGORIES[1]: ("budget","appropriation","tax","taxes","property tax","sales tax","revenue","spending","grant","bond","economic development","economy","workforce","business council","subsidy","incentive","compensation","fiscal"),
    POLICY_CATEGORIES[2]: ("education","school","school district","school board","teacher","student","curriculum","charter school","school choice","education savings account","recalibration","university of wyoming","community college","college","accreditation","tuition"),
    POLICY_CATEGORIES[3]: ("energy","oil","natural gas","coal","mining","mineral","minerals","uranium","nuclear","wind","solar","electricity","utility","utilities","power plant","transmission","pipeline","drilling","royalty","public service commission","rate case","terrapower","rare earth","critical minerals"),
    POLICY_CATEGORIES[4]: ("public lands","blm","bureau of land management","forest service","water","water rights","reservoir","river","drought","agriculture","ranch","rancher","livestock","grazing","wildlife","game and fish","grizzly","wolf","endangered species","habitat","conservation","reclamation","fishing","hunting"),
    POLICY_CATEGORIES[5]: ("health care","healthcare","medicaid","medicare","health insurance","hospital","clinic","physician","provider","nursing home","rural health","public health","behavioral health","mental health","vaccine","measles","reimbursement","health department","hospital district"),
    POLICY_CATEGORIES[6]: ("county commission","county commissioners","city council","town council","municipal","annexation","zoning","land use","planning commission","housing","affordable housing","workforce housing","development agreement","subdivision","local government","city budget","county budget","infrastructure","data center"),
    POLICY_CATEGORIES[7]: ("criminal justice","criminal law","sentencing","corrections","prison","jail","parole","probation","public defender","prosecutor","law enforcement","police","sheriff","use of force","body camera","bail","supreme court","district court","court ruling","lawsuit","injunction","appeal","first amendment","free speech","civil liberties","due process"),
    POLICY_CATEGORIES[8]: ("public records","open records","open meetings","transparency","government accountability","ethics","audit","regulation","regulatory","rulemaking","administrative rule","licensing","license","oversight","public information","records request","administrative law"),
}
PRIORITY = {POLICY_CATEGORIES[i]: 9-i for i in range(len(POLICY_CATEGORIES))}
PRIORITY[POLICY_CATEGORIES[6]] = 12
PRIORITY[POLICY_CATEGORIES[8]] = 11


def clean(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text).replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def phrase(text: str, value: str) -> bool:
    pattern = re.escape(value.lower()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text.lower()) is not None


def any_phrase(text: str, values: tuple[str, ...]) -> bool:
    return any(phrase(text, value) for value in values)


def article_text(article: dict[str, Any]) -> str:
    return clean(f"{article.get('title','')} {article.get('summary','')}").lower()


def ts(article: dict[str, Any]) -> float:
    try:
        return datetime.fromisoformat(str(article.get("published_at", ""))).timestamp()
    except Exception:
        return 0.0


def title_tokens(article: dict[str, Any]) -> list[str]:
    words = re.findall(r"[a-z0-9]+", clean(article.get("title", "")).lower())
    return [word for word in words if len(word) > 2 and word not in STOP]


def evidence_tokens(article: dict[str, Any]) -> set[str]:
    words = re.findall(r"[a-z0-9]+", article_text(article)[:600])
    return {word for word in words if len(word) > 3 and word not in STOP}


def same_story(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if abs(ts(first) - ts(second)) > 72 * 3600:
        return False
    a, b = title_tokens(first), title_tokens(second)
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    shared = sa & sb
    overlap = len(shared) / max(1, min(len(sa), len(sb)))
    ratio = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    if len(shared) >= 3 and overlap >= 0.62:
        return True
    if ratio >= 0.80 and len(shared) >= 2:
        return True
    ea, eb = evidence_tokens(first), evidence_tokens(second)
    evidence_shared = ea & eb
    return len(shared) >= 2 and len(evidence_shared) >= 6 and len(evidence_shared) / max(1, min(len(ea), len(eb))) >= 0.48


def cluster_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for article in sorted(articles, key=ts, reverse=True):
        match = next((c for c in clusters if any(same_story(article, x) for x in c["articles"][:4])), None)
        if match is None:
            clusters.append({"cluster_id": f"C{len(clusters)+1:04d}", "articles": [article]})
            continue
        source = str(article.get("source", "")).strip().lower()
        existing = next((x for x in match["articles"] if str(x.get("source", "")).strip().lower() == source), None)
        if existing is None:
            match["articles"].append(article)
        elif ts(article) > ts(existing):
            match["articles"].remove(existing)
            match["articles"].append(article)
        match["articles"].sort(key=ts, reverse=True)
    return clusters


def cluster_text(cluster: dict[str, Any]) -> str:
    return " ".join(article_text(article) for article in cluster.get("articles", []))


def classify(cluster: dict[str, Any]) -> str | None:
    text = cluster_text(cluster)
    if not text or any_phrase(text, JUNK) or not any_phrase(text, WYOMING) or not any_phrase(text, POLICY_ACTIONS):
        return None
    if any_phrase(text, ROUTINE_CRIME) and not any_phrase(text, JUSTICE_POLICY):
        return None
    scores: dict[str, int] = {}
    for category, keywords in RULES.items():
        score = sum(4 if len(keyword.split()) > 1 else 1 for keyword in keywords if phrase(text, keyword))
        scores[category] = score
    if any_phrase(text, ("city council","county commission","annexation","zoning","housing","data center")):
        scores[POLICY_CATEGORIES[6]] += 5
    if any_phrase(text, ("public records","open meetings","audit","ethics","rulemaking")):
        scores[POLICY_CATEGORIES[8]] += 5
    if any_phrase(text, ("election","candidate","campaign","primary","ballot","voter")):
        scores[POLICY_CATEGORIES[0]] += 5
    best = max(scores.values(), default=0)
    if best < 3:
        return None
    tied = [category for category, score in scores.items() if score == best]
    return max(tied, key=lambda category: PRIORITY.get(category, 0))


def card(cluster: dict[str, Any], category: str) -> dict[str, Any]:
    articles = sorted(cluster["articles"], key=ts, reverse=True)
    frequency = Counter(token for article in articles for token in set(title_tokens(article)))
    title = max(articles, key=lambda article: (sum(frequency[t] for t in set(title_tokens(article))), ts(article))).get("title", "Wyoming policy update")
    summaries = [clean(a.get("summary", "")) for a in articles if clean(a.get("summary", "")) and "no article description was supplied" not in clean(a.get("summary", "")).lower()]
    summary = max(summaries, key=len) if summaries else "Open the linked coverage for full details."
    if len(summary) > 750:
        summary = summary[:750].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    sources, seen = [], set()
    for article in articles:
        source, link = clean(article.get("source", "Unknown source")), str(article.get("link", "")).strip()
        if not link or source.lower() in seen:
            continue
        seen.add(source.lower())
        sources.append({"name": source, "url": link, "published_at": str(article.get("published_at", ""))})
    return {
        "cluster_id": cluster["cluster_id"], "category": category, "title": clean(title), "summary": summary,
        "published_at": max((str(a.get("published_at", "")) for a in articles), default=""),
        "sources": sources, "source_count": len(sources),
    }


def process_news(articles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    clusters = cluster_articles(articles)
    categories = {category: [] for category in POLICY_CATEGORIES}
    for cluster in clusters:
        category = classify(cluster)
        if category is None:
            continue
        story = card(cluster, category)
        if story["sources"]:
            categories[category].append(story)
    for stories in categories.values():
        stories.sort(key=lambda story: story["published_at"], reverse=True)
    count = sum(len(stories) for stories in categories.values())
    metadata = {
        "article_count": len(articles), "cluster_count": len(clusters), "policy_story_count": count,
        "duplicate_articles_grouped": max(0, len(articles)-len(clusters)),
        "multi_source_story_count": sum(1 for stories in categories.values() for story in stories if story["source_count"] > 1),
        "processing_mode": "source_faithful_local_rules_v2",
        "category_counts": {category: len(stories) for category, stories in categories.items()},
    }
    return [], categories, metadata
