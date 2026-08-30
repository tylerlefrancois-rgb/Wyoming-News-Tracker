import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request, send_from_directory

app = Flask(__name__)

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

WINDOWS = {
    48: "48 hours",
    72: "3 days",
    120: "5 days",
    168: "7 days",
}
DEFAULT_WINDOW = 120
CACHE_SECONDS = max(300, int(os.getenv("NEWS_CACHE_SECONDS", "1800")))
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

_cache = {}
_refreshing = set()
_refresh_errors = {}
_cache_lock = threading.Lock()

try:
    MOUNTAIN_TIME = ZoneInfo("America/Denver")
except Exception:
    MOUNTAIN_TIME = timezone.utc


def display_date(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(MOUNTAIN_TIME).strftime("%b %d, %Y · %I:%M %p MT")
    except Exception:
        return "Date unavailable"


def parse_window(raw_value):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW
    return value if value in WINDOWS else DEFAULT_WINDOW


def selected_window():
    return parse_window(request.args.get("window", DEFAULT_WINDOW))


def _refresh_digest(window_hours):
    try:
        # Import the feed engine only after the web server is already available.
        # A broken/slow feed dependency can never prevent /health or / from starting.
        from news_engine import build_digest

        digest = build_digest(window_hours)
        digest["cached_at"] = time.time()
        digest["updated_at"] = datetime.now(timezone.utc).isoformat()

        with _cache_lock:
            _cache[window_hours] = digest
            _refresh_errors.pop(window_hours, None)
    except Exception as exc:
        app.logger.exception("Background news refresh failed")
        with _cache_lock:
            _refresh_errors[window_hours] = type(exc).__name__
    finally:
        with _cache_lock:
            _refreshing.discard(window_hours)


def ensure_refresh(window_hours, force=False):
    """Return cached news immediately and refresh stale/missing data in the background."""
    now = time.time()
    start_thread = False

    with _cache_lock:
        cached = _cache.get(window_hours)
        cache_age = now - cached.get("cached_at", 0) if cached else None
        cache_is_fresh = cached is not None and cache_age is not None and cache_age < CACHE_SECONDS

        should_refresh = force or not cache_is_fresh
        if should_refresh and window_hours not in _refreshing:
            _refreshing.add(window_hours)
            _refresh_errors.pop(window_hours, None)
            start_thread = True

        refreshing = window_hours in _refreshing
        error_name = _refresh_errors.get(window_hours, "")

    if start_thread:
        thread = threading.Thread(
            target=_refresh_digest,
            args=(window_hours,),
            name="news-refresh-{}".format(window_hours),
            daemon=True,
        )
        thread.start()

    return cached, refreshing, error_name


@app.get("/health")
def health():
    return {"status": "ok", "app": "wyoming-policy-news-tracker"}, 200


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(ASSET_DIR, filename)


@app.get("/api/news")
def api_news():
    window_hours = selected_window()
    force = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    cached, refreshing, error_name = ensure_refresh(window_hours, force=force)

    if cached is not None:
        return jsonify(
            {
                "status": "ready",
                "refreshing": refreshing,
                "window_hours": window_hours,
                "window_label": WINDOWS[window_hours],
                "updated_label": display_date(cached.get("updated_at", "")),
                "digest": cached,
            }
        )

    if error_name and not refreshing:
        return (
            jsonify(
                {
                    "status": "error",
                    "refreshing": False,
                    "window_hours": window_hours,
                    "window_label": WINDOWS[window_hours],
                    "message": "News refresh failed: {}".format(error_name),
                }
            ),
            503,
        )

    return (
        jsonify(
            {
                "status": "loading",
                "refreshing": True,
                "window_hours": window_hours,
                "window_label": WINDOWS[window_hours],
            }
        ),
        202,
    )


@app.get("/")
def index():
    window_hours = selected_window()
    force = request.args.get("refresh", "").lower() in {"1", "true", "yes"}

    ensure_refresh(window_hours, force=force)

    return render_template(
        "index.html",
        categories=CATEGORIES,
        window_hours=window_hours,
        window_label=WINDOWS[window_hours],
        windows=WINDOWS,
        force_refresh=force,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
