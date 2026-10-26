"""Modal dialogs shared by the Pawnix terminal renderer."""

from __future__ import annotations

import curses
import textwrap

from pawnix.game.session import GameSession


class ModalRendererMixin:
    """Draw modal content using the color and text helpers from BoardRenderer."""

    def _draw_promotion_modal(self, screen: "curses._CursesWindow") -> None:
        height, width = screen.getmaxyx()
        labels = "[Q] Queen   [R] Rook   [B] Bishop   [N] Knight"
        if width < 36 or height < 7:
            self._addstr(screen, max(0, height // 2), 1, "Promote: Q / R / B / N", self._color(1, curses.A_REVERSE))
            return
        box_width, box_height = min(54, width - 4), min(7, height - 2)
        x, y = (width - box_width) // 2, (height - box_height) // 2
        for row in range(y + 1, y + box_height - 1):
            self._addstr(screen, row, x + 1, " " * (box_width - 2), self._color(1))
        self._draw_border(screen, x, y, box_width, box_height, "PROMOTE PAWN")
        self._addstr(screen, y + 3, x + max(2, (box_width - self._display_width(labels)) // 2), labels,
                     self._color(1, curses.A_BOLD))
        self._addstr(screen, y + box_height - 2, x + 2, "Press Q, R, B, or N · Esc cancels",
                     self._color(1, curses.A_DIM))

    def _draw_help_modal(self, screen: "curses._CursesWindow", version: str = "") -> None:
        height, width = screen.getmaxyx()
        box_width = min(88, width - 6)
        box_height = min(24, height - 4)
        if box_width < 30 or box_height < 8:
            return
        x, y = (width - box_width) // 2, (height - box_height) // 2
        for row in range(y + 1, y + box_height - 1):
            self._addstr(screen, row, x + 1, " " * (box_width - 2), self._color(1))
        self._draw_border(screen, x, y, box_width, box_height, "PAWNIX · QUICK GUIDE")
        sections = (
            (("PLAY", (
                ("Click / drag", "Move a piece"),
                ("Castle", "Click king, then its two-square destination"),
                ("Right-click", "Circle a square"),
                ("Right-drag", "Draw an arrow"),
                ("Premove", "Choose a piece and destination while waiting"),
                ("Type + Enter", "Submit SAN or UCI move"),
                ("Q / R / B / N", "Choose a promotion piece"),
                ("u / y", "Undo / redo a local move"),
                ("n / p", "Restart / pause a local game"),
                ("o / A", "Offer / accept a draw"),
                ("D", "Claim a threefold/fifty-move draw"),
                ("x / i / l", "Export PGN / import / resume"),
                ("Esc", "Clear selection or input"),
                ("[RESIGN S]", "Resign the game"),
                ("← / →", "Browse move history"),
            )), ("DISPLAY", (
                ("t / T", "Cycle themes forward / back"),
                ("Theme button", "Choose and save a preset theme"),
                ("- / =", "Resize the board"),
                ("v", "Move controls to other side"),
                ("r / Rain", "Toggle falling chess pieces"),
                ("g / Gaps", "Toggle spaces between board squares"),
                ("c / Pieces", "Cycle art, Unicode, and PNG pieces when supported"),
                ("Coordinates", "File and rank labels are always shown"),
                ("Piece size", "Adapts to the available terminal space"),
                ("? / F1", "Open or close this guide"),
            ))),
            (("WELCOME", (
                ("↑ / ↓", "Choose a control"),
                ("← / →", "Change option / AI level"),
                ("Enter", "Select or start game"),
                ("Lichess", "Sign in for online play; local is guest"),
                ("Challenge", "Enter opponent username"),
                ("A / X", "Accept / decline an incoming challenge"),
            )), ("SESSION", (
                ("b, then b / Enter", "Confirm return to welcome"),
                ("q", "Confirm forfeit and exit a match"),
                ("Mouse", "Click buttons and board squares"),
                ("Local play", "Works without signing in"),
            )))
        )

        def section_lines(
            title: str, items: tuple[tuple[str, str], ...], inner_width: int,
        ) -> list[tuple[str, bool]]:
            result = [(title, True)]
            key_width = min(12, max(7, inner_width // 3))
            for key, description in items:
                available = max(8, inner_width - key_width - 1)
                wrapped = textwrap.wrap(description, available, break_long_words=True) or [""]
                result.append((f"{key:<{key_width}} {wrapped[0]}", False))
                result.extend((" " * (key_width + 1) + part, False) for part in wrapped[1:])
            return result

        content_top = y + 2
        if box_width >= 70:
            column_width = (box_width - 7) // 2
            columns = (
                (sections[0][0], sections[1][0]),
                (sections[0][1], sections[1][1]),
            )
            for row, column_sections in enumerate(columns):
                col_x = x + 2 + row * (column_width + 3)
                lines = []
                for section in column_sections:
                    lines.extend(section_lines(section[0], section[1], column_width))
                    lines.append(("", False))
                for line_index, (line, heading) in enumerate(lines[:box_height - 5]):
                    self._addstr(
                        screen, content_top + line_index, col_x, line[:column_width],
                        self._color(1, curses.A_BOLD if heading else 0),
                    )
            divider_x = x + box_width // 2
            for divider_y in range(content_top, y + box_height - 2):
                self._addstr(screen, divider_y, divider_x, "│", self._color(1, curses.A_DIM))
        else:
            lines = []
            for column_sections in sections:
                for section in column_sections:
                    lines.extend(section_lines(section[0], section[1], box_width - 4))
                lines.append(("", False))
            for line_index, (line, heading) in enumerate(lines[:box_height - 5]):
                self._addstr(
                    screen, content_top + line_index, x + 2, line[:box_width - 4],
                    self._color(1, curses.A_BOLD if heading else 0),
                )
        close_hint = "Esc · ? · F1 · Enter closes"
        self._addstr(
            screen, y + box_height - 3,
            x + max(2, (box_width - self._display_width(close_hint)) // 2),
            close_hint, self._color(1, curses.A_DIM),
        )

    def _draw_exit_confirm_modal(self, screen: "curses._CursesWindow") -> None:
        height, width = screen.getmaxyx()
        box_width = min(58, width - 4)
        box_height = min(11, height - 2)
        if box_width < 24 or box_height < 7:
            self._addstr(
                screen, max(0, height // 2), 1,
                "Q / Enter: forfeit and exit · Esc: stay", self._color(1, curses.A_BOLD),
            )
            return
        x, y = (width - box_width) // 2, (height - box_height) // 2
        for row in range(y + 1, y + box_height - 1):
            self._addstr(screen, row, x + 1, " " * (box_width - 2), self._color(1))
        self._draw_border(screen, x, y, box_width, box_height, "FORFEIT AND EXIT?")
        detail = "Leaving now will forfeit this match."
        self._addstr(
            screen, y + 3, x + max(2, (box_width - self._display_width(detail)) // 2),
            detail, self._color(1),
        )
        exit_label, stay_label = "[ EXIT ]", "[ KEEP PLAYING ]"
        gap = 3
        cluster = self._display_width(exit_label) + gap + self._display_width(stay_label)
        exit_x = x + (box_width - cluster) // 2
        stay_x = exit_x + self._display_width(exit_label) + gap
        button_y = y + 5
        for index, (label, button_x) in enumerate(((exit_label, exit_x), (stay_label, stay_x))):
            style = curses.A_BOLD | (curses.A_REVERSE if index == 0 else 0)
            self._addstr(screen, button_y, button_x, label, self._color(1, style))
        self.exit_confirm_bounds = (
            (button_y, exit_x, exit_x + self._display_width(exit_label) - 1),
            (button_y, stay_x, stay_x + self._display_width(stay_label) - 1),
        )
        hint = "Q again / Enter: exit · Esc: keep playing"
        self._addstr(
            screen, y + box_height - 2,
            x + max(2, (box_width - self._display_width(hint)) // 2),
            hint, self._color(1, curses.A_DIM),
        )

    def _draw_back_confirm_modal(self, screen: "curses._CursesWindow") -> None:
        height, width = screen.getmaxyx()
        box_width = min(58, width - 4)
        box_height = min(11, height - 2)
        if box_width < 24 or box_height < 7:
            self._addstr(
                screen, max(0, height // 2), 1,
                "B again / Enter: return to welcome · Esc: stay", self._color(1, curses.A_BOLD),
            )
            return
        x, y = (width - box_width) // 2, (height - box_height) // 2
        for row in range(y + 1, y + box_height - 1):
            self._addstr(screen, row, x + 1, " " * (box_width - 2), self._color(1))
        self._draw_border(screen, x, y, box_width, box_height, "RETURN TO WELCOME?")
        detail = "Leaving now may forfeit this match."
        self._addstr(
            screen, y + 3, x + max(2, (box_width - self._display_width(detail)) // 2),
            detail, self._color(1),
        )
        back_label, stay_label = "[ RETURN ]", "[ KEEP PLAYING ]"
        gap = 3
        cluster = self._display_width(back_label) + gap + self._display_width(stay_label)
        back_x = x + (box_width - cluster) // 2
        stay_x = back_x + self._display_width(back_label) + gap
        button_y = y + 5
        for index, (label, button_x) in enumerate(((back_label, back_x), (stay_label, stay_x))):
            style = curses.A_BOLD | (curses.A_REVERSE if index == 0 else 0)
            self._addstr(screen, button_y, button_x, label, self._color(1, style))
        self.back_confirm_bounds = (
            (button_y, back_x, back_x + self._display_width(back_label) - 1),
            (button_y, stay_x, stay_x + self._display_width(stay_label) - 1),
        )
        hint = "B again / Enter: return · Esc: stay"
        self._addstr(
            screen, y + box_height - 2,
            x + max(2, (box_width - self._display_width(hint)) // 2),
            hint, self._color(1, curses.A_DIM),
        )

    def _draw_signout_confirm_modal(self, screen: "curses._CursesWindow") -> None:
        height, width = screen.getmaxyx()
        box_width = min(54, width - 4)
        box_height = min(9, height - 2)
        if box_width < 24 or box_height < 7:
            self._addstr(
                screen, max(0, height // 2), 1,
                "Sign out? ← / → choose · Enter confirms · Esc cancels",
                self._lobby_color(curses.A_BOLD),
            )
            return
        x, y = (width - box_width) // 2, (height - box_height) // 2
        for row in range(y + 1, y + box_height - 1):
            self._addstr(screen, row, x + 1, " " * (box_width - 2), self._color(1))
        self._draw_border(screen, x, y, box_width, box_height, "SIGN OUT?")
        detail = "Sign out of your Lichess account?"
        self._addstr(
            screen, y + 3, x + max(2, (box_width - self._display_width(detail)) // 2),
            detail, self._lobby_color(),
        )
        confirm_label, cancel_label = "[ SIGN OUT ]", "[ CANCEL ]"
        gap = 3
        cluster = self._display_width(confirm_label) + gap + self._display_width(cancel_label)
        confirm_x = x + (box_width - cluster) // 2
        cancel_x = confirm_x + self._display_width(confirm_label) + gap
        button_y = y + 5
        buttons = ((confirm_label, confirm_x), (cancel_label, cancel_x))
        for index, (label, button_x) in enumerate(buttons):
            style = curses.A_BOLD | (curses.A_REVERSE if index == self.signout_choice else 0)
            self._addstr(screen, button_y, button_x, label, self._lobby_color(style))
        self.signout_button_bounds = (
            (button_y, confirm_x, confirm_x + self._display_width(confirm_label) - 1),
            (button_y, cancel_x, cancel_x + self._display_width(cancel_label) - 1),
        )
        hint = "← / → choose · Enter confirm · Esc cancel"
        self._addstr(
            screen, y + box_height - 2,
            x + max(2, (box_width - self._display_width(hint)) // 2),
            hint, self._lobby_color(curses.A_DIM),
        )

    def _draw_result_modal(
        self, screen: "curses._CursesWindow", game: GameSession, result_label: str,
    ) -> None:
        height, width = screen.getmaxyx()
        self.result_button_bounds = None
        box_width = min(54, width - 6)
        box_height = min(12, height - 4)
        if box_width < 30 or box_height < 9:
            return
        x, y = (width - box_width) // 2, (height - box_height) // 2
        for row in range(y + 1, y + box_height - 1):
            self._addstr(screen, row, x + 1, " " * (box_width - 2), self._color(1))
        self._draw_border(screen, x, y, box_width, box_height, "GAME OVER")
        result_x = x + max(2, (box_width - self._display_width(result_label)) // 2)
        self._addstr(screen, y + 3, result_x, result_label, self._color(1, curses.A_BOLD))
        detail = "Exit to setup or play again."
        detail_x = x + max(2, (box_width - self._display_width(detail)) // 2)
        self._addstr(screen, y + 5, detail_x, detail, self._color(1))
        exit_label, redo_label = "[ EXIT ]", "[ REDO ]"
        gap = 5
        cluster = self._display_width(exit_label) + gap + self._display_width(redo_label)
        exit_x = x + (box_width - cluster) // 2
        redo_x = exit_x + self._display_width(exit_label) + gap
        button_y = y + 7
        for index, (label, button_x) in enumerate(((exit_label, exit_x), (redo_label, redo_x))):
            style = curses.A_BOLD | (curses.A_REVERSE if self.result_choice == index else 0)
            self._addstr(screen, button_y, button_x, label, self._color(1, style))
        self.result_button_bounds = (
            (button_y, exit_x, exit_x + self._display_width(exit_label) - 1),
            (button_y, redo_x, redo_x + self._display_width(redo_label) - 1),
        )
        hint = "← / → select · Enter confirm · Esc exit"
        hint_x = x + max(2, (box_width - self._display_width(hint)) // 2)
        self._addstr(screen, y + box_height - 2, hint_x, hint, self._color(1, curses.A_DIM))
