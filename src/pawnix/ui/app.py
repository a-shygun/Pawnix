"""Curses event loop for Pawnix's local chess interface."""

from __future__ import annotations

import curses
import queue
import sys
import threading
import time
import webbrowser

import chess

from pawnix import __version__
from pawnix.game.session import GameSession
from pawnix.game.storage import games_directory, load_game, recent_games, save_game
from pawnix.lichess.client import LichessClient
from pawnix.ui.lichess_flow import LichessFlowMixin
from pawnix.ui.preferences import load_theme, save_theme
from pawnix.ui.renderer import BoardRenderer


MATCH_MODES = (
    "Local · two players",
    "Online · Lichess AI",
    "Online · random match",
    "Online · challenge username",
)
TIME_CONTROLS = (
    ("Bullet · 1+0", 1, 0),
    ("Bullet · 2+1", 2, 1),
    ("Blitz · 3+0", 3, 0),
    ("Blitz · 3+2", 3, 2),
    ("Blitz · 5+0", 5, 0),
    ("Blitz · 5+3", 5, 3),
    ("Rapid · 10+0", 10, 0),
    ("Rapid · 10+5", 10, 5),
    ("Rapid · 15+10", 15, 10),
    ("Classical · 30+0", 30, 0),
)
GITHUB_URL = "https://github.com/a-shygun/Pawnix"


def _app_version() -> str:
    """Return the package version resolved from pyproject.toml metadata."""
    return __version__


def _lichess_seek_compatible(control: tuple[str, int, int]) -> bool:
    """Lichess Board random seeks support Rapid and Classical controls."""
    _, minutes, increment = control
    # Lichess estimates speed from a 40-move game; Rapid starts at 8 minutes.
    return minutes * 60 + increment * 40 >= 8 * 60


class PawnixApp(LichessFlowMixin):
    """Coordinate terminal input, game state, and rendering."""

    def __init__(
        self,
        minutes: int = 5,
        increment: int = 3,
        theme: str | None = None,
    ) -> None:
        self.game: GameSession | None = None
        self.pgn_prompt = False
        self.pgn_path_input = ""
        self.pgn_recent = recent_games()
        self.pgn_recent_index = 0
        self.incoming_challenge: dict | None = None
        self.review_ply = 0
        self.app_version = _app_version()
        self.renderer = BoardRenderer(theme or load_theme())
        self.mode_index = 0
        self.local_time_controls = TIME_CONTROLS
        self.time_index = next(
            (i for i, (_, base, inc) in enumerate(self.local_time_controls) if (base, inc) == (minutes, increment)),
            -1,
        )
        if self.time_index < 0:
            self.local_time_controls += ((f"Custom · {minutes}+{increment}", minutes, increment),)
            self.time_index = len(self.local_time_controls) - 1
        self.online_time_controls = tuple(control for control in self.local_time_controls if _lichess_seek_compatible(control))
        self.challenge_username = ""
        self.lichess_ai_level = 4
        self.lichess_ai_color = chess.WHITE
        self.lichess_client: LichessClient | None = LichessClient.from_environment()
        self.account_connected = self.lichess_client.authenticated
        self.time_controls = self.local_time_controls
        self._last_local_control = (minutes, increment)
        self.player_name = "Player"
        self.focus = 0
        self.lobby_status = ""
        self.mode = "local"
        self.white_name = self.player_name
        self.black_name = "Player 2"
        self._right_drag_start: int | None = None
        self._left_drag_start: int | None = None
        self._left_mouse_down = False
        self._suppress_click_after_release = False
        self._suppress_right_click_after_release: tuple[int, int] | None = None
        self.lichess_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.lichess_stop = threading.Event()
        self.lichess_lock = threading.Lock()
        self.lichess_responses: list[object] = []
        self.lichess_threads: list[threading.Thread] = []
        self.online_waiting = False
        self.online_game_id: str | None = None
        self.online_minutes = minutes
        self.online_increment = increment
        self.online_initial_fen = "startpos"
        self.remote_winner: chess.Color | None = None
        self.remote_draw = False
        self.lichess_username = ""
        self.online_color: chess.Color | None = None
        self.premove: chess.Move | None = None
        self.lichess_auth_pending = False
        self.lichess_auth_resume_online = False
        self.exit_requested = False

    def run(self) -> None:
        if self.account_connected:
            self._load_account_identity()
        # OSC 22-capable terminals can use a pointing hand instead of the
        # text-selection I-beam while Pawnix is accepting mouse clicks.
        try:
            sys.stdout.write("\x1b]22;pointer\x1b\\")
            sys.stdout.flush()
        except OSError:
            pass
        try:
            curses.wrapper(self._main_with_mouse_cleanup)
        finally:
            try:
                sys.stdout.write("\x1b]22;default\x1b\\")
                sys.stdout.flush()
            except OSError:
                pass

    def _main_with_mouse_cleanup(self, screen: "curses._CursesWindow") -> None:
        """Disable terminal mouse reporting before curses restores the shell."""
        try:
            self._main(screen)
        finally:
            try:
                curses.mousemask(0)
            except curses.error:
                pass
            self.renderer._begin_graphics_frame()

    def _main(self, screen: "curses._CursesWindow") -> None:
        screen.keypad(True)
        screen.timeout(100)
        try:
            screen.clearok(True)
        except curses.error:
            pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            mouse_events = curses.ALL_MOUSE_EVENTS | getattr(curses, "REPORT_MOUSE_POSITION", 0)
            curses.mousemask(mouse_events)
        except curses.error:
            pass
        try:
            curses.mouseinterval(0)
        except (curses.error, AttributeError):
            pass
        self.renderer.initialize()

        while True:
            self._drain_lichess_events()
            if self.game is None:
                self.renderer.draw_lobby(
                    screen, MATCH_MODES, self.mode_index, self.time_controls,
                    self.time_index, self.challenge_username,
                    self._account_label(), self.focus, self.lobby_status,
                    self.lichess_ai_level, self.app_version, self.lichess_ai_color,
                    self.lichess_username,
                )
            else:
                was_over = self.game.is_over
                self.game.tick()
                if not was_over and self.game.is_over:
                    self._save_local_autosave()
                orientation = (
                    self.online_color
                    if self._is_remote_game() and self.online_color is not None
                    else chess.WHITE
                )
                self.renderer.draw(
                    screen, self.game, self.white_name, self.black_name, self.review_ply,
                    orientation=orientation, version=self.app_version,
                    result_label=self._game_result_label(),
                    premove_color=self.online_color if self._is_remote_game() else None,
                    premove_move=self.premove,
                )
            key = screen.getch()
            if key == curses.KEY_RESIZE:
                # Ask ncurses to query the terminal itself. LINES/COLS can be
                # stale during rapid resize events, leaving stdscr and mouse
                # hit-testing on different coordinate grids.
                try:
                    resize = getattr(curses, "resizeterm", None)
                    if resize is not None:
                        try:
                            resize(0, 0)
                        except curses.error:
                            pass
                    curses.update_lines_cols()
                except curses.error:
                    pass
                try:
                    mouse_events = curses.ALL_MOUSE_EVENTS | getattr(curses, "REPORT_MOUSE_POSITION", 0)
                    curses.mousemask(mouse_events)
                    curses.mouseinterval(0)
                except curses.error:
                    pass
                try:
                    screen.clearok(True)
                    screen.erase()
                except curses.error:
                    pass
                # A resize can interrupt a press/release pair. Discard that
                # stale gesture so the next click starts cleanly.
                self._left_mouse_down = False
                self._left_drag_start = None
                self._suppress_click_after_release = False
                self._right_drag_start = None
                self._suppress_right_click_after_release = None
                continue
            if key == -1:
                continue
            if key == 3:
                self._stop_lichess()
                return
            if key == curses.KEY_MOUSE:
                self._handle_mouse()
                if self.exit_requested:
                    return
                continue
            if self.game is None:
                if self.renderer.signout_confirm_open:
                    if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                        self.renderer.signout_choice = 1 - self.renderer.signout_choice
                    elif key in (curses.KEY_ENTER, 10, 13):
                        self._handle_signout_confirmation(self.renderer.signout_choice)
                    elif key in (27, ord("q"), ord("Q")):
                        self.renderer.signout_confirm_open = False
                    continue
                if self.renderer.help_modal_open:
                    if key in (27, ord("?"), curses.KEY_F1, 10, 13):
                        self.renderer.help_modal_open = False
                    continue
                if key in (ord("?"), curses.KEY_F1):
                    self.renderer.help_modal_open = True
                    continue
                if self.online_waiting and key == 27:
                    self._cancel_online_seek()
                    continue
                if not self._handle_lobby_key(key):
                    if self.online_waiting:
                        self._cancel_online_seek()
                    return
                continue
            if self.renderer.result_modal_open:
                if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                    self.renderer.result_choice = 1 - self.renderer.result_choice
                elif key in (curses.KEY_ENTER, 10, 13):
                    self._handle_result_action(self.renderer.result_choice)
                elif key in (27, ord("e"), ord("E"), ord("b")):
                    self._handle_result_action(0)
                elif key in (ord("r"), ord("R")):
                    self._handle_result_action(1)
                continue
            if self.game.pending_promotion is not None:
                promotion_keys = {
                    ord("q"): chess.QUEEN, ord("r"): chess.ROOK,
                    ord("b"): chess.BISHOP, ord("n"): chess.KNIGHT,
                }
                if key in promotion_keys:
                    self.game.choose_promotion(promotion_keys[key])
                    self._after_local_move()
                elif key == 27:
                    self.game.cancel_promotion()
                continue
            if self.renderer.exit_confirm_open:
                if key in (ord("q"), ord("Q"), curses.KEY_ENTER, 10, 13):
                    self.renderer.exit_confirm_open = False
                    self._exit_current_match()
                    return
                if key == 27:
                    self.renderer.exit_confirm_open = False
                continue
            if self.renderer.back_confirm_open:
                if key in (ord("b"), ord("B"), curses.KEY_ENTER, 10, 13):
                    self.renderer.back_confirm_open = False
                    self._return_to_welcome()
                elif key in (27, ord("q"), ord("Q")):
                    self.renderer.back_confirm_open = False
                continue
            if self.renderer.help_modal_open:
                if key in (27, ord("?"), curses.KEY_F1, 10, 13):
                    self.renderer.help_modal_open = False
                continue
            if self.pgn_prompt:
                if key in (curses.KEY_ENTER, 10, 13):
                    self._load_pgn_prompt()
                elif key in (27,):
                    self.pgn_prompt = False
                    self.game.status = "PGN import canceled."
                elif key in (curses.KEY_UP, curses.KEY_DOWN) and self.pgn_recent:
                    direction = -1 if key == curses.KEY_UP else 1
                    self.pgn_recent_index = (self.pgn_recent_index + direction) % len(self.pgn_recent)
                    self.pgn_path_input = str(self.pgn_recent[self.pgn_recent_index])
                    self.game.status = (
                        f"Recent PGN {self.pgn_recent_index + 1}/{len(self.pgn_recent)}: "
                        f"{self.pgn_recent[self.pgn_recent_index].name} · Enter loads"
                    )
                elif key in (curses.KEY_BACKSPACE, 8, 127):
                    self.pgn_path_input = self.pgn_path_input[:-1]
                    self.game.status = f"Import PGN: {self.pgn_path_input}_"
                elif 32 <= key <= 126:
                    self.pgn_path_input += chr(key)
                    self.game.status = f"Import PGN: {self.pgn_path_input}_"
                continue
            if key in (ord("?"), curses.KEY_F1) and not self.game.input_buffer:
                self.renderer.help_modal_open = True
            elif key == ord("v") and not self.game.input_buffer:
                self.renderer.panel_on_left = not self.renderer.panel_on_left
            elif key == ord("b") and not self.game.input_buffer:
                self.renderer.back_confirm_open = True
            elif key in (ord("s"), ord("S")) and not self.game.input_buffer:
                self._forfeit_game()
            elif key in (ord("r"), ord("R")) and not self.game.input_buffer:
                self.renderer.rain_enabled = not self.renderer.rain_enabled
            elif key in (ord("g"), ord("G")) and not self.game.input_buffer:
                self.renderer.board_gaps_enabled = not self.renderer.board_gaps_enabled
            elif key in (ord("c"), ord("C")) and not self.game.input_buffer:
                style = self.renderer.cycle_piece_style()
                style_name = {
                    "art": "art pieces", "unicode": "Unicode pieces", "png": "PNG pieces",
                }[style]
                self.game.status = f"Showing {style_name}."
            elif key in (ord("q"), ord("Q")) and not self.game.input_buffer:
                self.renderer.exit_confirm_open = True
            elif key in (ord("u"), ord("U")) and not self.game.input_buffer:
                if not self._is_remote_game() and self.game.undo():
                    self.review_ply = len(self.game.moves)
                    self._save_local_autosave()
                elif self._is_remote_game():
                    self.game.status = "Undo is available in local games only."
            elif key in (ord("y"), ord("Y")) and not self.game.input_buffer:
                if not self._is_remote_game() and self.game.redo():
                    self.review_ply = len(self.game.moves)
                    self._save_local_autosave()
            elif key in (ord("p"), ord("P")) and not self.game.input_buffer:
                if self._is_remote_game():
                    self.game.status = "Pause is available in local games only."
                else:
                    self.game.paused = not self.game.paused
                    self.game.last_tick = time.monotonic()
                    self.game.status = "Game paused." if self.game.paused else "Game resumed."
            elif key == ord("D") and not self.game.input_buffer:
                self._claim_or_offer_draw()
            elif key == ord("o") and not self.game.input_buffer:
                self._offer_local_draw()
            elif key == ord("A") and not self.game.input_buffer and self.game.draw_offered:
                if self._is_remote_game():
                    self._send_draw_action(True)
                    self.game.status = "Draw acceptance sent."
                else:
                    self.game.finished = True
                    self.game.status = "Draw agreed."
                    self._save_local_autosave()
            elif key == ord("n") and not self.game.input_buffer and not self._is_remote_game():
                self._restart_local_game()
            elif key in (ord("x"), ord("X")) and not self.game.input_buffer and not self._is_remote_game():
                try:
                    path = save_game(self.game, archive=True)
                    self.game.status = f"PGN exported to {path}"
                except OSError as exc:
                    self.game.status = f"Could not export PGN: {exc}"
            elif key in (ord("i"), ord("I")) and not self.game.input_buffer and not self._is_remote_game():
                self.pgn_prompt = True
                self.pgn_path_input = ""
                self.pgn_recent = recent_games()
                self.pgn_recent_index = 0
                self.game.status = "Import PGN path (blank loads most recent): _"
            elif key in (ord("l"), ord("L")) and not self.game.input_buffer and not self._is_remote_game():
                try:
                    self.game = load_game()
                    self.mode = "local"
                    self.review_ply = len(self.game.moves)
                    self.game.status = "Autosaved game resumed."
                except (OSError, ValueError) as exc:
                    self.game.status = f"No autosave available: {exc}"
            elif key in (ord("t"), ord("T")):
                direction = -1 if key == ord("T") else 1
                self.renderer.preview_theme(self.renderer.theme_index + direction)
                self.renderer.select_theme()
                try:
                    save_theme(self.renderer.theme.key)
                    self.game.status = f"{self.renderer.theme.label} theme selected."
                except OSError:
                    self.game.status = f"{self.renderer.theme.label} selected for this session."
            elif key == curses.KEY_LEFT and not self.game.input_buffer:
                self._navigate_moves(-1)
            elif key == curses.KEY_RIGHT and not self.game.input_buffer:
                self._navigate_moves(1)
            elif self.renderer.theme_menu_open and key in (curses.KEY_UP, curses.KEY_DOWN):
                direction = -1 if key == curses.KEY_UP else 1
                self.renderer.preview_theme(self.renderer.theme_menu_index + direction)
            elif self.renderer.theme_menu_open and key in (curses.KEY_ENTER, 10, 13):
                self.renderer.select_theme()
                try:
                    save_theme(self.renderer.theme.key)
                    self.game.status = f"{self.renderer.theme.label} saved as default theme."
                except OSError:
                    self.game.status = "Theme selected for this session; could not save settings."
            elif self.renderer.theme_menu_open and key == 27:
                self.renderer.cancel_theme_preview()
            elif key == ord("-"):
                self.renderer.zoom = max(0, self.renderer.zoom - 1)
            elif key == ord("="):
                self.renderer.zoom += 1
            elif key == 27:
                self.game.selected = None
                self.premove = None
                self.game.status = "Selection cleared."
            elif key in (curses.KEY_BACKSPACE, 8, 127):
                self.game.input_buffer = self.game.input_buffer[:-1]
            elif key in (curses.KEY_ENTER, 10, 13):
                if self._is_remote_game() and self.online_color is not None and self.game.board.turn != self.online_color:
                    self.game.status = "Waiting for your opponent's move."
                    continue
                before = len(self.game.moves)
                self.game.submit_move()
                if len(self.game.moves) > before:
                    self._after_local_move()
            elif 32 <= key <= 126:
                if self._is_remote_game() and self.online_color is not None and self.game.board.turn != self.online_color:
                    self.game.status = "Waiting for your opponent's move."
                else:
                    self.game.input_buffer += chr(key)

    def _handle_lobby_key(self, key: int) -> bool:
        if self.incoming_challenge is not None:
            if key in (ord("a"), ord("A"), curses.KEY_ENTER, 10, 13):
                self._accept_incoming_challenge()
                return True
            if key in (ord("x"), ord("X"), 27):
                self._decline_incoming_challenge()
                return True
        if key == ord("q"):
            return False
        if key in (ord("r"), ord("R")) and self.focus == 4 and self.account_connected:
            self._begin_lichess_auth()
            return True
        elif key in (9, getattr(curses, "KEY_BTAB", -999)):
            self._tab_lobby_focus(-1 if key == getattr(curses, "KEY_BTAB", -999) else 1)
        elif self.focus == 2 and self.mode_index == 3 and key in map(ord, "wasdWASD"):
            if len(self.challenge_username) < 32:
                self.challenge_username += chr(key)
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_UP, curses.KEY_DOWN,
                     ord("w"), ord("a"), ord("s"), ord("d"), ord("W"), ord("A"), ord("S"), ord("D")):
            step = -1 if key in (curses.KEY_LEFT, curses.KEY_UP, ord("a"), ord("A"), ord("w"), ord("W")) else 1
            if self.focus == 0:
                self._set_mode_index(self.mode_index + step)
            elif self.focus == 8:
                self.lichess_ai_level = max(1, min(8, self.lichess_ai_level + step))
            elif self.focus == 9:
                self.lichess_ai_color = not self.lichess_ai_color
            elif self.focus == 1:
                self._move_time_choice(key)
                if self.mode_index != 2:
                    _, base, inc = self.time_controls[self.time_index]
                    self._last_local_control = (base, inc)
            elif self.focus in (6, 7, 4):
                action_order = (7, 6, 4)
                index = action_order.index(self.focus)
                self.focus = action_order[(index + step) % len(action_order)]
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.focus == 4:
                self._request_lichess_account_action()
            elif self.focus == 7:
                self.renderer.help_modal_open = True
            elif self.focus == 6:
                self._start_game()
            elif self.focus == 2 and self.mode_index == 3:
                self.focus = 6
            else:
                self._move_lobby_focus(1)
        elif key in (curses.KEY_BACKSPACE, 8, 127) and self.focus == 2:
            self.challenge_username = self.challenge_username[:-1]
        elif 32 <= key <= 126 and self.focus == 2:
            if self.mode_index == 3 and len(self.challenge_username) < 32:
                self.challenge_username += chr(key)
        return True

    def _lobby_focus_order(self) -> list[int]:
        order = [0]
        if self.mode_index == 1:
            order.extend((8, 9))
        if self.mode_index == 3:
            order.append(2)
        order.append(1)
        order.extend((7, 6, 4))
        return order

    def _move_lobby_focus(self, step: int) -> None:
        order = self._lobby_focus_order()
        try:
            index = order.index(self.focus)
        except ValueError:
            index = 0
        self.focus = order[(index + step) % len(order)]

    def _tab_lobby_focus(self, step: int) -> None:
        groups = [0]
        if self.mode_index == 1:
            groups.append(8)
        if self.mode_index == 3:
            groups.append(2)
        groups.append(1)
        groups.append(7)
        current_group = {9: 8, 6: 7, 4: 7}.get(self.focus, self.focus)
        try:
            index = groups.index(current_group)
        except ValueError:
            index = 0
        self.focus = groups[(index + step) % len(groups)]

    def _move_time_choice(self, key: int) -> None:
        if not self.time_controls:
            return
        rows = (len(self.time_controls) + 1) // 2
        col, row = divmod(self.time_index, rows)
        horizontal = key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("a"), ord("A"), ord("d"), ord("D"))
        if horizontal:
            candidate = (1 - col) * rows + row
        else:
            direction = -1 if key in (curses.KEY_UP, ord("w"), ord("W")) else 1
            candidate = col * rows + (row + direction) % rows
        if candidate < len(self.time_controls):
            self.time_index = candidate

    def _set_mode_index(self, index: int) -> None:
        """Switch clock choices with match mode and remember the local preset."""
        next_index = index % len(MATCH_MODES)
        if next_index == self.mode_index:
            return
        if self.mode_index != 2 and self.time_controls:
            _, minutes, increment = self.time_controls[self.time_index]
            self._last_local_control = (minutes, increment)
        self.mode_index = next_index
        self.time_controls = self.online_time_controls if next_index == 2 else self.local_time_controls
        desired = self._last_local_control if next_index != 2 else (10, 0)
        self.time_index = next(
            (i for i, (_, minutes, increment) in enumerate(self.time_controls) if (minutes, increment) == desired),
            0,
        )

    def _account_label(self) -> str:
        action = "SIGN OUT" if self.account_connected else "SIGN IN"
        return f"[ {action} ]"

    def _return_to_welcome(self) -> None:
        if self.online_waiting or self.online_game_id:
            if self.game is None or not self.game.is_over:
                self._resign_lichess()
            else:
                self._stop_lichess()
        self.game = None
        self.premove = None
        self.lobby_status = ""
        self.focus = 0
        self.remote_winner = None
        self.remote_draw = False
        self.renderer.help_modal_open = False
        self.renderer.result_modal_open = False
        if self.account_connected:
            self._start_account_event_stream(self.lichess_client)

    def _forfeit_game(self) -> None:
        if self.game is None or self.game.is_over:
            return
        forfeiting_color = (
            self.online_color if self._is_remote_game() and self.online_color is not None
            else self.game.board.turn
        )
        self.game.flagged = forfeiting_color
        self.game.status = f"{'White' if forfeiting_color else 'Black'} resigned."
        self.remote_winner = not forfeiting_color if self._is_remote_game() else None
        self.remote_draw = False
        if self._is_remote_game():
            self._resign_lichess()
        else:
            self._save_local_autosave()

    def _game_result_label(self) -> str:
        if self.game is None:
            return "GAME OVER"
        outcome = self.game.board.outcome()
        winner = outcome.winner if outcome else None
        if self._is_remote_game():
            if self.remote_draw:
                return "DRAW"
            if self.remote_winner is not None:
                winner = self.remote_winner
            elif self.game.flagged is not None:
                winner = not self.game.flagged
            if winner is None:
                return "GAME OVER"
            if self.online_color is not None:
                return "YOU WIN" if winner == self.online_color else "YOU LOSE"
            return "WHITE WINS" if winner == chess.WHITE else "BLACK WINS"
        if self.game.flagged is not None:
            winner = not self.game.flagged
        if winner is None:
            return "DRAW"
        return "WHITE WINS" if winner == chess.WHITE else "BLACK WINS"

    def _handle_result_action(self, choice: int) -> None:
        if choice == 0:
            self._return_to_welcome()
            return
        self.renderer.help_modal_open = False
        if self._is_remote_game():
            self._stop_lichess()
            while True:
                try:
                    self.lichess_events.get_nowait()
                except queue.Empty:
                    break
        self.game = None
        self.remote_winner = None
        self.remote_draw = False
        self._start_game()

    def _start_game(self) -> None:
        if self.mode_index == 2:
            self._start_lichess_seek()
            return
        if self.mode_index == 1:
            self._start_lichess_ai()
            return
        if self.mode_index == 3:
            self._start_lichess_challenge()
            return
        _, minutes, increment = self.time_controls[self.time_index]
        self.game = GameSession(minutes, increment)
        self.premove = None
        self.review_ply = 0
        self.mode = "local"
        self.white_name = self.player_name.strip() or "White"
        self.black_name = "Player 2"
        self.game.status = "White to move. Click a piece or enter a move in SAN/UCI notation."
        self._save_local_autosave()

    def _restart_local_game(self) -> None:
        if self.game is None or self._is_remote_game():
            return
        self.game = GameSession(self.game.minutes, self.game.increment)
        self.review_ply = 0
        self.premove = None
        self.game.status = "Local game restarted. White to move."
        self._save_local_autosave()

    def _save_local_autosave(self) -> None:
        if self.game is None or self._is_remote_game():
            return
        try:
            save_game(self.game)
            if self.game.is_over:
                save_game(self.game, archive=True)
        except OSError:
            pass

    def _load_pgn_prompt(self) -> None:
        from pathlib import Path

        path_text = self.pgn_path_input.strip()
        self.pgn_prompt = False
        try:
            if path_text:
                path = Path(path_text).expanduser()
            else:
                choices = recent_games()
                path = choices[0] if choices else games_directory() / "current.pgn"
            self.game = load_game(path)
            self.mode = "local"
            self.review_ply = len(self.game.moves)
            self.premove = None
            self.game.status = f"Imported {path.name}."
            self._save_local_autosave()
        except (OSError, ValueError) as exc:
            self.game.status = f"Could not import PGN: {exc}"

    def _claim_or_offer_draw(self) -> None:
        if self.game is None:
            return
        if self._is_remote_game():
            self._send_draw_action(True)
            self.game.status = "Draw offered to your opponent."
        elif self.game.claim_draw():
            self._save_local_autosave()
        else:
            self.game.status = "No threefold repetition or fifty-move draw can be claimed now."

    def _offer_local_draw(self) -> None:
        if self.game is None:
            return
        if self._is_remote_game():
            self._send_draw_action(True)
            self.game.status = "Draw offered to your opponent."
        else:
            self.game.draw_offered = True
            self.game.status = "Draw offered. The other player can press A to accept."

    def _after_local_move(self) -> None:
        if self.game is None:
            return
        self.premove = None
        if self._is_remote_game():
            if self.game.board.move_stack:
                self._send_lichess_move(self.game.board.peek().uci())
        self.review_ply = len(self.game.moves)
        self._save_local_autosave()

    def _navigate_moves(self, step: int) -> None:
        if self.game is not None:
            self.review_ply = max(0, min(len(self.game.moves), self.review_ply + step))

    def _handle_mouse(self) -> None:
        if self.game is None:
            self._handle_lobby_mouse()
            return
        try:
            _, mouse_x, mouse_y, _, state = curses.getmouse()
        except curses.error:
            return
        if self.renderer.result_modal_open:
            if state & (getattr(curses, "BUTTON1_CLICKED", 0) | getattr(curses, "BUTTON1_RELEASED", 0)):
                self._handle_game_click(mouse_x, mouse_y)
            return
        if self.renderer.exit_confirm_open:
            if state & (getattr(curses, "BUTTON1_CLICKED", 0) | getattr(curses, "BUTTON1_RELEASED", 0)):
                self._handle_game_click(mouse_x, mouse_y)
            return
        if self.renderer.back_confirm_open:
            if state & (getattr(curses, "BUTTON1_CLICKED", 0) | getattr(curses, "BUTTON1_RELEASED", 0)):
                self._handle_game_click(mouse_x, mouse_y)
            return
        if self.renderer.help_modal_open:
            if state & (getattr(curses, "BUTTON1_CLICKED", 0) | getattr(curses, "BUTTON1_RELEASED", 0)):
                self.renderer.help_modal_open = False
            return
        right_pressed = getattr(curses, "BUTTON3_PRESSED", 0)
        right_released = getattr(curses, "BUTTON3_RELEASED", 0)
        right_clicked = getattr(curses, "BUTTON3_CLICKED", 0)
        if right_pressed and state & right_pressed:
            self._suppress_right_click_after_release = None
            if self._right_drag_start is None:
                self._right_drag_start = self.renderer.square_at(mouse_x, mouse_y)
            return
        if right_released and state & right_released:
            destination = self.renderer.square_at(mouse_x, mouse_y)
            if self._right_drag_start is not None and destination is not None:
                if self._right_drag_start == destination:
                    self.renderer.mark_right_click(destination, destination)
                else:
                    self.renderer.mark_right_click(self._right_drag_start, destination)
                self._suppress_right_click_after_release = (mouse_x, mouse_y)
            self._right_drag_start = None
            return
        if right_clicked and state & right_clicked:
            if self._suppress_right_click_after_release == (mouse_x, mouse_y):
                self._suppress_right_click_after_release = None
                return
            self._suppress_right_click_after_release = None
            square = self.renderer.square_at(mouse_x, mouse_y)
            if square is not None:
                self.renderer.mark_right_click(square, square)
            return

        left_pressed = getattr(curses, "BUTTON1_PRESSED", 0)
        left_released = getattr(curses, "BUTTON1_RELEASED", 0)
        left_clicked = getattr(curses, "BUTTON1_CLICKED", 0)
        if left_pressed and state & left_pressed:
            if not self._left_mouse_down:
                self._left_mouse_down = True
                self._left_drag_start = self.renderer.square_at(mouse_x, mouse_y)
                self._suppress_click_after_release = False
            return
        if left_released and state & left_released:
            if self._left_mouse_down:
                origin = self._left_drag_start
                self._left_mouse_down = False
                self._left_drag_start = None
                self._suppress_click_after_release = True
                destination = self.renderer.square_at(mouse_x, mouse_y)
                if origin is not None and destination is not None and origin != destination:
                    self._move_by_drag(origin, destination)
                else:
                    self._handle_game_click(mouse_x, mouse_y)
                return
            self._suppress_click_after_release = True
            self._handle_game_click(mouse_x, mouse_y)
            return
        if left_clicked and state & left_clicked:
            if self._suppress_click_after_release:
                self._suppress_click_after_release = False
                return
            self._handle_game_click(mouse_x, mouse_y)
            return

    def _handle_game_click(self, mouse_x: int, mouse_y: int) -> None:
        if self.game is None:
            return
        if self.renderer.result_modal_open:
            for index, bounds in enumerate(self.renderer.result_button_bounds or ()):
                if mouse_y == bounds[0] and bounds[1] <= mouse_x <= bounds[2]:
                    self._handle_result_action(index)
                    return
            return
        if self.renderer.exit_confirm_open:
            for index, bounds in enumerate(self.renderer.exit_confirm_bounds or ()):
                if mouse_y == bounds[0] and bounds[1] <= mouse_x <= bounds[2]:
                    if index == 0:
                        self.renderer.exit_confirm_open = False
                        self._exit_current_match()
                    else:
                        self.renderer.exit_confirm_open = False
                    return
            return
        if self.renderer.back_confirm_open:
            for index, bounds in enumerate(self.renderer.back_confirm_bounds or ()):
                if mouse_y == bounds[0] and bounds[1] <= mouse_x <= bounds[2]:
                    self.renderer.back_confirm_open = False
                    if index == 0:
                        self._return_to_welcome()
                    return
            return
        back = self.renderer.back_button_bounds
        if back and mouse_y == back[0] and back[1] <= mouse_x <= back[2]:
            self.renderer.back_confirm_open = True
            return
        help_button = self.renderer.help_button_bounds
        if help_button and mouse_y == help_button[0] and help_button[1] <= mouse_x <= help_button[2]:
            self.renderer.help_modal_open = True
            return
        side_button = self.renderer.side_button_bounds
        if side_button and mouse_y == side_button[0] and side_button[1] <= mouse_x <= side_button[2]:
            self.renderer.panel_on_left = not self.renderer.panel_on_left
            return
        theme_button = self.renderer.theme_button_bounds
        if theme_button and mouse_y == theme_button[0] and theme_button[1] <= mouse_x <= theme_button[2]:
            self.renderer.toggle_theme_menu()
            return
        surrender_button = self.renderer.surrender_button_bounds
        if surrender_button and mouse_y == surrender_button[0] and surrender_button[1] <= mouse_x <= surrender_button[2]:
            self._forfeit_game()
            return
        rain_button = self.renderer.rain_button_bounds
        if rain_button and mouse_y == rain_button[0] and rain_button[1] <= mouse_x <= rain_button[2]:
            self.renderer.rain_enabled = not self.renderer.rain_enabled
            return
        gaps_button = self.renderer.gaps_button_bounds
        if gaps_button and mouse_y == gaps_button[0] and gaps_button[1] <= mouse_x <= gaps_button[2]:
            self.renderer.board_gaps_enabled = not self.renderer.board_gaps_enabled
            return
        piece_button = self.renderer.piece_button_bounds
        if (
            piece_button
            and mouse_y == piece_button[0]
            and piece_button[1] <= mouse_x <= piece_button[2]
        ):
            style = self.renderer.cycle_piece_style()
            style_name = {
                "art": "art pieces", "unicode": "Unicode pieces", "png": "PNG pieces",
            }[style]
            self.game.status = f"Showing {style_name}."
            return
        nav = self.renderer.move_nav_bounds
        if nav and mouse_y == nav[0]:
            if nav[1][0] <= mouse_x <= nav[1][1]:
                self._navigate_moves(-1)
            elif nav[2][0] <= mouse_x <= nav[2][1]:
                self._navigate_moves(1)
            return
        if self.renderer.handle_theme_click(mouse_x, mouse_y):
            if self.renderer.theme_commit_requested:
                try:
                    save_theme(self.renderer.theme.key)
                    self.game.status = f"{self.renderer.theme.label} saved as default theme."
                except OSError:
                    self.game.status = "Theme selected for this session; could not save settings."
            return
        square = self.renderer.square_at(mouse_x, mouse_y)
        if square is not None:
            if self._is_remote_game() and self.online_color is not None and self.game.board.turn != self.online_color:
                self._queue_premove_click(square)
                return
            if self.review_ply < len(self.game.moves):
                self.review_ply = len(self.game.moves)
                return
            if self.premove is not None:
                self.premove = None
                self.game.selected = None
            before = len(self.game.moves)
            self.game.select_square(square)
            if len(self.game.moves) > before:
                self._after_local_move()

    def _move_by_drag(self, origin: chess.Square, destination: chess.Square) -> None:
        if self.game is None:
            return
        if self.review_ply < len(self.game.moves):
            self.review_ply = len(self.game.moves)
            return
        if self._is_remote_game() and self.online_color is not None and self.game.board.turn != self.online_color:
            self._queue_premove(origin, destination)
            return
        if self.premove is not None:
            self.premove = None
        before = len(self.game.moves)
        self.game.selected = None
        self.game.select_square(origin)
        if self.game.selected == origin:
            self.game.select_square(destination)
        if len(self.game.moves) > before:
            self._after_local_move()

    def _queue_premove_click(self, square: chess.Square) -> None:
        """Select or queue a remote move while waiting for the opponent."""
        if self.game is None or self.online_color is None:
            return
        piece = self.game.board.piece_at(square)
        if self.premove is not None and square == self.premove.from_square:
            self.premove = None
            self.game.selected = None
            self.game.status = "Premove cleared."
            return
        if (piece is not None and piece.color == self.online_color
                and self.game.selected is not None and self.game.selected != square):
            if self._queue_premove(self.game.selected, square):
                return
        if piece is not None and piece.color == self.online_color:
            if self.game.selected == square:
                self.game.selected = None
                self.premove = None
                self.game.status = "Premove selection cleared."
            else:
                self.game.selected = square
                self.premove = None
                self.game.status = f"Selected {chess.square_name(square)} for a premove."
            return
        if self.game.selected is not None:
            self._queue_premove(self.game.selected, square)

    def _queue_premove(self, origin: chess.Square, destination: chess.Square) -> bool:
        if self.game is None or self.online_color is None:
            return False
        piece = self.game.board.piece_at(origin)
        if piece is None or piece.color != self.online_color:
            self.game.status = "Choose one of your pieces to queue a premove."
            return False
        if destination == origin:
            self.premove = None
            self.game.selected = None
            self.game.status = "Premove cleared."
            return True
        target_piece = self.game.board.piece_at(destination)
        move = chess.Move(origin, destination)
        if piece.piece_type == chess.PAWN and chess.square_rank(destination) in (0, 7):
            move.promotion = chess.QUEEN
        premove_board = self.game.board.copy(stack=False)
        premove_board.turn = self.online_color
        if target_piece is not None and target_piece.color == self.online_color:
            # The opponent may capture this piece first. Validate the intended
            # reply with its square vacated, then retain the move until the
            # server position makes it a legal capture.
            premove_board.remove_piece_at(destination)
        if move not in premove_board.pseudo_legal_moves:
            self.game.selected = origin
            self.premove = None
            self.game.status = "That premove is not possible from this position."
            return False
        self.premove = move
        self.game.selected = origin
        self.game.status = (
            f"Premove {move.uci()} queued; click the piece again to clear it."
            if target_piece is None or target_piece.color != self.online_color
            else f"Conditional capture {move.uci()} queued; it plays if that piece is taken."
        )
        return True

    def _handle_lobby_mouse(self) -> None:
        try:
            _, mouse_x, mouse_y, _, state = curses.getmouse()
        except curses.error:
            return
        if not self._is_primary_mouse_event(state):
            return
        if self.renderer.signout_confirm_open:
            for choice, bounds in enumerate(self.renderer.signout_button_bounds or ()):
                if mouse_y == bounds[0] and bounds[1] <= mouse_x <= bounds[2]:
                    self._handle_signout_confirmation(choice)
                    return
            self.renderer.signout_confirm_open = False
            return
        if self.renderer.help_modal_open:
            self.renderer.help_modal_open = False
            return
        link = self.renderer.welcome_github_bounds
        if link and mouse_y == link[0] and link[1] <= mouse_x <= link[2]:
            webbrowser.open(GITHUB_URL)
            return
        geometry = self.renderer._lobby_geometry
        for y, index, left, right in geometry.get("mode_rows", ()):
            if mouse_y == y and left <= mouse_x <= right:
                self._set_mode_index(index)
                self.focus = 0
                return
        ai_level = geometry.get("ai_level")
        if ai_level and ai_level[0] == mouse_y:
            _, minus_left, minus_right, plus_left, plus_right = ai_level
            if minus_left <= mouse_x <= minus_right:
                self.lichess_ai_level = max(1, self.lichess_ai_level - 1)
            elif plus_left <= mouse_x <= plus_right:
                self.lichess_ai_level = min(8, self.lichess_ai_level + 1)
            else:
                self.focus = 8
                return
            self.focus = 8
            return
        ai_color = geometry.get("ai_color")
        if ai_color and ai_color[0] == mouse_y:
            _, white_bounds, black_bounds = ai_color
            if white_bounds[0] <= mouse_x <= white_bounds[1]:
                self.lichess_ai_color = chess.WHITE
            elif black_bounds[0] <= mouse_x <= black_bounds[1]:
                self.lichess_ai_color = chess.BLACK
            self.focus = 9
            return
        for y, index, left, right in geometry.get("time_rows", ()):
            if mouse_y == y and left <= mouse_x <= right:
                self.time_index = index
                self.focus = 1
                return
        account = geometry.get("account")
        if account and account[0] == mouse_y and account[1] <= mouse_x <= account[2]:
            self.focus = 4
            self._request_lichess_account_action()
            return
        name = geometry.get("challenge")
        if name and name[0] == mouse_y and name[1] <= mouse_x <= name[2]:
            self.focus = 2
            return
        guide = geometry.get("guide")
        if guide and guide[0] == mouse_y and guide[1] <= mouse_x <= guide[2]:
            self.focus = 7
            self.renderer.help_modal_open = True
            return
        start = geometry.get("start")
        if start and start[0] == mouse_y and start[1] <= mouse_x <= start[2]:
            self.focus = 6
            self._start_game()
            return
        for kind, left, top, width, height in geometry.get("boxes", ()):
            if left <= mouse_x < left + width and top <= mouse_y < top + height:
                self.focus = {"mode": 0, "time": 1, "challenge": 2, "ai_color": 9,
                              "account": 4, "actions": 6, "status": 6}.get(kind, self.focus)
                return

    def _is_primary_mouse_event(self, state: int) -> bool:
        """Accept press, click, or release reporting without double-activating."""
        pressed = getattr(curses, "BUTTON1_PRESSED", 0)
        released = getattr(curses, "BUTTON1_RELEASED", 0)
        clicked = getattr(curses, "BUTTON1_CLICKED", 0)
        if pressed and state & pressed:
            self._left_mouse_down = True
            self._suppress_click_after_release = False
            return True
        if released and state & released:
            if self._left_mouse_down:
                self._left_mouse_down = False
                self._suppress_click_after_release = True
                return False
            self._suppress_click_after_release = True
            return True
        if clicked and state & clicked:
            if self._left_mouse_down:
                self._left_mouse_down = False
                self._suppress_click_after_release = True
                return False
            if self._suppress_click_after_release:
                self._suppress_click_after_release = False
                return False
            return True
        return False
