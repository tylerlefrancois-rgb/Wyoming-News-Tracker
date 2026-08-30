import calendar
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
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
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(" ", strip=True)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _entry_datetime(entry: Any) -> datetime | None:
    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("created_parsed")
    )
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def _entry_summary(entry: Any) -> str:
    candidates: list[str] = []

    for content_item in entry.get("content", []) or []:
        value = content_item.get("value", "")
        if value:
            candidates.append(clean_html(value))

    for key in ("summary", "description", "subtitle"):
        value = entry.get(key, "")
        if value:
            candidates.append(clean_html(value))

    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return "No article description was supplied by the RSS feed."
    return max(candidates, key=len)[:1600]


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _clean_url(value: str) -> str:
    if not _valid_http_url(value):
        return value
    parsed = urlparse(value)
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/") or "/",
            parsed.params,
            urlencode(query),
            "",
        )
    )


def _dedupe_key(source: str, title: str, link: str) -> str:
    cleaned_link = _clean_url(link).lower()
    if cleaned_link:
        return f"url:{cleaned_link}"
    normalized_title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return f"title:{source.lower()}:{normalized_title}"


def _fetch_one_feed(
    feed_info: dict[str, str],
    now: datetime,
    max_age_hours: int,
    per_source_limit: int,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    source = feed_info["source"]
    url = feed_info["url"]
    source_diag = {
        "status": "ok",
        "accepted": 0,
        "skipped_undated": 0,
        "skipped_outside_window": 0,
        "message": "",
    }

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=(5, 14))
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        entries = list(feed.entries or [])

        if not entries:
            message = "Feed returned no entries."
            if getattr(feed, "bozo", False):
                message = str(getattr(feed, "bozo_exception", message))
            source_diag["status"] = "error"
            source_diag["message"] = message[:300]
            return source, [], source_diag

        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entry in entries:
            if len(items) >= per_source_limit:
                break

            title = clean_html(entry.get("title", ""))
            raw_link = (entry.get("link", "") or "").strip()
            link = _clean_url(raw_link)
            published_at = _entry_datetime(entry)

            if not title or not _valid_http_url(link):
                continue
            if published_at is None:
                source_diag["skipped_undated"] += 1
                continue

            age_hours = (now - published_at).total_seconds() / 3600
            if age_hours < -6 or age_hours > max_age_hours:
                source_diag["skipped_outside_window"] += 1
                continue

            key = _dedupe_key(source, title, link)
            if key in seen:
                continue
            seen.add(key)

            items.append(
                {
                    "title": title,
                    "source": source,
                    "summary": _entry_summary(entry),
                    "link": link,
                    "published_at": published_at.isoformat(),
                }
            )

        source_diag["accepted"] = len(items)
        return source, items, source_diag

    except Exception as exc:
        source_diag["status"] = "error"
        source_diag["message"] = str(exc)[:300]
        return source, [], source_diag


def fetch_wyoming_news(
    max_age_hours: int = 120,
    per_source_limit: int = 30,
    max_articles: int = 180,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch current Wyoming reporting in parallel with explicit feed diagnostics."""
    now = datetime.now(timezone.utc)
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

    all_articles: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(6, len(WYOMING_FEEDS))) as executor:
        future_map = {
            executor.submit(
                _fetch_one_feed,
                feed_info,
                now,
                max_age_hours,
                per_source_limit,
            ): feed_info["source"]
            for feed_info in WYOMING_FEEDS
        }

        for future in as_completed(future_map):
            source, articles, source_diag = future.result()
            diagnostics["source_counts"][source] = source_diag["accepted"]
            diagnostics["skipped_undated"][source] = source_diag["skipped_undated"]
            diagnostics["skipped_outside_window"][source] = source_diag["skipped_outside_window"]

            if source_diag["status"] == "ok":
                diagnostics["successful_sources"].append(source)
            else:
                diagnostics["failed_sources"][source] = source_diag["message"] or "Feed failed."

            all_articles.extend(articles)

    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for article in sorted(all_articles, key=lambda item: item["published_at"], reverse=True):
        normalized_url = _clean_url(article.get("link", "")).lower()
        if normalized_url and normalized_url in seen_urls:
            continue
        if normalized_url:
            seen_urls.add(normalized_url)
        deduped.append(article)

    deduped = deduped[:max_articles]
    for index, article in enumerate(deduped, start=1):
        article["article_id"] = f"A{index:04d}"

    diagnostics["article_count"] = len(deduped)
    diagnostics["sources_with_recent_items"] = sum(
        1 for count in diagnostics["source_counts"].values() if count > 0
    )
    diagnostics["successful_sources"].sort()

    return deduped, diagnostics
