"""Google OAuth for Gmail and Calendar.

Deliberately narrow scopes. Note what is NOT here: `gmail.send`. Jarvis can
read your mail and write drafts, and that is the ceiling — sending is a
one-way, outward-facing action, so it stays a human keystroke in the Gmail UI.

Everything is lazily imported so the rest of Jarvis runs with these libraries
uninstalled.
"""

from __future__ import annotations

import logging
from pathlib import Path

import config

log = logging.getLogger("jarvis.google")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",  # create drafts, not send
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

_services: dict[str, object] = {}


class GoogleUnavailable(Exception):
    """Raised when libraries or credentials are missing, with a fix in the text."""


def _require_libs():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        return Request, Credentials, InstalledAppFlow, build
    except ImportError as e:
        raise GoogleUnavailable(
            "Google libraries are not installed. Run:\n"
            "  .venv\\Scripts\\python -m pip install google-api-python-client "
            "google-auth-httplib2 google-auth-oauthlib"
        ) from e


def _credentials():
    Request, Credentials, InstalledAppFlow, _ = _require_libs()

    token_path = Path(config.GOOGLE_TOKEN_PATH)
    creds_path = Path(config.GOOGLE_CREDENTIALS_PATH)

    creds = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, OSError) as e:
            log.warning("Stored token unreadable (%s); re-authorising.", e)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as e:
            log.warning("Token refresh failed (%s); re-authorising.", e)

    if not creds_path.is_file():
        raise GoogleUnavailable(
            f"No OAuth client file at {creds_path}.\n"
            "Create one: console.cloud.google.com -> new project -> enable the Gmail\n"
            "and Google Calendar APIs -> Credentials -> Create OAuth client ID ->\n"
            "Desktop app -> download the JSON and save it to that path.\n"
            "See the 'Gmail and Calendar' section of README.md."
        )

    # Opens a browser once; you approve in Google's own consent screen and the
    # resulting token is stored locally. Jarvis never sees your password.
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    log.info("Google authorisation stored at %s", token_path)
    return creds


def service(name: str, version: str):
    """Return a cached Google API client, authorising on first use."""
    key = f"{name}:{version}"
    if key not in _services:
        _, _, _, build = _require_libs()
        _services[key] = build(name, version, credentials=_credentials(), cache_discovery=False)
    return _services[key]


def gmail():
    return service("gmail", "v1")


def calendar():
    return service("calendar", "v3")


def is_configured() -> bool:
    """True if the libraries are importable and an OAuth client file exists."""
    try:
        _require_libs()
    except GoogleUnavailable:
        return False
    return Path(config.GOOGLE_CREDENTIALS_PATH).is_file()
