import calendar
import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup


WYOMING_FEEDS = [
    {"source": "WyoFile", "url": "https://wyofile.com/feed/"},
    {"source": "Wyoming Public Media", "url": "https://www.wyomingpublicmedia.org/rss.xml"},
    {"source": "Cowboy State Daily", "url": "https://cowboystatedaily.com/rss.xml"},
    {"source": "The Wyoming Truth", "url": "https://wyomingtruth.org/feed/"},
    {
        "source": "Wyoming Tribune Eagle",
        "url": "https://www.wyomingnews.com/search/?f=rss&t=article&c=news/local&l=50&s=start_time&sd=desc",
    },
    {
        "source": "Casper Star-Tribune",
        "url": "https://trib.com/search/?f=rss&t=article&l=50&s=start_time&sd=desc",
    },
    {
        "source": "Jackson Hole News&Guide",
        "url": "https://www.jhnewsandguide.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc",
    },
    {
        "source": "Gillette News Record",
        "url": "https://www.gillettenewsrecord.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc",
    },
    {"source": "Oil City News", "url": "https://oilcity.news/feed/"},
    {"source": "Cap City News", "url": "https://capcity.news/feed/"},
    {"source": "Powell Tribune", "url": "https://www.powelltribune.com/rss"},
    {"source": "Sheridan Media", "url": "https://sheridanmedia.com/feed/"},
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def clean_html(raw_html: str) -> str:
    """Convert RSS HTML fragments into compact plain text."""
    if not raw_html:
        return ""

    text = BeautifulSoup(raw_html, "html.parser").get_text(" ", strip=True)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _entry_datetime(entry: Any) -> datetime | None:
    """Return the most reliable timezone-aware publication time available."""
    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("created_parsed")
    )

    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)

    return None


def _entry_summary(entry: Any) -> str:
    """Prefer the longest useful RSS summary/content field."""
    candidates: list[str] = []

    for content_item in entry.get("content", []) or []:
        value = content_item.get("value", "")
        if value:
            candidates.append(clean_html(value))

    for key in ("summary", "description", "subtitle"):
        value = entry.get(key, "")
        if value:
            candidates.append(clean_html(value))

    candidates = [item for item in candidates if item]
    if not candidates:
        return "No article description was supplied by the RSS feed."

    return max(candidates, key=len)[:1200]


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _dedupe_key(source: str, title: str, link: str) -> str:
    """Remove true duplicates while preserving separate outlets covering one event."""
    if link:
        normalized_link = link.split("#", 1)[0].rstrip("/").lower()
        return f"url:{normalized_link}"

    normalized_title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return f"title:{source.lower()}:{normalized_title}"


def fetch_wyoming_news(
    max_age_hours: int = 120,
    per_source_limit: int = 20,
    max_articles: int = 120,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Fetch dated Wyoming news from the configured RSS feeds.

    Undated items are intentionally excluded so the app does not label old content
    as current news. The returned diagnostics make feed failures visible instead of
    silently hiding them.
    """
    now = datetime.now(timezone.utc)
    articles: list[dict[str, Any]] = []
    seen_items: set[str] = set()

    diagnostics: dict[str, Any] = {
        "requested_window_hours": max_age_hours,
        "configured_sources": len(WYOMING_FEEDS),
        "successful_sources": [],
        "failed_sources": {},
        "source_counts": {},
        "skipped_undated": {},
        "skipped_outside_window": {},
        "article_count": 0,
        "fetched_at": now.isoformat(),
    }

    for feed_info in WYOMING_FEEDS:
        source = feed_info["source"]
        url = feed_info["url"]

        try:
            feed = feedparser.parse(url, request_headers=REQUEST_HEADERS)
            entries = list(feed.entries or [])

            if not entries:
                message = "Feed returned no entries."
                if getattr(feed, "bozo", False):
                    message = str(getattr(feed, "bozo_exception", message))
                diagnostics["failed_sources"][source] = message
                diagnostics["source_counts"][source] = 0
                continue

            diagnostics["successful_sources"].append(source)
            diagnostics["skipped_undated"][source] = 0
            diagnostics["skipped_outside_window"][source] = 0
            accepted_for_source = 0

            for entry in entries:
                if accepted_for_source >= per_source_limit:
                    break

                title = clean_html(entry.get("title", ""))
                link = (entry.get("link", "") or "").strip()
                published_at = _entry_datetime(entry)

                if not title or not _valid_http_url(link):
                    continue

                if published_at is None:
                    diagnostics["skipped_undated"][source] += 1
                    continue

                age_hours = (now - published_at).total_seconds() / 3600

                # Allow a small clock-skew tolerance, but reject clearly future items.
                if age_hours < -6 or age_hours > max_age_hours:
                    diagnostics["skipped_outside_window"][source] += 1
                    continue

                key = _dedupe_key(source, title, link)
                if key in seen_items:
                    continue

                seen_items.add(key)
                accepted_for_source += 1

                articles.append(
                    {
                        "title": title,
                        "source": source,
                        "summary": _entry_summary(entry),
                        "link": link,
                        "published_at": published_at.isoformat(),
                    }
                )

            diagnostics["source_counts"][source] = accepted_for_source

        except Exception as exc:
            diagnostics["failed_sources"][source] = str(exc)
            diagnostics["source_counts"][source] = 0

    articles.sort(key=lambda item: item["published_at"], reverse=True)
    articles = articles[:max_articles]

    for index, article in enumerate(articles, start=1):
        article["article_id"] = f"A{index:04d}"

    diagnostics["article_count"] = len(articles)
    diagnostics["sources_with_recent_items"] = sum(
        1 for count in diagnostics["source_counts"].values() if count > 0
    )

    return articles, diagnostics
