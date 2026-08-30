import calendar
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

RSS_APP_FEEDS = [
    {"category": "Wyoming News", "url": "https://rss.app/feeds/tAr4m4B9sT7nmiZh.xml"},
    {"category": "Wyoming Legislature", "url": "https://rss.app/feeds/tYUWHgGoOXR67j15.xml"},
    {"category": "Criminal Justice", "url": "https://rss.app/feeds/t9tblFE0r1ld0EIV.xml"},
    {"category": "Campaign Finance & Election Integrity", "url": "https://rss.app/feeds/td9nj0JMyPDL2sHW.xml"},
    {"category": "Government Transparency, Regulation & Legal Reform", "url": "https://rss.app/feeds/tgm2n09YWIK0ZgPx.xml"},
    {"category": "Economics & State Budget", "url": "https://rss.app/feeds/tuCKnEkNjxKgXlUo.xml"},
    {"category": "Health Care", "url": "https://rss.app/feeds/tNz3QLKrxje5VsnA.xml"},
    {"category": "Education", "url": "https://rss.app/feeds/tiBDL7jljoFQ7kAa.xml"},
    {"category": "Marijuana / THC", "url": "https://rss.app/feeds/tMNTYA3qajuOJL2b.xml"},
]

CATEGORIES = [feed["category"] for feed in RSS_APP_FEEDS]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def clean_text(value: object) -> str:
    raw = html.unescape(str(value or ""))
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def entry_datetime(entry: Any) -> datetime | None:
    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("created_parsed")
    )
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
        return "Open the original article for full details."
    summary = max(candidates, key=len)
    if len(summary) > 850:
        summary = summary[:850].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    return summary


def source_name(entry: Any, link: str, feed_title: str) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        title = clean_text(source.get("title", ""))
        if title:
            return title
    elif source:
        title = clean_text(source)
        if title:
            return title

    try:
        hostname = urlparse(link).hostname or ""
        hostname = hostname.removeprefix("www.")
        if hostname and hostname not in {"rss.app", "rssapp.app"}:
            return hostname
    except Exception:
        pass

    return clean_text(feed_title) or "Source"


def entry_image(entry: Any) -> str:
    for item in entry.get("media_content", []) or []:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    for item in entry.get("media_thumbnail", []) or []:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    for item in entry.get("enclosures", []) or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("href") or item.get("url") or "")
        media_type = str(item.get("type") or "")
        if url and (media_type.startswith("image/") or not media_type):
            return url
    return ""


def fetch_feed(feed_info: dict[str, str], hours: int) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    category = feed_info["category"]
    diag = {"source": category, "status": "ok", "accepted": 0, "message": ""}
    now = datetime.now(timezone.utc)

    try:
        response = requests.get(feed_info["url"], headers=REQUEST_HEADERS, timeout=(5, 12))
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        entries = list(parsed.entries or [])
        if not entries:
            raise RuntimeError("RSS.app feed returned no entries")

        feed_title = clean_text(getattr(parsed, "feed", {}).get("title", ""))
        items: list[dict[str, Any]] = []
        seen_links: set[str] = set()

        for entry in entries[:80]:
            title = clean_text(entry.get("title", ""))
            link = str(entry.get("link", "") or "").strip()
            if not title or not link.startswith(("http://", "https://")):
                continue
            if link in seen_links:
                continue

            published = entry_datetime(entry)
            if published is not None:
                age_hours = (now - published).total_seconds() / 3600
                if age_hours < -6 or age_hours > hours:
                    continue

            seen_links.add(link)
            items.append(
                {
                    "title": title,
                    "summary": entry_summary(entry),
                    "link": link,
                    "source": source_name(entry, link, feed_title),
                    "published_at": published.isoformat() if published else "",
                    "image_url": entry_image(entry),
                }
            )

        items.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        diag["accepted"] = len(items)
        return category, items, diag

    except Exception as exc:
        diag["status"] = "error"
        diag["message"] = str(exc)[:240]
        return category, [], diag


def build_digest(hours: int = 120) -> dict[str, Any]:
    categories = {category: [] for category in CATEGORIES}
    diagnostics: dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=len(RSS_APP_FEEDS)) as pool:
        futures = [pool.submit(fetch_feed, feed_info, hours) for feed_info in RSS_APP_FEEDS]
        for future in as_completed(futures):
            category, items, diag = future.result()
            categories[category] = items
            diagnostics[category] = diag

    # Keep the RSS.app category structure, but remove exact URL repeats. Specific
    # policy feeds win over the general Wyoming News feed when the same link appears twice.
    seen_links: set[str] = set()
    duplicates_removed = 0
    dedupe_order = [category for category in CATEGORIES if category != "Wyoming News"] + ["Wyoming News"]

    for category in dedupe_order:
        unique_items: list[dict[str, Any]] = []
        for item in categories.get(category, []):
            link = item.get("link", "")
            if link and link in seen_links:
                duplicates_removed += 1
                continue
            if link:
                seen_links.add(link)
            unique_items.append(item)
        categories[category] = unique_items

    item_count = sum(len(items) for items in categories.values())
    successful_feeds = sum(1 for diag in diagnostics.values() if diag.get("status") == "ok")
    failed_feeds = len(RSS_APP_FEEDS) - successful_feeds

    return {
        "categories": categories,
        "metadata": {
            "item_count": item_count,
            "feed_count": successful_feeds,
            "duplicate_count": duplicates_removed,
            "failed_sources": failed_feeds,
            "processing_mode": "rss.app feed structure",
        },
        "diagnostics": diagnostics,
    }
