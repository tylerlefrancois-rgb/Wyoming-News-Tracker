# Wyoming Policy News Tracker

Clean RSS.app-based rebuild for Wyoming Liberty Group.

- Uses nine RSS.app feeds supplied by the project owner.
- Preserves RSS.app category structure and source wording.
- Removes only exact duplicate article URLs.
- Uses Python standard library only.
- Serves a responsive news-card interface over the existing Wyoming background image.
- Railway starts the service with `python server.py` and checks `/health`.
