"""Responsive curses renderer for the chessboard and its companion panel."""

from __future__ import annotations

import curses
import colorsys
import time
import unicodedata
from dataclasses import dataclass

import chess

from pawnix.game.session import GameSession
from pawnix.ui.lobby_renderer import LobbyRendererMixin
from pawnix.ui.modals import ModalRendererMixin
from pawnix.ui.themes import THEMES, select_theme


_PIECE_GLYPHS = {
    (chess.KING, "compact"): ("▗▂╋▂▖", " ▀█▀ ", " ▀▀▀ "),
    (chess.QUEEN, "compact"): (" ▆▄▆ ", " ▗█▖ ", " ▀▀▀ "),
    (chess.ROOK, "compact"): (" ▅ ▅ ", " ███ ", "▝▀▀▀▘"),
    (chess.BISHOP, "compact"): (" ▆▖▆ ", " ▐▙▌ ", " ▀▀▀ "),
    (chess.KNIGHT, "compact"): (" ▄▟▟▖", " ▂█▛▘", "▝▀▀▀▘"),
    (chess.PAWN, "compact"): ("  ▂  ", " ▆█▆ ", " ▔▔▔ "),
    (chess.KING, "extended"): (" ▂╋▂ ", "▜███▛", " ▜█▛ ", "▝▀▀▀▘"),
    (chess.QUEEN, "extended"): ("▂ ▄ ▂", "▜▙█▟▛", " ▜█▛ ", "▝▀▀▀▘"),
    (chess.ROOK, "extended"): ("▄ ▄ ▄", "█████", " ███ ", "▀▀▀▀▀"),
    (chess.BISHOP, "extended"): (" ▄▁▗ ", " ██▟ ", " ▟█▙ ", "▝▀▀▀▘"),
    (chess.KNIGHT, "extended"): ("  ▖▗ ", "▗▇▟█▌", " ▟█▛ ", "▝▀▀▀▘"),
    (chess.PAWN, "extended"): ("     ", " ▝█▘ ", " ▟█▙ ", " ▔▔▔ "),
    (chess.KING, "large"): ("  ▂▃╋▃▂  ", " ▐█████▋ ", "  ▜███▛  ", "   ▟█▙   ", "  ▀▀▀▀▀  "),
    (chess.QUEEN, "large"): ("▗  ▂  ▖", "▐▙▟█▙▟▌", " ▜███▛ ", " ▗███▖ ", "▝▀▀▀▀▀▘"),
    (chess.ROOK, "large"): ("▗▄ ▃ ▄▖", "▐█▄█▄█▌", "▝▜███▛▘", " ▟███▙ ", "▝▀▀▀▀▀▘"),
    (chess.BISHOP, "large"): ("▗▅  ▖", "██▍ █", "███▍█", "▝███▘", "▀▀▀▀▀"),
    (chess.KNIGHT, "large"): ("  ▅ ▅", " ▟▛███▖", "▝▀▜███▊", " ▗███▛ ", " ▀▀▀▀▀ "),
    (chess.PAWN, "large"): (" ▄▇▄", " ▜█▛", "▄███▄", "▔▔▔▔▔"),
}


@dataclass(frozen=True)
class BoardLayout:
    board_x: int
    board_y: int
    board_width: int
    board_height: int
    panel_x: int
    panel_width: int
    cell_width: int
    cell_height: int
    horizontal_gap: int = 2
    vertical_gap: int = 1
    horizontal_padding: int = 2
    vertical_padding: int = 1
    piece_size: str = "large"


class BoardRenderer(LobbyRendererMixin, ModalRendererMixin):
    """Draw themed squares and centered pieces in a bordered, responsive layout."""

    def __init__(self, theme: str = "ocean") -> None:
        self.theme = select_theme(theme)
        self.theme_index = THEMES.index(self.theme)
        self.layout: BoardLayout | None = None
        self.theme_menu_open = False
        self.theme_menu_index = self.theme_index
        self.theme_commit_requested = False
        self._theme_menu_bounds: tuple[int, int, int] | None = None
        self.legal_targets: set[chess.Square] = set()
        self.circled_squares: set[chess.Square] = set()
        self.arrows: set[tuple[chess.Square, chess.Square]] = set()
        self._lobby_geometry: dict[str, object] = {}
        self.back_button_bounds: tuple[int, int, int] | None = None
        self.move_nav_bounds: tuple[int, tuple[int, int], tuple[int, int]] | None = None
        self.help_button_bounds: tuple[int, int, int] | None = None
        self.side_button_bounds: tuple[int, int, int] | None = None
        self.theme_button_bounds: tuple[int, int, int] | None = None
        self.rain_button_bounds: tuple[int, int, int] | None = None
        self.gaps_button_bounds: tuple[int, int, int] | None = None
        self.coordinates_button_bounds: tuple[int, int, int] | None = None
        self.surrender_button_bounds: tuple[int, int, int] | None = None
        self.result_modal_open = False
        self.result_button_bounds: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
        self.result_choice = 0
        self.back_confirm_open = False
        self.back_confirm_bounds: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
        self.exit_confirm_open = False
        self.exit_confirm_bounds: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
        self.signout_confirm_open = False
        self.signout_choice = 0
        self.signout_button_bounds: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
        self.game_theme_rows: tuple[tuple[int, int, int, int], ...] = ()
        self.help_modal_open = False
        self.welcome_github_bounds: tuple[int, int, int] | None = None
        self.panel_on_left = True
        self.orientation = chess.WHITE
        self._lobby_frame = 0
        self.color_enabled = False
        self.rich_colors = False
        self.piece_pairs = False
        self.lobby_background_pair = 0
        self.lobby_theme_pairs = False
        self.rain_color_pairs = False
        self.rain_enabled = True
        self.board_gaps_enabled = False
        self.coordinates_enabled = True
        self.legal_pair = 4
        self.legal_piece_pairs = False
        self.last_move_pair = 4
        self.last_move_piece_pairs = False
        self.last_move_squares: set[chess.Square] = set()
        self.check_square: chess.Square | None = None
        # Start with large piece sprites.
        self.zoom = 5

    def initialize(self) -> None:
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            curses.use_default_colors()
            self.color_enabled = True
            self.rich_colors = curses.COLORS >= 256
            self.piece_pairs = curses.COLOR_PAIRS >= 14
            self._initialize_pairs()
        except curses.error:
            self.color_enabled = False
            self.rich_colors = False

    def select_theme(self, index: int | None = None) -> None:
        """Commit the currently previewed theme as the active selection."""
        if index is not None:
            self.theme_index = index % len(THEMES)
            self.theme_menu_index = self.theme_index
        self.theme = THEMES[self.theme_menu_index]
        self.theme_index = self.theme_menu_index
        self.theme_menu_open = False
        self._initialize_pairs()

    def open_theme_menu(self) -> None:
        self.theme_menu_open = True
        self.theme_menu_index = self.theme_index
        self.preview_theme(self.theme_menu_index)

    def preview_theme(self, index: int) -> None:
        self.theme_menu_index = index % len(THEMES)
        self.theme = THEMES[self.theme_menu_index]
        self._initialize_pairs()

    def cancel_theme_preview(self) -> None:
        self.theme = THEMES[self.theme_index]
        self.theme_menu_index = self.theme_index
        self.theme_menu_open = False
        self._initialize_pairs()

    def toggle_theme_menu(self) -> None:
        if self.theme_menu_open:
            self.cancel_theme_preview()
        else:
            self.open_theme_menu()

    def handle_theme_click(self, x: int, y: int) -> bool:
        """Handle clicks on the theme selector; return whether it consumed the click."""
        self.theme_commit_requested = False
        if self.theme_menu_open:
            for row, index, left, right in self.game_theme_rows:
                if y == row and left <= x <= right:
                    if index == self.theme_menu_index:
                        self.select_theme()
                        self.theme_commit_requested = True
                    else:
                        self.preview_theme(index)
                    return True
            self.cancel_theme_preview()
            return False
        return False

    def mark_right_click(self, start: chess.Square, destination: chess.Square) -> None:
        """Toggle a square ring or a directional board annotation."""
        if start == destination:
            if start in self.circled_squares:
                self.circled_squares.remove(start)
            else:
                self.circled_squares.add(start)
            return
        arrow = (start, destination)
        reverse = (destination, start)
        if arrow in self.arrows:
            self.arrows.remove(arrow)
        elif reverse in self.arrows:
            self.arrows.remove(reverse)
        else:
            self.arrows.add(arrow)

    def _initialize_pairs(self) -> None:
        if not self.color_enabled:
            return
        theme = self.theme
        if self.rich_colors:
            light, dark, selected = theme.light, theme.dark, theme.selected
            white, black = theme.white, theme.black
        else:
            light, dark, selected = theme.fallback_light, theme.fallback_dark, theme.fallback_selected
            white, black = theme.fallback_white, theme.fallback_black
        try:
            curses.init_pair(1, curses.COLOR_WHITE, -1)
            curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)
            curses.init_pair(2, light, light)
            curses.init_pair(3, dark, dark)
            curses.init_pair(4, selected, selected)
            if curses.COLOR_PAIRS >= 7:
                curses.init_pair(5, curses.COLOR_YELLOW, -1)
            if curses.COLOR_PAIRS >= 8:
                curses.init_pair(7, curses.COLOR_RED, -1)
            if self.piece_pairs:
                # Keep white pieces visibly gray on the brightest light squares.
                curses.init_pair(8, white, light)
                curses.init_pair(9, white, dark)
                curses.init_pair(10, black, light)
                curses.init_pair(11, black, dark)
                curses.init_pair(12, white, selected)
                curses.init_pair(13, black, selected)
            self.legal_pair = 4
            self.legal_piece_pairs = False
            if curses.COLOR_PAIRS >= 51:
                legal_color = self._complementary_theme_color(light, dark, selected)
                curses.init_pair(48, legal_color, legal_color)
                curses.init_pair(49, white, legal_color)
                curses.init_pair(50, black, legal_color)
                self.legal_pair = 48
                self.legal_piece_pairs = True
            self.last_move_pair = 4
            self.last_move_piece_pairs = False
            if self.rich_colors and curses.COLOR_PAIRS >= 54:
                muted_color = self._muted_theme_color(selected)
                curses.init_pair(51, muted_color, muted_color)
                curses.init_pair(52, white, muted_color)
                curses.init_pair(53, black, muted_color)
                self.last_move_pair = 51
                self.last_move_piece_pairs = True
            if curses.COLOR_PAIRS >= 18:
                if self.rich_colors:
                    rain_shades = (232, 240, 248, 255)
                else:
                    rain_shades = (curses.COLOR_WHITE,) * 4
                for index, shade in enumerate(rain_shades):
                    curses.init_pair(14 + index, shade, -1)
                self.rain_color_pairs = True
            else:
                self.rain_color_pairs = False
            self.lobby_background_pair = 1
            self.lobby_theme_pairs = curses.COLOR_PAIRS >= 18 + len(THEMES) * 2
            if self.lobby_theme_pairs:
                # Two unique board-color swatches per theme keep the full palette
                # visible in the welcome screen at the same time.
                for theme_index, palette in enumerate(THEMES):
                    if self.rich_colors:
                        swatch_light, swatch_dark = palette.light, palette.dark
                    else:
                        swatch_light, swatch_dark = palette.fallback_light, palette.fallback_dark
                    first_pair = 18 + theme_index * 2
                    curses.init_pair(first_pair, curses.COLOR_BLACK, swatch_light)
                    curses.init_pair(first_pair + 1, curses.COLOR_WHITE, swatch_dark)
        except curses.error:
            self.color_enabled = False
            self.rich_colors = False

    @staticmethod
    def _complementary_theme_color(light: int, dark: int, accent: int) -> int:
        """Choose a saturated xterm color opposite the board's average hue."""
        try:
            light_rgb = tuple(component / 1000 for component in curses.color_content(light))
            dark_rgb = tuple(component / 1000 for component in curses.color_content(dark))
            average = tuple((light_rgb[index] + dark_rgb[index]) / 2 for index in range(3))
            hue, luminance, saturation = colorsys.rgb_to_hls(*average)
            if saturation < 0.16:
                return accent
            target = colorsys.hls_to_rgb(
                (hue + 0.5) % 1, min(0.56, max(0.38, luminance)), max(0.62, saturation),
            )
            candidates = (
                range(16, min(curses.COLORS, 256)) if curses.COLORS >= 16
                else range(1, max(1, curses.COLORS - 1))
            )
            return min(
                candidates,
                key=lambda color: sum(
                    (curses.color_content(color)[index] / 1000 - target[index]) ** 2
                    for index in range(3)
                ),
            )
        except (curses.error, ValueError):
            return accent

    @staticmethod
    def _muted_theme_color(accent: int) -> int:
        """Find a low-saturation xterm color derived from the theme accent."""
        try:
            rgb = tuple(component / 1000 for component in curses.color_content(accent))
            hue, lightness, saturation = colorsys.rgb_to_hls(*rgb)
            target = colorsys.hls_to_rgb(hue, min(0.62, max(0.42, lightness)), min(0.34, saturation * 0.4))
            candidates = range(16, min(curses.COLORS, 256))
            return min(
                candidates,
                key=lambda color: sum(
                    (curses.color_content(color)[index] / 1000 - target[index]) ** 2
                    for index in range(3)
                ),
            )
        except (curses.error, ValueError):
            return accent

    def draw(
        self,
        screen: "curses._CursesWindow",
        game: GameSession,
        white_name: str = "White",
        black_name: str = "Black",
        view_ply: int | None = None,
        orientation: chess.Color = chess.WHITE,
        version: str = "",
        result_label: str = "GAME OVER",
        premove_color: chess.Color | None = None,
        premove_move: chess.Move | None = None,
    ) -> None:
        try:
            screen.erase()
        except curses.error:
            # A terminal can resize while a frame is being prepared.
            pass
        self.orientation = orientation
        was_result_modal_open = self.result_modal_open
        self.result_modal_open = False
        self.result_button_bounds = None
        self.exit_confirm_bounds = None
        self.back_confirm_bounds = None
        self._lobby_frame = int(time.monotonic() * 10)
        self.back_button_bounds = None
        self.help_button_bounds = None
        self.side_button_bounds = None
        self.theme_button_bounds = None
        self.surrender_button_bounds = None
        self.gaps_button_bounds = None
        self.coordinates_button_bounds = None
        self.game_theme_rows = ()
        height, width = screen.getmaxyx()
        layout = self._make_layout(height, width)
        self.layout = layout
        if layout is None:
            message = "Terminal too small for a board; enlarge the window."
            self._addstr(screen, max(0, height // 2), max(0, (width - len(message)) // 2), message, 0)
            self._safe_refresh(screen)
            return

        # Keep the side panel centered independently of the board's exact
        # height. With gaps off on a short terminal, the board can shrink to
        # one row per square; tying the panel to board_height then leaves too
        # little room for controls, moves, and navigation. A stable minimum
        # also keeps the gap toggle in the same place as the board reflows.
        panel_height = max(13, layout.board_height - 6)
        panel_y = max(1, (height - panel_height) // 2)
        board_right = layout.board_x + layout.board_width
        panel_right = layout.panel_x + layout.panel_width
        gap_left = min(board_right, panel_right)
        gap_right = max(layout.board_x, layout.panel_x)
        excluded_rain_areas = (
            # Keep animated Unicode sprites a couple of cells away from the
            # board edge as terminal width handling can vary for block glyphs.
            (layout.board_x - 2, layout.board_y - 1,
             layout.board_width + 4, layout.board_height + 2),
            (layout.panel_x, panel_y, layout.panel_width, panel_height),
            (gap_left, 0, max(0, gap_right - gap_left), height),
        )
        self._draw_piece_rain(
            screen,
            2,
            2,
            width - 4,
            height - 4,
            excluded=excluded_rain_areas,
        )
        # Paint borders above the animated background so rain cannot flicker
        # over the frame or board outline.
        self._draw_border(screen, 1, 1, width - 2, height - 2, "")
        self._draw_border(screen, layout.board_x, layout.board_y, layout.board_width, layout.board_height, "BOARD")
        view_board = game.board.copy(stack=True)
        if view_ply is not None:
            while view_board.move_stack and len(view_board.move_stack) > view_ply:
                view_board.pop()
        self.legal_targets = set()
        self.last_move_squares = set()
        self.check_square = view_board.king(view_board.turn) if view_board.is_check() else None
        if view_board.move_stack:
            last_move = view_board.peek()
            self.last_move_squares = {last_move.from_square, last_move.to_square}
        if game.selected is not None and (view_ply is None or view_ply == len(game.moves)):
            if premove_move is not None and game.selected == premove_move.from_square:
                self.legal_targets = {premove_move.to_square}
            elif premove_color is not None and view_board.turn != premove_color:
                piece = view_board.piece_at(game.selected)
                if piece is not None and piece.color == premove_color:
                    premove_board = view_board.copy(stack=False)
                    premove_board.turn = premove_color
                    self.legal_targets = {
                        move.to_square for move in premove_board.pseudo_legal_moves
                        if move.from_square == game.selected
                    }
            else:
                self.legal_targets = {
                    move.to_square for move in view_board.legal_moves
                    if move.from_square == game.selected
                }
        self._draw_squares(screen, layout, game, view_board)
        if self.coordinates_enabled:
            self._draw_coordinates(screen, layout)
        self._draw_annotations(screen, layout)
        self._draw_panel(screen, layout, game, panel_y, panel_height, view_ply)
        self._draw_game_clocks(screen, layout, game, white_name, black_name, orientation)
        if game.pending_promotion is not None:
            self._draw_promotion_modal(screen)
        self.result_modal_open = game.is_over
        if self.result_modal_open:
            if not was_result_modal_open:
                self.result_choice = 0
            self._draw_result_modal(screen, game, result_label)
        elif self.exit_confirm_open:
            self._draw_exit_confirm_modal(screen)
        elif self.back_confirm_open:
            self._draw_back_confirm_modal(screen)
        elif self.help_modal_open:
            self._draw_help_modal(screen, version)
        self._safe_refresh(screen)


    def _draw_piece_rain(
        self,
        screen: "curses._CursesWindow",
        x: int,
        y: int,
        width: int,
        height: int,
        excluded: tuple[tuple[int, int, int, int], ...] = (),
    ) -> None:
        """Animate the large chess-piece sprites falling behind the lobby panels."""
        if not self.rain_enabled or width < 8 or height < 8:
            return
        piece_types = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING)
        for stream, column in enumerate(range(2, width - 9, 18)):
            sprite = _PIECE_GLYPHS[(piece_types[stream % len(piece_types)], "large")]
            period = height + len(sprite)
            speed = 1 + stream % 4
            phase = stream * 11
            top = (self._lobby_frame // speed + phase) % period - len(sprite)
            attr = self._rain_color((stream * 3 + stream // 2) % 4)
            for row, line in enumerate(sprite):
                at_y = y + top + row
                line_width = self._display_width(line)
                if (
                    y <= at_y < y + height
                    and not self._rain_overlaps(at_y, x + column, line_width, excluded)
                ):
                    self._addstr(screen, at_y, x + column, line, attr)

        # Small Unicode chess glyphs add scattered drops between the larger
        # sprites. Fixed pseudo-random stream properties keep them coherent
        # across frames while still making the pattern feel varied.
        small_pieces = "♟♞♜♛♚♝"
        for stream, column in enumerate(range(2, width - 1, 6)):
            seed = (stream * 1103515245 + 12345) & 0x7fffffff
            speed = 2 + seed % 7
            phase = (seed >> 5) % (height + 1)
            row = (self._lobby_frame // speed + phase) % (height + 1) - 1
            drop_y = y + row
            if (
                y <= drop_y < y + height
                and not self._rain_overlaps(drop_y, x + column, 1, excluded)
            ):
                piece = small_pieces[(seed >> 11) % len(small_pieces)]
                shade = (seed >> 17) % 4
                self._addstr(screen, y + row, x + column, piece, self._rain_color(shade))

    @staticmethod
    def _rain_overlaps(
        row: int,
        column: int,
        glyph_width: int,
        excluded: tuple[tuple[int, int, int, int], ...],
    ) -> bool:
        """Keep animated glyphs outside solid UI rectangles."""
        return any(
            top <= row < top + box_height
            and column < left + box_width
            and column + glyph_width > left
            for left, top, box_width, box_height in excluded
        )

    def _rain_color(self, shade: int) -> int:
        if self.rain_color_pairs:
            attrs = 0
            if not self.rich_colors:
                attrs = (curses.A_DIM, curses.A_DIM, 0, curses.A_BOLD)[shade]
            return self._color(14 + shade, attrs)
        return self._color(1, curses.A_DIM if shade < 2 else 0)

    def _lobby_color(self, attrs: int = 0) -> int:
        return self._color(self.lobby_background_pair, attrs)

    def _lobby_box(self, screen: "curses._CursesWindow", x: int, y: int, width: int, height: int, title: str) -> None:
        fill = self._lobby_color()
        for row in range(1, height - 1):
            self._addstr(screen, y + row, x + 1, " " * (width - 2), fill)
        self._draw_border(screen, x, y, width, height, "", self.lobby_background_pair)
        title_x = x + max(2, (width - self._display_width(title) - 2) // 2)
        self._addstr(screen, y, title_x, f" {title} ", self._lobby_color(curses.A_BOLD))

    def square_at(self, x: int, y: int) -> chess.Square | None:
        layout = self.layout
        if layout is None:
            return None
        stride_x = layout.cell_width + layout.horizontal_gap
        stride_y = layout.cell_height + layout.vertical_gap
        origin_x = layout.board_x + 1 + layout.horizontal_padding
        origin_y = layout.board_y + 1 + layout.vertical_padding
        for row in range(8):
            top = origin_y + row * stride_y
            if not top <= y < top + layout.cell_height:
                continue
            for file in range(8):
                left = origin_x + file * stride_x
                if left <= x < left + layout.cell_width:
                    # Use the same screen-to-square mapping as the renderer.
                    # Keeping hit-testing tied to drawn tile bounds prevents
                    # the edge files from drifting when gaps or sizes change.
                    return self._display_square(file, row)
        return None

    def _display_square(self, file: int, row: int) -> chess.Square:
        """Map a screen row/column to a chess square for the current orientation."""
        if self.orientation == chess.BLACK:
            return chess.square(7 - file, row)
        return chess.square(file, 7 - row)

    def _square_position(self, square: chess.Square) -> tuple[int, int]:
        """Return a square's column and row in the current board orientation."""
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        if self.orientation == chess.BLACK:
            return 7 - file, rank
        return file, 7 - rank

    def _make_layout(self, height: int, width: int) -> BoardLayout | None:
        horizontal_gap, vertical_gap = (2, 1) if self.board_gaps_enabled else (0, 0)
        panel_width = min(32, max(22, width - 98))
        panel_gap = 2
        outer_margin = 2
        border = 1
        horizontal_padding, vertical_padding = 2, 1
        inset_x = border + horizontal_padding
        inset_y = border + vertical_padding
        available_board_width = width - 2 * outer_margin - panel_width - panel_gap
        max_cell_width = (available_board_width - 2 * inset_x - 7 * horizontal_gap) // 8
        if max_cell_width < 3 and horizontal_gap:
            # Preserve the user's gap preference when it fits, but reclaim
            # horizontal gutters as a last resort on narrow terminals.
            horizontal_gap = 0
            max_cell_width = (available_board_width - 2 * inset_x) // 8
        # Clocks sit beside the board, so reserve only a compact frame margin.
        clock_space = 2
        available_board_height = height - 2 * clock_space
        max_cell_height_v = (available_board_height - 2 * inset_y - 7 * vertical_gap) // 8
        # A terminal row is about twice as tall as a character cell is wide.
        # Keep every square at the same visual aspect ratio as the board scales.
        max_cell_height_h = (max_cell_width - 1) // 2
        max_cell_height = min(max_cell_height_h, max_cell_height_v)
        if max_cell_height < 1 or max_cell_width < 3:
            return None
        cell_height = min(max_cell_height, 2 + self.zoom)
        cell_width = 2 * cell_height + 1
        if cell_height >= 5:
            piece_size = "large"
        elif cell_height >= 4:
            piece_size = "extended"
        elif cell_height >= 3:
            piece_size = "compact"
        else:
            piece_size = "small"
        inner_width = 8 * cell_width + 7 * horizontal_gap
        inner_height = 8 * cell_height + 7 * vertical_gap
        board_width = inner_width + 2 * inset_x
        board_height = inner_height + 2 * inset_y
        full_width = board_width + panel_gap + panel_width
        group_x = max(1, (width - full_width) // 2)
        if self.panel_on_left:
            panel_x = group_x
            board_x = group_x + panel_width + panel_gap
        else:
            board_x = group_x
            panel_x = board_x + board_width + panel_gap
        board_y = max(clock_space, (height - board_height - 2 * clock_space) // 2 + clock_space)
        return BoardLayout(
            board_x, board_y, board_width, board_height,
            panel_x, panel_width,
            cell_width, cell_height, horizontal_gap, vertical_gap,
            horizontal_padding, vertical_padding,
            piece_size,
        )

    def _draw_squares(
        self, screen: "curses._CursesWindow", layout: BoardLayout, game: GameSession,
        board: chess.Board,
    ) -> None:
        # Clear the complete board interior first so the rain never shows
        # through its borders, gutters, or padding between the square tiles.
        for row in range(1, layout.board_height - 1):
            self._addstr(screen, layout.board_y + row, layout.board_x + 1,
                         " " * (layout.board_width - 2), self._color(1))
        for row in range(8):
            for file in range(8):
                square = self._display_square(file, row)
                light_square = (row + file) % 2 == 0
                is_selected = square == game.selected
                is_legal_target = square in self.legal_targets
                is_last_move = square in self.last_move_squares
                is_check = square == self.check_square
                pair = (7 if is_check else 4 if is_selected else self.legal_pair if is_legal_target else
                        self.last_move_pair if is_last_move else 2 if light_square else 3)
                if self.color_enabled:
                    square_style = self._color(pair, curses.A_DIM if is_last_move and pair == 4 else 0)
                    if is_check and curses.COLOR_PAIRS < 8:
                        square_style |= curses.A_REVERSE | curses.A_BOLD
                else:
                    square_style = (curses.A_REVERSE | curses.A_BOLD) if is_check or is_selected or is_legal_target else (
                        curses.A_REVERSE | curses.A_DIM if is_last_move else
                        curses.A_REVERSE if light_square else 0
                    )
                x = layout.board_x + 1 + layout.horizontal_padding + file * (layout.cell_width + layout.horizontal_gap)
                y = layout.board_y + 1 + layout.vertical_padding + row * (layout.cell_height + layout.vertical_gap)
                for inner_y in range(layout.cell_height):
                    self._addstr(screen, y + inner_y, x, " " * layout.cell_width, square_style)
                piece = board.piece_at(square)
                if piece:
                    self._draw_piece(
                        screen, x, y, layout.cell_width, layout.cell_height,
                        layout.piece_size, piece,
                        light_square, is_check or is_selected or is_legal_target or (
                            is_last_move and self.last_move_piece_pairs
                        ), square_style, pair,
                    )

    def _draw_coordinates(self, screen: "curses._CursesWindow", layout: BoardLayout) -> None:
        """Draw file and rank labels in the board's reserved padding."""
        x_origin = layout.board_x + 1 + layout.horizontal_padding
        y_origin = layout.board_y + 1 + layout.vertical_padding
        stride_x = layout.cell_width + layout.horizontal_gap
        stride_y = layout.cell_height + layout.vertical_gap
        file_y = y_origin + 8 * layout.cell_height + 7 * layout.vertical_gap
        rank_x = layout.board_x + 2
        attr = self._color(1, curses.A_DIM)

        for file in range(8):
            square = self._display_square(file, 7)
            label = chess.FILE_NAMES[chess.square_file(square)]
            self._addstr(
                screen,
                file_y,
                x_origin + file * stride_x + layout.cell_width // 2,
                label,
                attr,
            )

        for row in range(8):
            square = self._display_square(0, row)
            label = str(chess.square_rank(square) + 1)
            self._addstr(
                screen,
                y_origin + row * stride_y + layout.cell_height // 2,
                rank_x,
                label,
                attr,
            )

    def _draw_piece(
        self,
        screen: "curses._CursesWindow",
        x: int,
        y: int,
        width: int,
        height: int,
        piece_size: str,
        piece: chess.Piece,
        light_square: bool,
        selected: bool,
        square_style: int,
        highlight_pair: int = 4,
    ) -> None:
        if piece_size == "small":
            lines = (piece.unicode_symbol(),)
        else:
            lines = _PIECE_GLYPHS[(piece.piece_type, piece_size)]
        if self.piece_pairs:
            if selected and highlight_pair == self.legal_pair and self.legal_piece_pairs:
                pair = 49 if piece.color else 50
            elif selected and highlight_pair == self.last_move_pair and self.last_move_piece_pairs:
                pair = 52 if piece.color else 53
            else:
                pair = (12 if piece.color else 13) if selected else (
                    (8 if light_square else 9) if piece.color else (10 if light_square else 11)
                )
            attr = self._color(pair, curses.A_BOLD)
        else:
            attr = square_style | (curses.A_BOLD if piece.color else curses.A_DIM)

        visible_lines = lines[:height]
        vertical_slack = height - len(visible_lines)
        if piece.piece_type == chess.PAWN:
            # The source pawn sprite is four rows tall. Bias odd slack downward
            # so its visual center sits lower within the square.
            vertical_offset = (vertical_slack + 1) // 2
        else:
            vertical_offset = vertical_slack // 2
        top = y + max(0, vertical_offset)
        sprite_width = max((self._display_width(line.strip()) for line in visible_lines), default=0)
        for offset, line in enumerate(visible_lines):
            line = line.strip()
            line = self._fit_line(line, width)
            line_width = self._display_width(line)
            canvas_left = x + max(0, (width - sprite_width) // 2)
            left = canvas_left + max(0, (sprite_width - line_width) // 2)
            self._addstr(screen, top + offset, left, line, attr)

    def _draw_annotations(self, screen: "curses._CursesWindow", layout: BoardLayout) -> None:
        attr = self._color(5, curses.A_BOLD) if self.color_enabled else curses.A_BOLD | curses.A_UNDERLINE
        stride_x = layout.cell_width + layout.horizontal_gap
        stride_y = layout.cell_height + layout.vertical_gap
        inset_x = layout.board_x + 1 + layout.horizontal_padding
        inset_y = layout.board_y + 1 + layout.vertical_padding

        for square in self.circled_squares:
            file, row = self._square_position(square)
            x = inset_x + file * stride_x
            y = inset_y + row * stride_y
            left, right = x + 1, x + layout.cell_width - 2
            top, bottom = y + 1, y + layout.cell_height - 2
            if right <= left or bottom <= top:
                continue
            self._addstr(screen, top, left, "╭" + "─" * (right - left - 1) + "╮", attr)
            self._addstr(screen, bottom, left, "╰" + "─" * (right - left - 1) + "╯", attr)
            for mark_y in range(top + 1, bottom):
                self._addstr(screen, mark_y, left, "│", attr)
                self._addstr(screen, mark_y, right, "│", attr)

        for start, destination in self.arrows:
            source_file, source_row = self._square_position(start)
            target_file, target_row = self._square_position(destination)
            points = self._grid_line(source_file, source_row, target_file, target_row)
            dx, dy = target_file - source_file, target_row - source_row
            line_char = "─" if dy == 0 else "│" if dx == 0 else "╲" if dx * dy > 0 else "╱"
            arrowheads = {
                (1, 0): "▶", (-1, 0): "◀", (0, 1): "▼", (0, -1): "▲",
                (1, 1): "↘", (-1, -1): "↖", (1, -1): "↗", (-1, 1): "↙",
            }
            step_x = 0 if dx == 0 else 1 if dx > 0 else -1
            step_y = 0 if dy == 0 else 1 if dy > 0 else -1
            for index, (file, row) in enumerate(points):
                square_x = inset_x + file * stride_x
                square_y = inset_y + row * stride_y
                char = arrowheads[(step_x, step_y)] if index == len(points) - 1 else line_char
                self._addstr(
                    screen, square_y + layout.cell_height // 2,
                    square_x + layout.cell_width // 2, char, attr,
                )

    @staticmethod
    def _grid_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
        """Return the chess-square cells crossed by a straight annotation arrow."""
        points: list[tuple[int, int]] = []
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        step_x = 1 if x0 < x1 else -1
        step_y = 1 if y0 < y1 else -1
        error = dx - dy
        while True:
            points.append((x0, y0))
            if x0 == x1 and y0 == y1:
                return points
            doubled = 2 * error
            if doubled > -dy:
                error -= dy
                x0 += step_x
            if doubled < dx:
                error += dx
                y0 += step_y

    def _draw_panel(
        self, screen: "curses._CursesWindow", layout: BoardLayout, game: GameSession,
        panel_y: int, panel_height: int, view_ply: int | None,
    ) -> None:
        x, width = layout.panel_x + 2, layout.panel_width - 4
        control_left = layout.panel_x + 2
        for row in range(1, panel_height - 1):
            self._addstr(screen, panel_y + row, layout.panel_x + 1,
                         " " * (layout.panel_width - 2), self._color(1))
        control_height = 17 if self.theme_menu_open else 8
        self._draw_border(screen, layout.panel_x, panel_y, layout.panel_width,
                          control_height, "CONTROLS")
        control_labels = (
            ("[BACK B]", "[GUIDE ?]"),
            ("[SIDE V]", "[THEME T]"),
            ("[RAIN R]", "[RESIGN S]"),
            ("[GAP G]", "[COORDS C]"),
        )
        column_width = (layout.panel_width - 2) // 2
        column_starts = (layout.panel_x + 1, layout.panel_x + 1 + column_width)
        bounds = {}
        for row_index, labels in enumerate(control_labels):
            row_y = panel_y + 2 + row_index
            for column, label in enumerate(labels):
                text_width = self._display_width(label)
                left = column_starts[column] + max(0, (column_width - text_width) // 2)
                attrs = curses.A_BOLD | curses.A_UNDERLINE
                if label == "[RAIN R]" and not self.rain_enabled:
                    attrs |= curses.A_DIM
                if label == "[COORDS C]" and not self.coordinates_enabled:
                    attrs |= curses.A_DIM
                if label == "[GAP G]" and not self.board_gaps_enabled:
                    attrs |= curses.A_DIM
                self._addstr(screen, row_y, left, label, self._color(1, attrs))
                bounds[(row_index, column)] = (row_y, left, left + text_width - 1)
        self.back_button_bounds = bounds[(0, 0)]
        self.help_button_bounds = bounds[(0, 1)]
        self.side_button_bounds = bounds[(1, 0)]
        self.theme_button_bounds = bounds[(1, 1)]
        self.rain_button_bounds = bounds[(2, 0)]
        self.surrender_button_bounds = bounds[(2, 1)]
        self.gaps_button_bounds = bounds[(3, 0)]
        self.coordinates_button_bounds = bounds[(3, 1)]

        self.game_theme_rows = ()
        if self.theme_menu_open:
            rows = []
            theme_columns = 2
            column_width = max(1, (layout.panel_width - 4) // theme_columns)
            for index, theme in enumerate(THEMES):
                row, col = divmod(index, theme_columns)
                row_y = panel_y + 7 + row
                cell_x = control_left + col * column_width
                rows.append((row_y, index, cell_x, cell_x + column_width - 1))
                selected = index == self.theme_menu_index
                style = curses.A_REVERSE if selected else 0
                self._addstr(screen, row_y, cell_x, "●" if selected else "○",
                             self._color(1, style))
                swatch_x = cell_x + 2
                if self.lobby_theme_pairs:
                    first_pair = 18 + index * 2
                    self._addstr(screen, row_y, swatch_x, " ", self._color(first_pair))
                    self._addstr(screen, row_y, swatch_x + 1, " ", self._color(first_pair + 1))
                else:
                    self._addstr(screen, row_y, swatch_x, "  ", self._color(1))
                label_x = swatch_x + 3
                label = self._fit_line(theme.label, max(0, column_width - 6))
                self._addstr(screen, row_y, label_x, label, self._color(1, style))
            self.game_theme_rows = tuple(rows)

        moves_y = panel_y + control_height
        moves_height = max(3, panel_height - control_height - 3)
        self._draw_border(screen, layout.panel_x, moves_y, layout.panel_width,
                          moves_height, "MOVES")
        nav_y = moves_y + moves_height
        move_lines = []
        for index in range(0, len(game.moves), 2):
            white = game.moves[index]
            black = game.moves[index + 1] if index + 1 < len(game.moves) else ""
            move_lines.append(f"{index // 2 + 1}. {white} {black}".rstrip())
        current_ply = len(game.moves) if view_ply is None else view_ply
        move_start_y = moves_y + 2
        move_capacity = max(0, moves_y + moves_height - 1 - move_start_y)
        if move_capacity:
            columns = 2 if width >= 30 and len(move_lines) > move_capacity else 1
            visible_capacity = move_capacity * columns
            first = max(0, len(move_lines) - visible_capacity)
            column_width = max(1, (width - 4) // columns)
            for index in range(first, len(move_lines)):
                offset = index - first
                column, row = divmod(offset, move_capacity)
                move_index = min(len(game.moves), (index + 1) * 2)
                attr = curses.A_REVERSE if move_index == current_ply and current_ply else 0
                move_x = x + column * column_width
                move_text = self._fit_line(move_lines[index], column_width)
                self._addstr(screen, move_start_y + row, move_x, move_text,
                             self._color(1, attr))
        prev_label, next_label = "[◀ PREV]", "[NEXT ▶]"
        gap = 1
        prev_width = (layout.panel_width - gap) // 2
        next_width = layout.panel_width - gap - prev_width
        prev_x = layout.panel_x
        next_x = prev_x + prev_width + gap
        self._draw_border(screen, prev_x, nav_y, prev_width, 3, "")
        self._draw_border(screen, next_x, nav_y, next_width, 3, "")
        prev_text_x = prev_x + max(1, (prev_width - self._display_width(prev_label)) // 2)
        next_text_x = next_x + max(1, (next_width - self._display_width(next_label)) // 2)
        nav_text_y = nav_y + 1
        self.move_nav_bounds = (
            nav_text_y,
            (prev_x + 1, prev_x + prev_width - 2),
            (next_x + 1, next_x + next_width - 2),
        )
        prev_attr = self._color(1, curses.A_BOLD | (curses.A_DIM if current_ply <= 0 else 0))
        next_attr = self._color(1, curses.A_BOLD | (curses.A_DIM if current_ply >= len(game.moves) else 0))
        self._addstr(screen, nav_text_y, prev_text_x, prev_label, prev_attr)
        self._addstr(screen, nav_text_y, next_text_x, next_label, next_attr)

    def _draw_clock_box(
        self,
        screen: "curses._CursesWindow",
        x: int,
        y: int,
        width: int,
        label: str,
        seconds: float,
        active: bool,
        name: str = "",
    ) -> None:
        if width < 5:
            return
        attr = self._color(6, curses.A_BOLD) if active and self.color_enabled else (
            curses.A_BOLD | curses.A_REVERSE if active else self._color(1, curses.A_BOLD)
        )
        marker = "▶" if active else " "
        text = f"{marker} {name or label}"
        clock = f"{label} {self._clock(seconds)}"
        clock_width = self._display_width(clock)
        border_attr = self._color(1, curses.A_BOLD)
        self._addstr(screen, y, x, "┌" + "─" * (width - 2) + "┐", border_attr)
        # Erase the rain and board underneath the clock's content row.
        self._addstr(screen, y + 1, x + 1, " " * (width - 2), self._color(1))
        self._addstr(screen, y + 1, x, "│", border_attr)
        self._addstr(screen, y + 1, x + width - 1, "│", border_attr)
        self._addstr(screen, y + 2, x, "└" + "─" * (width - 2) + "┘", border_attr)
        content_x, content_width = x + 2, width - 4
        if active:
            self._addstr(screen, y + 1, x + 1, " " * (width - 2), attr)
        clock_x = content_x + max(0, content_width - clock_width)
        name_width = max(1, clock_x - content_x - 1)
        self._addstr(screen, y + 1, content_x, self._fit_line(text, name_width), attr)
        self._addstr(screen, y + 1, clock_x, clock, attr)

    def _draw_game_clocks(
        self,
        screen: "curses._CursesWindow",
        layout: BoardLayout,
        game: GameSession,
        white_name: str,
        black_name: str,
        orientation: chess.Color = chess.WHITE,
    ) -> None:
        x, width = layout.panel_x, layout.panel_width
        top_color = not orientation
        bottom_color = orientation
        names = {chess.WHITE: white_name, chess.BLACK: black_name}
        self._draw_clock_box(
            screen, x, layout.board_y, width, "WHITE" if top_color else "BLACK",
            game.remaining[top_color], game.board.turn == top_color, names[top_color],
        )
        self._draw_captured_pieces(screen, x, layout.board_y - 1, width,
                                   top_color, game.captured[top_color])
        self._draw_clock_box(
            screen, x, layout.board_y + layout.board_height - 3, width,
            "WHITE" if bottom_color else "BLACK", game.remaining[bottom_color],
            game.board.turn == bottom_color, names[bottom_color],
        )
        self._draw_captured_pieces(screen, x, layout.board_y + layout.board_height,
                                   width, bottom_color, game.captured[bottom_color])

    def _draw_captured_pieces(
        self, screen: "curses._CursesWindow", x: int, y: int, width: int,
        capturer: chess.Color, captured_types: list[int],
    ) -> None:
        """Show captured enemy pieces between that player's clock and the board."""
        self._addstr(screen, y, x + 1, " " * max(0, width - 2), self._color(1))
        glyphs = "".join(
            chess.Piece(piece_type, not capturer).unicode_symbol()
            for piece_type in captured_types
        )
        if glyphs:
            glyphs = self._fit_line(glyphs, width - 4)
            self._addstr(screen, y, x + max(2, (width - self._display_width(glyphs)) // 2),
                         glyphs, self._color(1, curses.A_BOLD))

    @staticmethod
    def _clock(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60:02}:{total % 60:02}"

    def _draw_border(
        self, screen: "curses._CursesWindow", x: int, y: int, width: int, height: int, title: str, pair: int = 1
    ) -> None:
        if width < 3 or height < 3:
            return
        attr = self._color(pair, curses.A_BOLD)
        self._addstr(screen, y, x, "┌" + "─" * (width - 2) + "┐", attr)
        for row in range(1, height - 1):
            self._addstr(screen, y + row, x, "│", attr)
            self._addstr(screen, y + row, x + width - 1, "│", attr)
        self._addstr(screen, y + height - 1, x, "└" + "─" * (width - 2) + "┘", attr)
        if title:
            label = f" {title} "
            self._addstr(screen, y, x + 2, label, attr)

    def _color(self, pair: int, attrs: int = 0) -> int:
        if self.color_enabled:
            try:
                return curses.color_pair(pair) | attrs
            except curses.error:
                pass
        return attrs

    @staticmethod
    def _display_width(value: str) -> int:
        return sum(
            2 if unicodedata.east_asian_width(char) in ("W", "F")
            else 0 if unicodedata.combining(char)
            else 1
            for char in value
        )

    @classmethod
    def _fit_line(cls, value: str, width: int) -> str:
        if cls._display_width(value) <= width:
            return value
        while value and cls._display_width(value) > width:
            value = value[:-1]
        return value

    def _addstr(self, screen: "curses._CursesWindow", y: int, x: int, value: str, attr: int = 0) -> None:
        height, width = screen.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= width:
            return
        try:
            screen.addstr(y, x, value[: max(0, width - x - 1)], attr)
        except curses.error:
            pass

    @staticmethod
    def _safe_refresh(screen: "curses._CursesWindow") -> None:
        try:
            screen.refresh()
        except curses.error:
            # The terminal may have changed size after the frame was drawn;
            # the next KEY_RESIZE cycle will render with its new dimensions.
            pass
