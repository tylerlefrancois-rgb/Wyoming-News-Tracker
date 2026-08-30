import os
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request

from news_engine import CATEGORIES, build_digest

app = Flask(__name__)

WINDOWS = {
    48: "48 hours",
    72: "3 days",
    120: "5 days",
    168: "7 days",
}
DEFAULT_WINDOW = 120
CACHE_SECONDS = max(300, int(os.getenv("NEWS_CACHE_SECONDS", "1800")))

_cache: dict[int, dict] = {}
_cache_lock = threading.Lock()

try:
    MOUNTAIN_TIME = ZoneInfo("America/Denver")
except Exception:
    MOUNTAIN_TIME = timezone.utc


def display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(MOUNTAIN_TIME).strftime("%b %d, %Y · %I:%M %p MT")
    except Exception:
        return "Date unavailable"


def selected_window() -> int:
    try:
        value = int(request.args.get("window", DEFAULT_WINDOW))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW
    return value if value in WINDOWS else DEFAULT_WINDOW


def get_digest(window_hours: int, force: bool = False) -> dict:
    now = time.time()
    with _cache_lock:
        cached = _cache.get(window_hours)
        if cached and not force and now - cached["cached_at"] < CACHE_SECONDS:
            return cached

    digest = build_digest(window_hours)
    digest["cached_at"] = now
    digest["updated_at"] = datetime.now(timezone.utc).isoformat()

    with _cache_lock:
        _cache[window_hours] = digest
    return digest


@app.get("/health")
def health():
    return {"status": "ok", "app": "wyoming-policy-news-tracker"}, 200


@app.get("/")
def index():
    window_hours = selected_window()
    force = request.args.get("refresh", "").lower() in {"1", "true", "yes"}

    error = ""
    try:
        digest = get_digest(window_hours, force=force)
    except Exception as exc:
        app.logger.exception("News refresh failed")
        digest = {
            "categories": {category: [] for category in CATEGORIES},
            "metadata": {
                "story_count": 0,
                "outlet_count": 0,
                "multi_source_count": 0,
                "failed_sources": 0,
            },
            "diagnostics": {},
            "updated_at": "",
        }
        error = f"The news update failed: {type(exc).__name__}. The app itself is running normally."

    categories = digest.get("categories", {})
    active_categories = [category for category in CATEGORIES if categories.get(category)]

    return render_template(
        "index.html",
        categories=categories,
        active_categories=active_categories,
        metadata=digest.get("metadata", {}),
        diagnostics=digest.get("diagnostics", {}),
        window_hours=window_hours,
        window_label=WINDOWS[window_hours],
        windows=WINDOWS,
        updated_label=display_date(digest.get("updated_at", "")),
        display_date=display_date,
        error=error,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
