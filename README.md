# Wyoming Policy News Tracker

Clean Flask/Gunicorn rebuild for Railway.

- No Streamlit dependency or Streamlit application code.
- Server-rendered category sections with news cards.
- Duplicate coverage is grouped into a single story with multiple outlet links.
- Source-provided RSS descriptions are used instead of AI-generated summaries.
- Optional RSS.app feeds can be added through `RSS_APP_FEEDS_JSON`.
- Health endpoint: `/health`.

Railway start command:

`gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -`
