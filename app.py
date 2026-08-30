import os
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, abort, render_template, request, send_from_directory

from ai_processor import POLICY_CATEGORIES, process_news
from news_scraper import fetch_wyoming_news


app = Flask(__name__)

CACHE_TTL_SECONDS = max(300, int(os.getenv("NEWS_CACHE_TTL_SECONDS", "1800")))
DEFAULT_WINDOW_HOURS = 120
WINDOWS = {
    48: "48 hours",
    72: "3 days",
    120: "5 days",
    168: "7 days",
}

_cache: dict[int, dict] = {}
_cache_lock = threading.Lock()
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
try:
    MOUNTAIN = ZoneInfo("America/Denver")
except Exception:
    MOUNTAIN = timezone.utc


def _display_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(MOUNTAIN).strftime("%b %d, %Y · %I:%M %p MT")
    except Exception:
        return "Date unavailable"


def _window_from_request() -> int:
    raw = request.args.get("window", str(DEFAULT_WINDOW_HOURS)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_WINDOW_HOURS
    return value if value in WINDOWS else DEFAULT_WINDOW_HOURS


def _load_digest(window_hours: int, force_refresh: bool = False) -> dict:
    now = time.time()
    with _cache_lock:
        cached = _cache.get(window_hours)
        if (
            not force_refresh
            and cached
            and now - cached.get("cached_at", 0) < CACHE_TTL_SECONDS
        ):
            return cached

    articles, diagnostics = fetch_wyoming_news(
        max_age_hours=window_hours,
        per_source_limit=30,
        max_articles=180,
    )
    _, categories, metadata = process_news(articles)

    payload = {
        "articles": articles,
        "categories": categories,
        "metadata": metadata,
        "diagnostics": diagnostics,
        "cached_at": now,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    with _cache_lock:
        _cache[window_hours] = payload
    return payload


@app.get("/health")
def health():
    return {"status": "ok"}, 200


@app.get("/assets/<path:filename>")
def assets(filename: str):
    if not os.path.isdir(ASSET_DIR):
        abort(404)
    return send_from_directory(ASSET_DIR, filename)


@app.get("/")
def index():
    window_hours = _window_from_request()
    force_refresh = request.args.get("refresh", "").strip().lower() in {"1", "true", "yes"}

    error_message = ""
    payload = {
        "categories": {category: [] for category in POLICY_CATEGORIES},
        "metadata": {},
        "diagnostics": {},
        "updated_at": "",
    }

    try:
        payload = _load_digest(window_hours, force_refresh=force_refresh)
    except Exception:
        error_message = (
            "The tracker could not complete a fresh news update. "
            "The source feeds or processing service may be temporarily unavailable."
        )

    categories = payload.get("categories", {})
    active_categories = [
        category for category in POLICY_CATEGORIES if categories.get(category)
    ]
    metadata = payload.get("metadata", {})
    diagnostics = payload.get("diagnostics", {})

    return render_template(
        "index.html",
        categories=categories,
        all_categories=POLICY_CATEGORIES,
        active_categories=active_categories,
        metadata=metadata,
        diagnostics=diagnostics,
        window_hours=window_hours,
        window_label=WINDOWS[window_hours],
        windows=WINDOWS,
        error_message=error_message,
        updated_label=_display_datetime(payload.get("updated_at", "")),
        display_datetime=_display_datetime,
    )





if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
