"""Host-side loopback OAuth flow writing the calendar token file. Never prints tokens."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import secrets
import sys
import urllib.parse
import webbrowser
import requests
from app.core.config import WorkerSettings
from app.core.exceptions import AuthenticationError
from app.providers.google_calendar.auth import GoogleCalendarTokenManager
from app.providers.google_calendar.connect import (
    authorization_url,
    exchange_code,
    token_record,
)

DEFAULT_PORT = 8765


def save_token(settings, session, redirect_uri, code) -> None:
    payload = exchange_code(
        session,
        settings.calendar_client_id,
        settings.calendar_client_secret,
        redirect_uri,
        code,
        settings.request_timeout_seconds,
    )
    manager = GoogleCalendarTokenManager(settings, session)
    Path(manager.settings.token_file_path).parent.mkdir(parents=True, exist_ok=True)
    manager._save(token_record(payload))


def callback_handler(expected_state, complete):
    """One-shot handler class; `complete(code)` exchanges the code and saves the token."""

    class CalendarCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            state = (query.get("state") or [""])[0]
            code = (query.get("code") or [""])[0]
            if (
                query.get("error")
                or not code
                or not secrets.compare_digest(state, expected_state)
            ):
                self._reply(400, "Authorization rejected. You can close this tab.")
                return
            try:
                complete(code)
            except AuthenticationError:
                self._reply(400, "Authorization failed. See the terminal.")
                return
            self._reply(200, "Google Calendar connected. You can close this tab.")

        def _reply(self, status, message):
            body = message.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    return CalendarCallbackHandler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    settings = WorkerSettings.from_env()
    if (
        not settings.calendar_client_id
        or settings.calendar_client_id == "your_application_client_ID"
        or not settings.calendar_client_secret
    ):
        print(
            "CALENDAR_CLIENT_ID and CALENDAR_CLIENT_SECRET are required "
            "(GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET remain fallbacks)",
            file=sys.stderr,
        )
        return 2
    redirect_uri = f"http://localhost:{args.port}/"
    state = secrets.token_urlsafe(32)
    session = requests.Session()
    connected = []

    def complete(code):
        save_token(settings, session, redirect_uri, code)
        connected.append(True)

    url = authorization_url(settings.calendar_client_id, redirect_uri, state)
    print(f"Add {redirect_uri} as a redirect URI, then authorize here:\n{url}")
    webbrowser.open(url)
    server = HTTPServer(("127.0.0.1", args.port), callback_handler(state, complete))
    try:
        server.handle_request()
    finally:
        server.server_close()
        session.close()
    if not connected:
        print("Not connected; no token file was written.", file=sys.stderr)
        return 1
    print(f"Connected. Token written to {settings.calendar_token_file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
