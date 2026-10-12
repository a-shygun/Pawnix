"""Welcome-screen layout and rendering for Pawnix."""

from __future__ import annotations

import curses
import textwrap
import time

import chess


_PAWNIX_LOGO = (
    "▄▄▄▄▄▄▄ ▄▄▄▄▄▄▄ ▄▄▄ ▄▄▄ ▄▄▄ ▄▄▄ ▄▄▄▄▄ ▄▄▄ ▄▄▄",
    "█\u00a0▄▄▄\u00a0█ █\u00a0▄▄▄\u00a0█ █\u00a0█▄█\u00a0█ █\u00a0▀██\u00a0█ █▄\u00a0▄█ █▄▀█▀▄█",
    "█\u00a0▄▄▄▄█ █\u00a0▄▄▄\u00a0█ █\u00a0▀▄▀\u00a0█ █\u00a0█▄▀\u00a0█ ▄█\u00a0█▄ ▄█▀▄▀█▄",
    "█▄█     █▄█ █▄█ █▄█▀█▄█ █▄█▀█▄█ █▄▄▄█ █▄█▀█▄█",
)


class LobbyRendererMixin:
    """Render the welcome lobby using BoardRenderer drawing helpers."""

    def draw_lobby(
        self, screen: "curses._CursesWindow", modes: tuple[str, ...], mode_index: int,
        time_controls: tuple[tuple[str, int, int], ...], time_index: int,
        challenge_username: str, account_label: str, focus: int, status: str,
        ai_level: int = 4, version: str = "", ai_color: chess.Color = chess.WHITE,
        account_name: str = "",
    ) -> None:
        """Draw centered setup panels over an animated chess-piece rain."""
        try:
            screen.erase()
        except curses.error:
            pass
        self._lobby_frame = int(time.monotonic() * 10)
        height, width = screen.getmaxyx()
        self.layout = None
        self.welcome_github_bounds = None
        self.signout_button_bounds = None

        frame_x, frame_y = 1, 1
        frame_width, frame_height = width - 2, height - 2
        content_x, content_width = frame_x + 3, frame_width - 6
        two_column_layout = height < 50
        box_width = max(3, min(42, content_width - 4))
        box_x = content_x + max(0, (content_width - box_width) // 2)
        self._draw_piece_rain(screen, content_x, frame_y + 1, content_width,
                              max(0, frame_y + frame_height - 1 - (frame_y + 1)))
        # Draw the frame over the moving glyphs so its outline stays fixed.
        self._draw_border(screen, frame_x, frame_y, frame_width, frame_height, "")

        logo_y = frame_y + 2
        logo_width = max(self._display_width(line) for line in _PAWNIX_LOGO)
        logo_x = frame_x + max(1, (frame_width - logo_width) // 2)
        for row, line in enumerate(_PAWNIX_LOGO):
            self._addstr(screen, logo_y + row, logo_x, line.ljust(logo_width), self._lobby_color(curses.A_BOLD))
        gap, boxes = 1, []
        mode_h = max(8, len(modes) + 4)
        challenge_h = 6 if mode_index == 3 else 0
        ai_box_h = 7 if mode_index == 1 else 0
        time_columns = 2 if box_width >= 38 else 1
        time_row_count = (len(time_controls) + time_columns - 1) // time_columns
        time_h = time_row_count + 4
        actions_width = min(content_width, max(box_width, 39))
        if two_column_layout:
            left_column_width = max(3, (content_width - 2) // 2)
            right_column_width = max(3, content_width - 2 - left_column_width)
            actions_width = min(42, max(3, right_column_width - 2))
        status_lines = textwrap.wrap(
            status,
            width=max(1, actions_width - 4),
            break_long_words=True,
            break_on_hyphens=False,
        ) if status else []
        action_height = 7 + len(status_lines)
        available_top = logo_y + len(_PAWNIX_LOGO) + 3
        if two_column_layout:
            column_gap = 2
            left_column_width = max(3, (content_width - column_gap) // 2)
            right_column_width = max(3, content_width - column_gap - left_column_width)
            left_box_width = min(42, max(3, left_column_width - 2))
            right_box_width = min(42, max(3, right_column_width - 2))
            pair_width = left_box_width + column_gap + right_box_width
            pair_x = content_x + max(0, (content_width - pair_width) // 2)
            left_box_x = pair_x
            right_box_x = pair_x + left_box_width + column_gap
            time_box_width = right_box_width
            time_columns = 2 if time_box_width >= 38 else 1
            time_row_count = (len(time_controls) + time_columns - 1) // time_columns
            time_h = time_row_count + 4
            actions_x, actions_width = right_box_x, right_box_width
            top_y = available_top
            mode_x, mode_y, mode_width = left_box_x, top_y, left_box_width
            ai_box_x, ai_box_y, ai_box_width = left_box_x, mode_y + mode_h + gap, left_box_width
            challenge_box_y = ai_box_y + ai_box_h + gap if ai_box_h else mode_y + mode_h + gap
            time_box_x, time_box_y = right_box_x, top_y
            actions_y = time_box_y + time_h + gap
        else:
            mode_x, mode_y, mode_width = box_x, available_top, box_width
            ai_box_x, ai_box_y, ai_box_width = box_x, mode_y + mode_h + gap, box_width
            challenge_box_y = ai_box_y + ai_box_h + gap if ai_box_h else mode_y + mode_h + gap
            time_box_x, time_box_y = box_x, challenge_box_y + (challenge_h + gap if challenge_h else 0)
            actions_width = min(content_width, max(box_width, 39))
            actions_x = content_x + max(0, (content_width - actions_width) // 2)
            actions_y = time_box_y + time_h + gap

        self._lobby_box(screen, mode_x, mode_y, mode_width, mode_h, "MATCH TYPE")
        boxes.append(("mode", mode_x, mode_y, mode_width, mode_h))
        mode_rows = []
        ai_level_bounds = None
        ai_color_bounds = None
        mode_option_width = max(
            self._display_width(f" {('●' if index == mode_index else '○')} {mode} ")
            for index, mode in enumerate(modes)
        )
        mode_option_x = mode_x + max(2, (mode_width - mode_option_width) // 2)
        for index, mode in enumerate(modes):
            row_y = mode_y + 2 + index
            label = " " + ("● " if index == mode_index else "○ ") + mode + " "
            mode_rows.append((row_y, index, mode_x + 1, mode_x + mode_width - 2))
            style = curses.A_REVERSE if focus == 0 and index == mode_index else 0
            self._addstr(screen, row_y, mode_option_x, label, self._lobby_color(style))
        if ai_box_h:
            self._lobby_box(screen, ai_box_x, ai_box_y, ai_box_width, ai_box_h, "LICHESS AI")
            boxes.append(("ai_settings", ai_box_x, ai_box_y, ai_box_width, ai_box_h))
            ai_row = ai_box_y + 2
            ai_prefix, ai_minus, ai_value, ai_plus = "", "[-]", f"Level {ai_level}", "[+]"
            ai_line = f"{ai_minus}  {ai_value}  {ai_plus}"
            ai_x = ai_box_x + max(2, (ai_box_width - self._display_width(ai_line)) // 2)
            minus_x = ai_x + self._display_width(ai_prefix)
            value_x = minus_x + self._display_width(ai_minus) + 2
            plus_x = value_x + self._display_width(ai_value) + 2
            control_style = curses.A_BOLD | curses.A_UNDERLINE | (curses.A_REVERSE if focus == 8 else 0)
            self._addstr(screen, ai_row, minus_x, ai_minus, self._lobby_color(control_style))
            self._addstr(screen, ai_row, value_x, ai_value, self._lobby_color(curses.A_BOLD))
            self._addstr(screen, ai_row, plus_x, ai_plus, self._lobby_color(control_style))
            ai_level_bounds = (
                ai_row,
                minus_x, minus_x + self._display_width(ai_minus) - 1,
                plus_x, plus_x + self._display_width(ai_plus) - 1,
            )
            color_row = ai_box_y + 4
            white_label = "[ ● White ]" if ai_color == chess.WHITE else "[ ○ White ]"
            black_label = "[ ● Black ]" if ai_color == chess.BLACK else "[ ○ Black ]"
            color_gap = 2
            combined_width = self._display_width(white_label) + color_gap + self._display_width(black_label)
            color_x = ai_box_x + max(2, (ai_box_width - combined_width) // 2)
            white_x = color_x
            black_x = white_x + self._display_width(white_label) + color_gap
            white_style = curses.A_REVERSE if focus == 9 and ai_color == chess.WHITE else 0
            black_style = curses.A_REVERSE if focus == 9 and ai_color == chess.BLACK else 0
            self._addstr(screen, color_row, white_x, white_label, self._lobby_color(white_style))
            self._addstr(screen, color_row, black_x, black_label, self._lobby_color(black_style))
            ai_color_bounds = (
                color_row,
                (white_x, white_x + self._display_width(white_label) - 1),
                (black_x, black_x + self._display_width(black_label) - 1),
            )

        challenge_bounds = None
        if mode_index == 3:
            self._lobby_box(screen, left_box_x if two_column_layout else box_x,
                            challenge_box_y, left_box_width if two_column_layout else box_width,
                            challenge_h, "CHALLENGE")
            challenge_x = left_box_x if two_column_layout else box_x
            challenge_width = left_box_width if two_column_layout else box_width
            boxes.append(("challenge", challenge_x, challenge_box_y, challenge_width, challenge_h))
            prompt = "Opponent username"
            prompt_x = challenge_x + max(2, (challenge_width - self._display_width(prompt)) // 2)
            self._addstr(screen, challenge_box_y + 2, prompt_x, prompt, self._lobby_color())
            name_y = challenge_box_y + 3
            name_label = f"{challenge_username[:28]}_"
            name_x = challenge_x + max(2, (challenge_width - self._display_width(name_label)) // 2)
            self._addstr(screen, name_y, name_x, name_label,
                         self._lobby_color(curses.A_REVERSE if focus == 2 else 0))
            challenge_bounds = (name_y, challenge_x + 1, challenge_x + challenge_width - 2)

        time_title = "LICHESS · RAPID / CLASSICAL" if mode_index == 2 else "TIME CONTROL"
        self._lobby_box(screen, time_box_x, time_box_y, time_box_width if two_column_layout else box_width,
                        time_h, time_title)
        boxes.append(("time", time_box_x, time_box_y, time_box_width if two_column_layout else box_width, time_h))
        time_rows = []
        active_time_width = time_box_width if two_column_layout else box_width
        col_width = (active_time_width - 4) // time_columns
        column_labels = [[], []]
        for index, (label, _, _) in enumerate(time_controls):
            column_labels[index // time_row_count].append(
                " " + ("● " if index == time_index else "○ ")
                + label.replace(" · ", " ").replace("Classical", "Classic") + " "
            )
        column_offsets = [
            max(0, (col_width - max((self._display_width(option) for option in labels), default=0)) // 2)
            for labels in column_labels
        ]
        for index, (label, _, _) in enumerate(time_controls):
            col, row = divmod(index, time_row_count)
            row_y, option_x = time_box_y + 2 + row, time_box_x + 2 + col * col_width
            time_rows.append((row_y, index, option_x, option_x + col_width - 2))
            selected = index == time_index
            style = curses.A_REVERSE if selected and focus == 1 else 0
            display_label = label.replace(" · ", " ").replace("Classical", "Classic")
            option = " " + ("● " if selected else "○ ") + display_label + " "
            self._addstr(screen, row_y, option_x + column_offsets[col], option, self._lobby_color(style))

        guide_bounds = None
        guide_label = "[ ? ]"
        start_label = "[ START GAME ]"
        self._lobby_box(screen, actions_x, actions_y, actions_width, action_height, "ACTIONS")
        boxes.append(("actions", actions_x, actions_y, actions_width, action_height))
        guide_row = actions_y + 2
        action_gap = 3
        action_cluster_width = self._display_width(guide_label) + action_gap + self._display_width(start_label)
        action_cluster_x = actions_x + max(2, (actions_width - action_cluster_width) // 2)
        guide_x = action_cluster_x
        self._addstr(screen, guide_row, guide_x, guide_label,
                     self._lobby_color(curses.A_REVERSE | curses.A_BOLD if focus == 7 else curses.A_BOLD))
        guide_bounds = (guide_row, guide_x, guide_x + self._display_width(guide_label) - 1)
        start_row = guide_row
        start_x = guide_x + self._display_width(guide_label) + action_gap
        start_style = curses.A_REVERSE | curses.A_BOLD if focus == 6 else curses.A_BOLD
        self._addstr(screen, start_row, start_x, start_label, self._lobby_color(start_style))
        account_row = actions_y + 3
        account_x = actions_x + max(2, (actions_width - self._display_width(account_label)) // 2)
        is_signout = "SIGN OUT" in account_label
        account_style = curses.A_BOLD | (curses.A_UNDERLINE if focus == 4 and is_signout else 0)
        account_attr = (self._color(7, account_style) if is_signout
                        else self._lobby_color(account_style))
        self._addstr(screen, account_row, account_x, account_label, account_attr)
        account_hint = self._fit_line(
            f"Online: {account_name or 'Lichess'} · Local: guest", actions_width - 4,
        )
        hint_x = actions_x + max(2, (actions_width - self._display_width(account_hint)) // 2)
        hint_row = actions_y + 4
        self._addstr(screen, hint_row, hint_x, account_hint, self._lobby_color())
        for row, status_text in enumerate(status_lines):
            status_x = actions_x + max(2, (actions_width - self._display_width(status_text)) // 2)
            self._addstr(screen, actions_y + 5 + row, status_x, status_text,
                         self._lobby_color(curses.A_BOLD))

        welcome_prefix = f"Pawnix v{version} · " if version else "Pawnix · "
        github_label = "GitHub"
        welcome_link = welcome_prefix + github_label
        last_box_bottom = max((box_y + box_height - 1 for _, _, box_y, _, box_height in boxes),
                              default=actions_y + action_height - 1)
        link_y = last_box_bottom + 1
        link_x = frame_x + max(2, (frame_width - self._display_width(welcome_link)) // 2)
        github_x = link_x + self._display_width(welcome_prefix)
        self._addstr(screen, link_y, link_x, welcome_prefix, self._lobby_color())
        self._addstr(screen, link_y, github_x, github_label,
                     self._lobby_color(curses.A_UNDERLINE))
        self.welcome_github_bounds = (
            link_y, github_x, github_x + self._display_width(github_label) - 1,
        )
        self._lobby_geometry = {
            "boxes": tuple(boxes), "mode_rows": tuple(mode_rows), "time_rows": tuple(time_rows),
            "ai_level": ai_level_bounds,
            "ai_color": ai_color_bounds,
            "account": (account_row, account_x, account_x + self._display_width(account_label) - 1),
            "challenge": challenge_bounds,
            "guide": guide_bounds,
            "start": (start_row, start_x, start_x + self._display_width(start_label)),
        }
        if self.help_modal_open:
            self._draw_help_modal(screen, version)
        if self.signout_confirm_open:
            self._draw_signout_confirm_modal(screen)
        self._safe_refresh(screen)
