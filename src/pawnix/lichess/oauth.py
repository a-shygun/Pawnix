"""Lichess Authorization Code with PKCE for the installed terminal client."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser

from pawnix.lichess.credentials import save_token

CLIENT_ID = "https://github.com/a-shygun/Pawnix"
LICHESS_AUTHORIZE = "https://lichess.org/oauth"
LICHESS_TOKEN = "https://lichess.org/api/token"
SCOPE = "board:play challenge:write"
CALLBACK_TIMEOUT = 180


def authorize() -> str:
    """Authorize Pawnix in the user's browser, save token in OS keychain, return it."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    result: dict[str, str] = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            result.update({key: values[0] for key, values in params.items() if values})
            body = (
                "Pawnix received the Lichess response. You can close this tab and return to the terminal."
                if "code" in result
                else "Lichess authorization did not complete. Return to Pawnix and try again."
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    try:
        server = http.server.HTTPServer(("127.0.0.1", 0), CallbackHandler)
    except OSError as exc:
        raise RuntimeError(f"Could not start the local Lichess sign-in callback: {exc}") from exc
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPE,
        "state": state,
    })
    authorization_url = f"{LICHESS_AUTHORIZE}?{query}"
    try:
        if not webbrowser.open(authorization_url, new=1, autoraise=True):
            raise RuntimeError(
                "Could not open a browser automatically. Open https://lichess.org/oauth in a browser and retry sign-in."
            )
        deadline = time.monotonic() + CALLBACK_TIMEOUT
        while time.monotonic() < deadline and not result:
            server.handle_request()
        if not result:
            raise RuntimeError("Lichess sign-in timed out. Try again.")
        if result.get("state") != state:
            raise RuntimeError("Lichess sign-in response did not match this request. Try again.")
        if result.get("error"):
            detail = result.get("error_description", result["error"])
            raise RuntimeError(f"Lichess sign-in was not completed: {detail}")
        code = result.get("code")
        if not code:
            raise RuntimeError("Lichess did not return an authorization code. Try again.")

        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
        }).encode("ascii")
        request = urllib.request.Request(
            LICHESS_TOKEN,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Pawnix/0.1.0 (terminal chess client)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Could not exchange the Lichess authorization code: {exc}") from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise RuntimeError("Lichess did not return an access token.")
        save_token(token)
        return token
    finally:
        server.server_close()
