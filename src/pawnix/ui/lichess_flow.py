"""Lichess account and online-game workflows for the terminal UI."""

from __future__ import annotations

import json
import os
import queue
import threading
import time

import chess

from pawnix.game.session import GameSession
from pawnix.lichess.client import LichessClient
from pawnix.lichess.credentials import delete_token
from pawnix.lichess.oauth import authorize


class LichessFlowMixin:
    """Provide account, authentication, and remote-game flows to PawnixApp."""

    def _load_account_identity(self) -> None:
        client = self.lichess_client
        if client is None or not client.authenticated or self.lichess_username:
            return

        def load_identity() -> None:
            try:
                self.lichess_events.put(("identity", client.get_account()))
                self._start_account_event_stream(client)
            except Exception:
                pass

        self._spawn_lichess_thread(load_identity)

    def _start_account_event_stream(self, client=None) -> None:
        client = client or self.lichess_client
        if client is None or not client.authenticated or getattr(self, "account_stream_running", False):
            return
        if self.game is None:
            self.lichess_stop.clear()
        self.account_stream_running = True

        def listen() -> None:
            delay = 1
            try:
                while not self.lichess_stop.is_set():
                    response = None
                    try:
                        response = client.open_event_stream()
                        self._register_lichess_response(response)
                        self._read_lichess_events(response)
                        delay = 1
                    except Exception as exc:
                        if not self.lichess_stop.is_set():
                            self.lichess_events.put(("stream_disconnected", str(exc)))
                    finally:
                        if response is not None:
                            self._forget_lichess_response(response)
                    if self.lichess_stop.wait(delay):
                        break
                    delay = min(delay * 2, 30)
            finally:
                self.account_stream_running = False

        self._spawn_lichess_thread(listen)

    def _accept_incoming_challenge(self) -> None:
        challenge = self.incoming_challenge
        client = self.lichess_client
        if not challenge or client is None:
            return
        detail = challenge.get("challenge", challenge)
        challenge_id = str(detail.get("id", ""))
        if not challenge_id:
            self.lobby_status = "This incoming challenge has no usable ID."
            return
        variant = detail.get("variant", {})
        if isinstance(variant, dict) and variant.get("key", "standard") != "standard":
            self.lobby_status = "Only standard chess challenges are supported. Press X to decline."
            return
        clock = detail.get("timeControl", {})
        limit = int(clock.get("limit", 300) or 300)
        increment = int(clock.get("increment", 0) or 0)
        minutes = max(1, (limit + 59) // 60)
        self._prepare_remote_game(client, minutes, increment, "challenge", "Accepting incoming challenge…")
        self.incoming_challenge = None
        self._spawn_lichess_thread(self._run_accept_challenge, challenge_id)

    def _run_accept_challenge(self, challenge_id: str) -> None:
        try:
            self.lichess_client.accept_challenge(challenge_id)
            self.lichess_events.put(("incoming_accepted", challenge_id))
        except Exception as exc:
            self.lichess_events.put(("error", f"Could not accept challenge: {exc}"))

    def _decline_incoming_challenge(self) -> None:
        challenge = self.incoming_challenge or {}
        detail = challenge.get("challenge", challenge)
        challenge_id = str(detail.get("id", ""))
        client = self.lichess_client
        self.incoming_challenge = None
        if not client or not challenge_id:
            return

        def decline() -> None:
            try:
                client.decline_challenge(challenge_id)
                self.lichess_events.put(("incoming_declined", None))
            except Exception as exc:
                self.lichess_events.put(("error", f"Could not decline challenge: {exc}"))

        self._spawn_lichess_thread(decline)

    def _send_draw_action(self, accept: bool) -> None:
        client, game_id = self.lichess_client, self.online_game_id
        if client is None or game_id is None:
            return

        def send() -> None:
            try:
                client.set_draw_offer(game_id, accept)
                self.lichess_events.put(("draw_action", accept))
            except Exception as exc:
                self.lichess_events.put(("error", f"Could not send draw offer: {exc}"))

        self._spawn_lichess_thread(send)

    def _toggle_lichess_account(self) -> None:
        if self.account_connected:
            try:
                self._stop_lichess()
                delete_token()
                os.environ.pop("LICHESS_TOKEN", None)
                self.lichess_client = None
                self.lichess_username = ""
                self.account_connected = False
                self.lobby_status = "Signed out. Local guest games do not need a Lichess account."
            except Exception as exc:
                self.lobby_status = f"Could not sign out: {exc}"
            return
        self._begin_lichess_auth()

    def _request_lichess_account_action(self) -> None:
        if self.account_connected:
            self.renderer.signout_confirm_open = True
            self.renderer.signout_choice = 1
        else:
            self._toggle_lichess_account()

    def _handle_signout_confirmation(self, choice: int) -> None:
        self.renderer.signout_confirm_open = False
        if choice == 0:
            self._toggle_lichess_account()

    def _begin_lichess_auth(self, resume_online: bool = False) -> None:
        if self.lichess_auth_pending:
            self.lobby_status = "Waiting for Lichess sign-in to finish in your browser…"
            return
        self.lichess_auth_pending = True
        self.lichess_auth_resume_online = resume_online
        self.lobby_status = "Opening Lichess sign-in in your browser…"

        def sign_in() -> None:
            try:
                token = authorize()
                account = LichessClient(token).get_account()
                self.lichess_events.put(("auth_success", (token, account)))
            except Exception as exc:
                self.lichess_events.put(("auth_error", str(exc)))

        self._spawn_lichess_thread(sign_in)

    def _start_lichess_seek(self) -> None:
        client = LichessClient.from_environment()
        if not client.authenticated:
            self._begin_lichess_auth(resume_online=True)
            return
        _, minutes, increment = self.time_controls[self.time_index]
        self._prepare_remote_game(
            client, minutes, increment, "online",
            "Connecting to Lichess and starting a casual seek…",
        )
        self._spawn_lichess_thread(self._run_lichess_seek, minutes, increment)

    def _start_lichess_ai(self) -> None:
        client = LichessClient.from_environment()
        if not client.authenticated:
            self._begin_lichess_auth(resume_online=True)
            return
        _, minutes, increment = self.time_controls[self.time_index]
        self._prepare_remote_game(client, minutes, increment, "lichess_ai", "Starting a Lichess AI game…")
        color = "white" if self.lichess_ai_color == chess.WHITE else "black"
        self._spawn_lichess_thread(self._run_lichess_ai, self.lichess_ai_level, minutes, increment, color)

    def _start_lichess_challenge(self) -> None:
        username = self.challenge_username.strip()
        if not username:
            self.lobby_status = "Enter a Lichess username in the opponent field first."
            self.focus = 2
            return
        client = LichessClient.from_environment()
        if not client.authenticated:
            self._begin_lichess_auth(resume_online=True)
            return
        _, minutes, increment = self.time_controls[self.time_index]
        self._prepare_remote_game(client, minutes, increment, "challenge", f"Challenging {username}…")
        self._spawn_lichess_thread(self._run_lichess_challenge, username, minutes, increment)

    def _prepare_remote_game(self, client, minutes: int, increment: int, mode: str, status: str) -> None:
        self.lichess_client = client
        self.lichess_stop.clear()
        self.online_waiting = True
        self.online_game_id = None
        self.online_minutes, self.online_increment = minutes, increment
        self.online_color = None
        self.premove = None
        self.mode = mode
        self.remote_winner = None
        self.remote_draw = False
        self.game = None
        self.lobby_status = f"{status} Press Esc to cancel."

    def _open_remote_streams(self, client) -> None:
        account = client.get_account()
        self.lichess_events.put(("account", account))
        self._start_account_event_stream(client)

    def _run_lichess_ai(self, level: int, minutes: int, increment: int, color: str) -> None:
        client = self.lichess_client
        if client is None:
            return
        try:
            self._open_remote_streams(client)
            response = client.challenge_ai(level, minutes, increment, color)
            game_id = str(response.get("id", ""))
            if not game_id:
                raise RuntimeError("Lichess did not return the AI game id.")
            self.lichess_events.put(("ai_started", game_id))
            self._start_lichess_game_stream(game_id)
        except Exception as exc:
            if not self.lichess_stop.is_set():
                self.lichess_events.put(("error", str(exc)))

    def _run_lichess_challenge(self, username: str, minutes: int, increment: int) -> None:
        client = self.lichess_client
        if client is None:
            return
        try:
            self._open_remote_streams(client)
            response = client.open_challenge(username, minutes, increment)
            self._register_lichess_response(response)
            self.lichess_events.put(("challenge_active", username))
            completed = False
            try:
                for line in response:
                    if self.lichess_stop.is_set():
                        break
                    if not line.strip():
                        continue
                    payload = json.loads(line.decode("utf-8", errors="replace"))
                    if payload.get("done") == "declined":
                        completed = True
                        self.lichess_events.put(("challenge_declined", username))
                    elif payload.get("done") == "accepted":
                        completed = True
                        self.lichess_events.put(("challenge_accepted", username))
            finally:
                response.close()
                self._forget_lichess_response(response)
            if not completed and not self.lichess_stop.is_set():
                self.lichess_events.put(("challenge_closed", username))
        except Exception as exc:
            if not self.lichess_stop.is_set():
                self.lichess_events.put(("error", str(exc)))

    def _start_lichess_game_stream(self, game_id: str) -> None:
        if not hasattr(self, "_streaming_game_ids"):
            self._streaming_game_ids = set()
        if game_id in self._streaming_game_ids:
            return
        self._streaming_game_ids.add(game_id)
        self._spawn_lichess_thread(self._read_lichess_game, game_id)

    def _is_remote_game(self) -> bool:
        return self.mode in {"online", "lichess_ai", "challenge"}

    def _start_selected_lichess_mode(self) -> None:
        if self.mode_index == 1:
            self._start_lichess_ai()
        elif self.mode_index == 3:
            self._start_lichess_challenge()
        else:
            self._start_lichess_seek()

    def _spawn_lichess_thread(self, target, *args) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.lichess_threads.append(thread)
        thread.start()

    def _register_lichess_response(self, response) -> None:
        with self.lichess_lock:
            self.lichess_responses.append(response)

    def _forget_lichess_response(self, response) -> None:
        with self.lichess_lock:
            if response in self.lichess_responses:
                self.lichess_responses.remove(response)

    def _run_lichess_seek(self, minutes: int, increment: int) -> None:
        client = self.lichess_client
        if client is None:
            return
        try:
            self._open_remote_streams(client)
            seek_response = client.open_seek(minutes, increment, rated=False)
            self._register_lichess_response(seek_response)
            self.lichess_events.put(("seek_active", None))
            try:
                for line in seek_response:
                    if self.lichess_stop.is_set():
                        break
                    if line.strip():
                        self.lichess_events.put(("seek_message", line.decode("utf-8", errors="replace")))
            finally:
                seek_response.close()
                self._forget_lichess_response(seek_response)
            if not self.lichess_stop.is_set():
                self.lichess_events.put(("seek_closed", None))
        except Exception as exc:
            if not self.lichess_stop.is_set():
                self.lichess_events.put(("error", str(exc)))

    def _read_lichess_events(self, response) -> None:
        try:
            with response:
                for line in response:
                    if self.lichess_stop.is_set():
                        break
                    if not line.strip():
                        continue
                    event = json.loads(line.decode("utf-8"))
                    if event.get("type") == "gameStart":
                        game_info = event.get("game", {})
                        compat = game_info.get("compat", {}) if isinstance(game_info, dict) else {}
                        if not isinstance(compat, dict) or compat.get("board") is not True:
                            # The event stream includes games already running
                            # elsewhere on this account; only board-compatible
                            # games can be opened through the Board API.
                            continue
                    self.lichess_events.put(("event", event))
                    if event.get("type") == "gameStart":
                        game_id = event.get("game", {}).get("id")
                        if game_id:
                            self._start_lichess_game_stream(game_id)
        except Exception as exc:
            if not self.lichess_stop.is_set():
                self.lichess_events.put(("stream_disconnected", str(exc)))
        finally:
            self._forget_lichess_response(response)

    def _read_lichess_game(self, game_id: str) -> None:
        client = self.lichess_client
        if client is None:
            return
        response = None
        try:
            response = client.open_game_stream(game_id)
            self._register_lichess_response(response)
            with response:
                for line in response:
                    if self.lichess_stop.is_set():
                        break
                    if line.strip():
                        self.lichess_events.put(("game_state", json.loads(line.decode("utf-8"))))
        except Exception as exc:
            if not self.lichess_stop.is_set():
                self.lichess_events.put(("error", f"Lichess game stream stopped: {exc}"))
        finally:
            if response is not None:
                self._forget_lichess_response(response)

    def _drain_lichess_events(self) -> None:
        while True:
            try:
                kind, payload = self.lichess_events.get_nowait()
            except queue.Empty:
                return
            if kind == "account":
                account = payload if isinstance(payload, dict) else {}
                self.lichess_username = str(account.get("id", account.get("username", "")))
                self.lobby_status = f"Signed in to Lichess as {self.lichess_username}; seeking a casual game…"
            elif kind == "identity":
                account = payload if isinstance(payload, dict) else {}
                self.lichess_username = str(account.get("id", account.get("username", "")))
            elif kind == "auth_success":
                token, account = payload
                self.lichess_client = LichessClient(token)
                self.account_connected = True
                self.lichess_username = str(account.get("id", account.get("username", "")))
                self.lichess_auth_pending = False
                self.lobby_status = f"Connected to Lichess as {self.lichess_username}."
                self._start_account_event_stream(self.lichess_client)
                if self.lichess_auth_resume_online:
                    self.lichess_auth_resume_online = False
                    self._start_selected_lichess_mode()
            elif kind == "auth_error":
                self.lichess_auth_pending = False
                self.lichess_auth_resume_online = False
                self.lobby_status = f"Lichess sign-in failed: {payload}"
            elif kind == "seek_active":
                self.lobby_status = "Casual seek active on Lichess. Press Esc to cancel."
            elif kind == "challenge_active":
                self.lobby_status = f"Challenge sent to {payload}; waiting for acceptance. Press Esc to cancel."
            elif kind == "challenge_accepted":
                self.lobby_status = f"{payload} accepted; connecting to the game…"
            elif kind == "challenge_declined":
                self.lobby_status = f"{payload} declined the challenge."
                self.online_waiting = False
            elif kind == "challenge_closed":
                self.lobby_status = f"Challenge to {payload} ended. Press Enter to try again."
                self.online_waiting = False
            elif kind == "incoming_accepted":
                self.lobby_status = "Challenge accepted; connecting to the game…"
            elif kind == "incoming_declined":
                self.lobby_status = "Incoming challenge declined."
            elif kind == "draw_action":
                self.lobby_status = "Draw offer sent." if payload else "Draw offer declined."
            elif kind == "stream_disconnected":
                self.lobby_status = f"Lichess connection lost; retrying automatically ({payload})."
            elif kind == "ai_started":
                self.online_game_id = str(payload)
                self.lobby_status = "Lichess AI game created; connecting to the board…"
            elif kind == "event" and isinstance(payload, dict):
                event_type = payload.get("type")
                if event_type == "gameStart":
                    self.online_game_id = payload.get("game", {}).get("id")
                    self.incoming_challenge = None
                    self.lobby_status = f"Game found ({self.online_game_id}); connecting to board…"
                elif event_type == "challenge":
                    self.incoming_challenge = payload
                    challenge = payload.get("challenge", {})
                    challenger = challenge.get("challenger", {})
                    name = challenger.get("name", challenger.get("id", "opponent"))
                    self.lobby_status = f"Incoming challenge from {name}. Press A to accept or X to decline."
                elif event_type == "gameFinish":
                    game_info = payload.get("game", {})
                    winner = payload.get("winner")
                    if winner is None and isinstance(game_info, dict):
                        winner = game_info.get("winner")
                    self.remote_winner = (
                        chess.WHITE if winner == "white" else chess.BLACK if winner == "black" else None
                    )
                    self.remote_draw = winner == "draw"
                    if self.game is not None:
                        self.game.status = "Lichess game finished."
                        self.game.finished = True
                    self.online_waiting = False
            elif kind == "game_state" and isinstance(payload, dict):
                self._apply_lichess_game_state(payload)
            elif kind == "seek_closed":
                if self.online_game_id is None:
                    self.lobby_status = "The Lichess seek ended. Press Enter to search again."
                    self.online_waiting = False
            elif kind == "error":
                message = str(payload)
                if self.game is not None:
                    self.game.status = message
                else:
                    self._stop_lichess()
                    self.lobby_status = message
                self.online_waiting = False
            elif kind == "move_error":
                message, uci = payload
                if self.game is not None and self.game.board.move_stack and self.game.board.peek().uci() == uci:
                    moving_color = not self.game.board.turn
                    self.game.board.pop()
                    if self.game.moves:
                        self.game.moves.pop()
                    self.game.remaining[moving_color] = max(
                        0.0, self.game.remaining[moving_color] - self.game.increment,
                    )
                    self.review_ply = len(self.game.moves)
                if self.game is not None:
                    self.game.status = str(message)

    def _apply_lichess_game_state(self, event: dict) -> None:
        state = event.get("state", event)
        if event.get("type") == "gameFull":
            self.online_game_id = str(event.get("id", self.online_game_id or ""))
            self.online_initial_fen = str(event.get("initialFen", "startpos"))
            white = event.get("white", {})
            black = event.get("black", {})
            self.white_name = str(white.get("name", white.get("id", "White")))
            self.black_name = str(black.get("name", black.get("id", "Black")))
            account_id = self.lichess_username.lower()
            if account_id and str(white.get("id", "")).lower() == account_id:
                self.online_color = chess.WHITE
            elif account_id and str(black.get("id", "")).lower() == account_id:
                self.online_color = chess.BLACK
        if self.game is None:
            self.game = GameSession(getattr(self, "online_minutes", 5), getattr(self, "online_increment", 0))
        previous_turn = self.game.board.turn
        try:
            board = chess.Board() if self.online_initial_fen == "startpos" else chess.Board(self.online_initial_fen)
            san_moves = []
            captured_by = {chess.WHITE: [], chess.BLACK: []}
            for uci in str(state.get("moves", "")).split():
                move = board.parse_uci(uci)
                san_moves.append(board.san(move))
                if board.is_capture(move):
                    captured_square = move.to_square
                    if board.is_en_passant(move):
                        captured_square += -8 if board.turn == chess.WHITE else 8
                    captured_piece = board.piece_at(captured_square)
                    if captured_piece:
                        captured_by[board.turn].append(captured_piece.piece_type)
                board.push(move)
        except (ValueError, chess.InvalidMoveError, chess.IllegalMoveError) as exc:
            self.game.status = f"Could not read the Lichess position: {exc}"
            return
        self.game.board = board
        self.game.moves = san_moves
        self.game.captured = captured_by
        self.game.remaining[chess.WHITE] = max(0.0, float(state.get("wtime", 0)) / 1000)
        self.game.remaining[chess.BLACK] = max(0.0, float(state.get("btime", 0)) / 1000)
        self.game.increment = int(state.get("winc", getattr(self, "online_increment", 0)))
        self.game.last_tick = time.monotonic()
        self.game.selected = None
        self.review_ply = len(san_moves)
        if self.online_color is not None:
            opponent_offer_key = "bdraw" if self.online_color == chess.WHITE else "wdraw"
            self.game.draw_offered = bool(state.get(opponent_offer_key, False))
        self.online_waiting = False
        status = str(state.get("status", "started"))
        self.game.status = f"Lichess game · {status.replace('_', ' ')}"
        if self.game.draw_offered:
            self.game.status = "Your opponent offered a draw. Press A to accept or D to counter-offer."
        if status not in {"started", "created"}:
            self.game.finished = True
            if status.lower() in {"draw", "stalemate", "repetition", "fiftymoves", "insufficientmaterial"}:
                self.remote_draw = True
        queued = self.premove
        if (queued is not None and self.online_color is not None
                and previous_turn != self.online_color and board.turn == self.online_color):
            if queued in board.legal_moves:
                self.premove = None
                self.game.selected = None
                self.game.push_move(queued)
                self.game.status = "Premove played."
                self._after_local_move()
            else:
                self.game.selected = queued.from_square
                self.game.status = "Premove stays queued; it is not legal in this position."
        elif queued is not None and self.game is not None:
            self.game.selected = queued.from_square

    def _send_lichess_move(self, uci: str) -> None:
        client, game_id = self.lichess_client, self.online_game_id
        if client is None or game_id is None:
            return
        def send() -> None:
            try:
                client.play_move(game_id, uci)
            except Exception as exc:
                self.lichess_events.put(("move_error", (str(exc), uci)))
        self._spawn_lichess_thread(send)

    def _cancel_online_seek(self) -> None:
        self._stop_lichess()
        self.online_waiting = False
        self.lobby_status = "Lichess search or challenge canceled."
        if self.account_connected:
            self._start_account_event_stream(self.lichess_client)

    def _stop_lichess(self) -> None:
        self.lichess_stop.set()
        with self.lichess_lock:
            responses = list(self.lichess_responses)
        for response in responses:
            try:
                response.close()
            except Exception:
                pass
        self.online_waiting = False
        self.online_game_id = None
        self.account_stream_running = False

    def _resign_lichess(self) -> None:
        client, game_id = self.lichess_client, self.online_game_id
        if client is not None and game_id:
            def resign() -> None:
                try:
                    client.resign(game_id)
                except Exception:
                    pass
            thread = threading.Thread(target=resign, daemon=True)
            thread.start()
            thread.join(timeout=2)
        self._stop_lichess()

    def _exit_current_match(self) -> None:
        self.exit_requested = True
        if self._is_remote_game() and self.online_game_id:
            self._resign_lichess()
