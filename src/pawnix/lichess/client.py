"""Small standard-library client for the Lichess Board API."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from pawnix.lichess.credentials import load_token


class LichessClient:
    """Use public profile endpoints and authenticated Board API routes."""

    API_ROOT = "https://lichess.org/api"
    USER_AGENT = "Pawnix/0.1.0 (terminal chess client)"

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or os.environ.get("LICHESS_TOKEN", "") or load_token()).strip()

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    @classmethod
    def from_environment(cls) -> "LichessClient":
        """Load an explicit environment token or the user's saved OAuth token."""
        return cls()

    def get_account(self) -> dict:
        """Verify the token and return the authenticated Lichess account."""
        return self._json_request("GET", "/account")

    def get_public_profile(self, username: str) -> dict:
        """Fetch one public profile; this endpoint does not require OAuth."""
        username = username.strip()
        if not username:
            raise ValueError("username cannot be empty")
        payload = self._json_request("GET", f"/user/{quote(username, safe='')}", authenticated=False)
        if not isinstance(payload, dict):
            raise ValueError("Lichess returned an unexpected profile response")
        return payload

    def open_event_stream(self):
        """Open the authenticated account event stream; caller must close it."""
        return self._open("GET", "/stream/event", accept="application/x-ndjson")

    def open_game_stream(self, game_id: str):
        """Open one Board API game's NDJSON stream."""
        return self._open(
            "GET", f"/board/game/stream/{quote(game_id, safe='')}", accept="application/x-ndjson"
        )

    def open_seek(self, minutes: int, increment: int, rated: bool = False):
        """Create a real-time seek and keep its response open until matched/canceled."""
        if not 0 <= minutes <= 180 or not 0 <= increment <= 180:
            raise ValueError("Lichess seek time must be between 0 and 180 minutes/seconds")
        if minutes * 60 + increment * 40 < 8 * 60:
            raise ValueError(
                "Lichess random seeks require Rapid or Classical time controls; choose one such as 10+0."
            )
        body = urlencode({
            "time": minutes,
            "increment": increment,
            "rated": "true" if rated else "false",
            "variant": "standard",
        }).encode("ascii")
        return self._open("POST", "/board/seek", body=body, content_type="application/x-www-form-urlencoded",
                          accept="application/x-ndjson")

    def challenge_ai(self, level: int, minutes: int, increment: int, color: str = "random") -> dict:
        """Start a casual game against Lichess's built-in AI."""
        if not 1 <= level <= 8:
            raise ValueError("Lichess AI level must be between 1 and 8")
        if color not in {"white", "black", "random"}:
            raise ValueError("Lichess AI color must be white, black, or random")
        body = urlencode({
            "level": level, "clock.limit": minutes * 60,
            "clock.increment": increment, "color": color,
        }).encode("ascii")
        return self._json_request(
            "POST", "/challenge/ai", body=body,
            content_type="application/x-www-form-urlencoded",
        )

    def open_challenge(self, username: str, minutes: int, increment: int):
        """Challenge a Lichess user and hold the request open until accepted/canceled."""
        username = username.strip()
        if not username:
            raise ValueError("Enter a Lichess username to challenge.")
        body = urlencode({
            "clock.limit": minutes * 60, "clock.increment": increment,
            "color": "random", "rated": "false", "keepAliveStream": "true",
        }).encode("ascii")
        return self._open(
            "POST", f"/challenge/{quote(username, safe='')}", body=body,
            content_type="application/x-www-form-urlencoded", accept="application/x-ndjson",
        )

    def play_move(self, game_id: str, uci: str) -> dict:
        """Submit one legal UCI move to a Board API game."""
        return self._json_request(
            "POST", f"/board/game/{quote(game_id, safe='')}/move/{quote(uci, safe='')}",
        )

    def resign(self, game_id: str) -> dict:
        return self._json_request("POST", f"/board/game/{quote(game_id, safe='')}/resign")

    def accept_challenge(self, challenge_id: str) -> dict:
        return self._json_request("POST", f"/challenge/{quote(challenge_id, safe='')}/accept")

    def decline_challenge(self, challenge_id: str) -> dict:
        return self._json_request("POST", f"/challenge/{quote(challenge_id, safe='')}/decline")

    def set_draw_offer(self, game_id: str, accept: bool = True) -> dict:
        action = "yes" if accept else "no"
        return self._json_request("POST", f"/board/game/{quote(game_id, safe='')}/draw/{action}")

    def _json_request(
        self, method: str, path: str, authenticated: bool = True,
        body: bytes | None = None, content_type: str | None = None,
    ) -> dict:
        with self._open(method, path, body=body, content_type=content_type,
                        authenticated=authenticated, accept="application/json") as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Lichess returned an unexpected JSON response")
        return payload

    def _open(
        self, method: str, path: str, body: bytes | None = None, *,
        accept: str = "application/json", content_type: str | None = None,
        authenticated: bool = True,
    ):
        headers = {"Accept": accept, "User-Agent": self.USER_AGENT}
        if authenticated:
            if not self.token:
                raise RuntimeError("Sign in to Lichess from the Pawnix welcome screen to play online.")
            headers["Authorization"] = f"Bearer {self.token}"
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(f"{self.API_ROOT}{path}", data=body, headers=headers, method=method)
        try:
            timeout = 65 if accept == "application/json" else None
            return urlopen(request, timeout=timeout)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if exc.code == 401:
                message = "Lichess rejected the saved credential. Sign out and authorize Pawnix again."
            elif exc.code == 403:
                message = "Lichess denied this action. Reauthorize Pawnix with board:play and challenge:write permissions."
            elif exc.code == 429:
                message = "Lichess rate limit reached; wait before retrying."
            elif exc.code == 400 and path == "/board/seek":
                message = "Lichess rejected this seek. Random Board API games require Rapid or Classical time controls; choose one such as 10+0."
            else:
                message = f"Lichess API returned HTTP {exc.code}."
            if detail:
                message += f" {detail}"
            raise RuntimeError(message) from exc
        except URLError as exc:
            raise RuntimeError(f"Could not connect to Lichess: {exc.reason}") from exc
