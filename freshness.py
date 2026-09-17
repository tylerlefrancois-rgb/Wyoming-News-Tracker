import os
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse


_DATE_FIELDS = ("pubdate", "published", "created", "date")
_URL_DATE_PATTERNS = (
    re.compile(r"(?:^|/)(20\d{2})[/-](0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])(?:/|$)"),
    re.compile(r"(?:^|/)(20\d{2})[/-](0?[1-9]|1[0-2])(?:/|$)"),
)


def _direct_child_text(server, node, field):
    wanted = field.lower()
    for child in list(node):
        if server.local_name(child.tag) != wanted:
            continue
        text = server.clean_text(child.text)
        if text:
            return text
    return ""


def _published_date(server, node):
    # Prefer true publication fields. Do not use Atom/RSS "updated" as a
    # publication date: aggregators can refresh that field for old stories and
    # make months-old coverage look current.
    for field in _DATE_FIELDS:
        raw = _direct_child_text(server, node, field)
        if not raw:
            continue
        parsed = server.parse_date(raw)
        if parsed is not None:
            return parsed
    return None


def _embedded_url_date(link):
    try:
        path = urlparse(link).path
    except Exception:
        return None

    match = _URL_DATE_PATTERNS[0].search(path)
    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None

    match = _URL_DATE_PATTERNS[1].search(path)
    if match:
        try:
            # Month-only URLs are useful only as a stale-content guard. Use the
            # final day of the month so we do not reject a current-month story.
            year = int(match.group(1))
            month = int(match.group(2))
            if month == 12:
                next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
            from datetime import timedelta
            return next_month - timedelta(days=1)
        except ValueError:
            return None

    return None


def _is_fresh(server, published, link="", now=None):
    if published is None:
        return False

    now = now or datetime.now(timezone.utc)
    age_hours = (now - published).total_seconds() / 3600
    if age_hours < -6 or age_hours > server.MAX_AGE_HOURS:
        return False

    # Some generated feeds stamp an old article with a recent ingestion/update
    # time. When the publisher URL itself contains a clear older date, trust the
    # publisher URL and reject the item.
    url_date = _embedded_url_date(link)
    if url_date is not None:
        url_age_hours = (now - url_date).total_seconds() / 3600
        if url_age_hours > server.MAX_AGE_HOURS + 24:
            return False

    return True


def _strict_parse_feed(server, xml_bytes):
    root = server.ET.fromstring(xml_bytes)
    entries = [
        node
        for node in root.iter()
        if server.local_name(node.tag) in {"item", "entry"}
    ]
    now = datetime.now(timezone.utc)

    items = []
    seen_links = set()

    for node in entries[:150]:
        title = server.child_text(node, {"title"})
        link = server.entry_link(node)
        if not title or not link or link in seen_links:
            continue

        published = _published_date(server, node)
        if not _is_fresh(server, published, link, now):
            continue

        summary = server.child_text(
            node,
            {"description", "summary", "encoded", "content", "subtitle"},
        )
        if not summary:
            summary = "Open the original article for full details."
        if len(summary) > 650:
            summary = summary[:650].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."

        seen_links.add(link)
        items.append(
            {
                "title": title,
                "link": link,
                "summary": summary,
                "source": server.source_name(node, link),
                "published_at": published.isoformat(),
                "image": server.entry_image(node),
                "_sort": published.timestamp(),
            }
        )

    items.sort(key=lambda item: item.get("_sort", 0), reverse=True)
    return items


def _prune_digest(server, payload):
    if payload is None:
        return None

    now = datetime.now(timezone.utc)
    sections = []
    total_items = 0
    sources = set()

    for original_section in payload.get("sections", []):
        section = dict(original_section)
        fresh_items = []

        for item in original_section.get("items", []):
            published = server.parse_date(item.get("published_at", ""))
            if not _is_fresh(server, published, item.get("link", ""), now):
                continue
            fresh_items.append(item)
            sources.add(item.get("source", "Source"))

        fresh_items.sort(
            key=lambda item: (
                server.parse_date(item.get("published_at", "")) or datetime.min.replace(tzinfo=timezone.utc)
            ).timestamp(),
            reverse=True,
        )
        section["items"] = fresh_items
        total_items += len(fresh_items)
        sections.append(section)

    cleaned = dict(payload)
    cleaned["sections"] = sections
    cleaned["window_days"] = server.MAX_AGE_DAYS

    metrics = dict(payload.get("metrics", {}))
    metrics["items"] = total_items
    metrics["sources"] = len(sources)
    metrics["feeds"] = len(sections) or metrics.get("feeds", 0)
    metrics["failed_feeds"] = sum(
        1 for section in sections if section.get("status") != "ok"
    )
    cleaned["metrics"] = metrics
    return cleaned


def install(server):
    if getattr(server, "_freshness_patch_installed", False):
        return

    # Keep the existing default unless Railway explicitly overrides it.
    try:
        max_age_days = int(os.environ.get("NEWS_MAX_AGE_DAYS", server.MAX_AGE_DAYS))
    except ValueError:
        max_age_days = server.MAX_AGE_DAYS
    server.MAX_AGE_DAYS = max(1, min(30, max_age_days))
    server.MAX_AGE_HOURS = server.MAX_AGE_DAYS * 24

    server.parse_feed = lambda xml_bytes: _strict_parse_feed(server, xml_bytes)

    def google_news_rss_url(query):
        query = str(query or "").strip()
        if not re.search(r"\bwhen:\d+[dhmy]\b", query, re.I):
            query = f"{query} when:{server.MAX_AGE_DAYS}d".strip()
        return (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )

    server.google_news_rss_url = google_news_rss_url

    original_ensure_refresh = server.ensure_refresh

    def ensure_refresh(force=False):
        cached, refreshing, error = original_ensure_refresh(force=force)
        return _prune_digest(server, cached), refreshing, error

    server.ensure_refresh = ensure_refresh
    server._freshness_patch_installed = True
