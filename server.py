import html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8080"))
CACHE_SECONDS = max(300, int(os.environ.get("NEWS_CACHE_SECONDS", "1800")))
DEFAULT_HOURS = 120
ALLOWED_HOURS = {48, 72, 120, 168}

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

_cache = {}
_refreshing = set()
_errors = {}
_lock = threading.Lock()


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data:
            self.parts.append(data)


def clean_text(value):
    raw = html.unescape(str(value or ""))
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def local_name(tag):
    return str(tag).split("}")[-1].lower()


def child_text(node, names):
    wanted = {name.lower() for name in names}
    for child in node.iter():
        if local_name(child.tag) in wanted:
            text = clean_text(child.text)
            if text:
                return text
    return ""


def entry_link(node):
    for child in node.iter():
        if local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href", "")).strip()
        if href.startswith(("http://", "https://")):
            return href
        text = clean_text(child.text)
        if text.startswith(("http://", "https://")):
            return text
    guid = child_text(node, {"guid", "id"})
    if guid.startswith(("http://", "https://")):
        return guid
    return ""


def entry_image(node):
    for child in node.iter():
        name = local_name(child.tag)
        if name not in {"enclosure", "content", "thumbnail", "image"}:
            continue
        candidate = (
            str(child.attrib.get("url", "")).strip()
            or str(child.attrib.get("href", "")).strip()
            or clean_text(child.text)
        )
        media_type = str(child.attrib.get("type", "")).lower()
        if not candidate.startswith(("http://", "https://")):
            continue
        if (
            media_type.startswith("image/")
            or name in {"thumbnail", "image"}
            or re.search(r"\.(?:jpg|jpeg|png|webp|gif)(?:\?|$)", candidate, re.I)
        ):
            return candidate
    return ""


def parse_date(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def source_name(node, link):
    value = child_text(node, {"source", "creator", "author"})
    if value:
        return value
    try:
        host = urlparse(link).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or "Source"
    except Exception:
        return "Source"


def parse_feed(xml_bytes, feed, hours):
    root = ET.fromstring(xml_bytes)
    now = datetime.now(timezone.utc)
    entries = [
        node for node in root.iter()
        if local_name(node.tag) in {"item", "entry"}
    ]

    items = []
    seen_links = set()

    for node in entries[:80]:
        title = child_text(node, {"title"})
        link = entry_link(node)
        if not title or not link or link in seen_links:
            continue

        published_raw = child_text(
            node,
            {"pubdate", "published", "updated", "date", "created"},
        )
        published = parse_date(published_raw)
        if published is not None:
            age_hours = (now - published).total_seconds() / 3600
            if age_hours < -6 or age_hours > hours:
                continue

        summary = child_text(
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
                "source": source_name(node, link),
                "published_at": published.isoformat() if published else "",
                "image": entry_image(node),
            }
        )

    return items


def fetch_feed(feed, hours):
    req = Request(
        feed["url"],
        headers={
            "User-Agent": "Mozilla/5.0 WyomingPolicyNewsTracker/4.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    try:
        with urlopen(req, timeout=12) as response:
            data = response.read(4_000_000)
        return {
            "category": feed["category"],
            "status": "ok",
            "items": parse_feed(data, feed, hours),
            "error": "",
        }
    except Exception as exc:
        return {
            "category": feed["category"],
            "status": "error",
            "items": [],
            "error": type(exc).__name__,
        }


def build_digest(hours):
    results = {}
    with ThreadPoolExecutor(max_workers=len(RSS_APP_FEEDS)) as pool:
        future_map = {
            pool.submit(fetch_feed, feed, hours): feed
            for feed in RSS_APP_FEEDS
        }
        for future in as_completed(future_map):
            result = future.result()
            results[result["category"]] = result

    sections = []
    total_items = 0
    failed_feeds = 0
    source_names = set()
    global_seen_links = set()

    for feed in RSS_APP_FEEDS:
        category = feed["category"]
        result = results.get(
            category,
            {"status": "error", "items": [], "error": "Unavailable"},
        )
        if result["status"] != "ok":
            failed_feeds += 1

        items = []
        for item in result.get("items", []):
            link = item.get("link", "")
            if link and link in global_seen_links:
                continue
            if link:
                global_seen_links.add(link)
            source_names.add(item.get("source", "Source"))
            items.append(item)

        total_items += len(items)
        sections.append(
            {
                "category": category,
                "status": result["status"],
                "error": result.get("error", ""),
                "items": items,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "sections": sections,
        "metrics": {
            "items": total_items,
            "feeds": len(RSS_APP_FEEDS),
            "failed_feeds": failed_feeds,
            "sources": len(source_names),
        },
    }


def _refresh(hours):
    try:
        digest = build_digest(hours)
        with _lock:
            _cache[hours] = {
                "data": digest,
                "cached_at": time.time(),
            }
            _errors.pop(hours, None)
    except Exception as exc:
        with _lock:
            _errors[hours] = type(exc).__name__
    finally:
        with _lock:
            _refreshing.discard(hours)


def ensure_refresh(hours, force=False):
    now = time.time()
    start = False

    with _lock:
        cached = _cache.get(hours)
        fresh = (
            cached is not None
            and now - cached.get("cached_at", 0) < CACHE_SECONDS
        )
        if (force or not fresh) and hours not in _refreshing:
            _refreshing.add(hours)
            _errors.pop(hours, None)
            start = True
        refreshing = hours in _refreshing
        error = _errors.get(hours, "")

    if start:
        threading.Thread(
            target=_refresh,
            args=(hours,),
            name=f"rss-refresh-{hours}",
            daemon=True,
        ).start()

    return cached, refreshing, error


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "WyomingPolicyNews/4.0"

    def log_message(self, fmt, *args):
        print(
            "%s - - [%s] %s"
            % (self.address_string(), self.log_date_time_string(), fmt % args),
            flush=True,
        )

    def send_bytes(self, status, body, content_type, cache_control="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_bytes(
            status,
            json_bytes(payload),
            "application/json; charset=utf-8",
            "no-store",
        )

    def send_file(self, relative_path, content_type, cache_control):
        path = (ROOT / relative_path).resolve()
        if ROOT not in path.parents and path != ROOT:
            self.send_error(404)
            return
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_bytes(status=200, body=body, content_type=content_type, cache_control=cache_control)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "app": "wyoming-policy-news-tracker",
                    "engine": "stdlib-rss-app",
                },
            )
            return

        if path == "/api/news":
            query = parse_qs(parsed.query)
            try:
                hours = int(query.get("hours", [str(DEFAULT_HOURS)])[0])
            except ValueError:
                hours = DEFAULT_HOURS
            if hours not in ALLOWED_HOURS:
                hours = DEFAULT_HOURS

            force = query.get("refresh", ["0"])[0].lower() in {
                "1",
                "true",
                "yes",
            }
            cached, refreshing, error = ensure_refresh(hours, force=force)

            if cached:
                payload = dict(cached["data"])
                payload.update(
                    {
                        "status": "ready",
                        "refreshing": refreshing,
                    }
                )
                self.send_json(200, payload)
                return

            if error and not refreshing:
                self.send_json(
                    503,
                    {
                        "status": "error",
                        "refreshing": False,
                        "error": error,
                    },
                )
                return

            self.send_json(
                202,
                {
                    "status": "loading",
                    "refreshing": True,
                },
            )
            return

        if path in {"/", "/index.html"}:
            self.send_file("index.html", "text/html; charset=utf-8", "no-store")
            return
        if path == "/styles.css":
            self.send_file("styles.css", "text/css; charset=utf-8", "public, max-age=300")
            return
        if path == "/app.js":
            self.send_file("app.js", "application/javascript; charset=utf-8", "public, max-age=300")
            return
        if path == "/assets/wyoming_landscape.jpg":
            self.send_file(
                "assets/wyoming_landscape.jpg",
                "image/jpeg",
                "public, max-age=86400",
            )
            return
        if path == "/favicon.ico":
            self.send_bytes(204, b"", "image/x-icon", "public, max-age=86400")
            return

        self.send_error(404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Wyoming Policy News Tracker listening on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()
