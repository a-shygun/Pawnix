"""Local chess state, clocks, and move handling."""

from __future__ import annotations

import time
from dataclasses import dataclass

import chess


@dataclass
class _Snapshot:
    board: chess.Board
    moves: list[str]
    remaining: dict[chess.Color, float]
    captured: dict[chess.Color, list[int]]
    flagged: chess.Color | None
    finished: bool
    paused: bool
    draw_offered: bool
    status: str


class GameSession:
    """Own a local hot-seat game independently of its terminal interface."""

    def __init__(self, minutes: int = 5, increment: int = 3) -> None:
        self.board = chess.Board()
        self.minutes = minutes
        self.increment = increment
        self.remaining = {chess.WHITE: float(minutes * 60), chess.BLACK: float(minutes * 60)}
        self.last_tick = time.monotonic()
        self.moves: list[str] = []
        self.captured = {chess.WHITE: [], chess.BLACK: []}
        self.selected: chess.Square | None = None
        self.input_buffer = ""
        self.status = "Select a piece and destination, or type a move such as e2e4 or Nf3."
        self.flagged: chess.Color | None = None
        self.finished = False
        self.paused = False
        self.pending_promotion: tuple[chess.Square, chess.Square] | None = None
        self.draw_offered = False
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []

    @property
    def is_over(self) -> bool:
        return self.finished or self.flagged is not None or self.board.is_game_over()

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        elapsed = now - self.last_tick
        self.last_tick = now
        if self.is_over or self.paused:
            return
        color = self.board.turn
        self.remaining[color] = max(0.0, self.remaining[color] - elapsed)
        if self.remaining[color] <= 0:
            self.flagged = color
            self.status = f"{'White' if color else 'Black'} ran out of time. Game over."

    def select_square(self, square: chess.Square) -> None:
        if self.is_over:
            return
        piece = self.board.piece_at(square)
        if self.selected is None:
            if piece and piece.color == self.board.turn:
                self.selected = square
                self.status = f"Selected {chess.square_name(square)}. Choose its destination."
            else:
                self.status = "Select a piece belonging to the side to move."
            return

        if square == self.selected:
            self.selected = None
            self.status = "Selection cleared."
            return

        selected_piece = self.board.piece_at(self.selected)
        # Accept both common castling gestures: king to its final square, or
        # king to the rook. python-chess still makes the final legality call.
        if (piece and piece.color == self.board.turn and selected_piece
                and selected_piece.piece_type == chess.KING
                and piece.piece_type == chess.ROOK):
            castle = next((candidate for candidate in self.board.legal_moves
                           if candidate.from_square == self.selected
                           and self.board.is_castling(candidate)
                           and (chess.square_file(candidate.to_square) > chess.square_file(candidate.from_square))
                           == (chess.square_file(square) > chess.square_file(candidate.from_square))), None)
            if castle is not None:
                self.push_move(castle)
                return

        move = chess.Move(self.selected, square)
        if selected_piece and selected_piece.piece_type == chess.PAWN and chess.square_rank(square) in (0, 7):
            move.promotion = chess.QUEEN
            if move in self.board.legal_moves:
                self.pending_promotion = (self.selected, square)
                self.status = "Promote to queen, rook, bishop, or knight."
                return
        if move in self.board.legal_moves:
            self.push_move(move)
        elif piece and piece.color == self.board.turn:
            self.selected = square
            self.status = f"Selected {chess.square_name(square)}. Choose its destination."
        else:
            self.selected = None
            self.status = "That move is not legal."

    def submit_move(self) -> None:
        text = self.input_buffer.strip()
        self.input_buffer = ""
        if not text:
            return
        if self.is_over:
            self.status = "This game is over. Start a new Pawnix session to play again."
            return
        try:
            try:
                move = self.board.parse_uci(text.lower())
            except ValueError:
                move = self.board.parse_san(text)
            if move not in self.board.legal_moves:
                raise ValueError("illegal move")
        except ValueError:
            self.status = f"Could not parse a legal move: {text}"
            return
        self.push_move(move)

    def choose_promotion(self, piece_type: int) -> None:
        if self.pending_promotion is None:
            return
        origin, destination = self.pending_promotion
        self.pending_promotion = None
        move = chess.Move(origin, destination, promotion=piece_type)
        if move in self.board.legal_moves:
            self.push_move(move)

    def cancel_promotion(self) -> None:
        self.pending_promotion = None
        self.status = "Promotion canceled. Choose another move."

    def _snapshot(self) -> _Snapshot:
        return _Snapshot(
            self.board.copy(stack=True), list(self.moves), dict(self.remaining),
            {color: list(pieces) for color, pieces in self.captured.items()},
            self.flagged, self.finished, self.paused, self.draw_offered, self.status,
        )

    def _restore(self, snapshot: _Snapshot) -> None:
        self.board = snapshot.board.copy(stack=True)
        self.moves = list(snapshot.moves)
        self.remaining = dict(snapshot.remaining)
        self.captured = {color: list(pieces) for color, pieces in snapshot.captured.items()}
        self.flagged, self.finished = snapshot.flagged, snapshot.finished
        self.paused, self.draw_offered, self.status = snapshot.paused, snapshot.draw_offered, snapshot.status
        self.selected = None
        self.pending_promotion = None
        self.last_tick = time.monotonic()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self.status = "Move undone."
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self.status = "Move restored."
        return True

    def claim_draw(self) -> bool:
        if self.board.can_claim_threefold_repetition():
            self.finished = True
            self.status = "Draw claimed by threefold repetition."
            return True
        if self.board.can_claim_fifty_moves():
            self.finished = True
            self.status = "Draw claimed by the fifty-move rule."
            return True
        return False

    def push_move(self, move: chess.Move) -> None:
        self._undo.append(self._snapshot())
        self._redo.clear()
        san = self.board.san(move)
        moving_color = self.board.turn
        if self.board.is_capture(move):
            captured_square = move.to_square
            if self.board.is_en_passant(move):
                captured_square += -8 if moving_color else 8
            captured = self.board.piece_at(captured_square)
            if captured:
                self.captured[moving_color].append(captured.piece_type)
        self.board.push(move)
        self.remaining[moving_color] += self.increment
        self.moves.append(san)
        self.draw_offered = False
        self.selected = None
        self.last_tick = time.monotonic()
        # Threefold repetition and the fifty-move rule are claimable draws,
        # not automatic endings. Keep the game live until a player claims one;
        # python-chess's default outcome still ends automatic draws such as
        # fivefold repetition and the seventy-five-move rule.
        outcome = self.board.outcome()
        self.status = (
            f"Game over: {outcome.result()} · {outcome.termination.name.replace('_', ' ').lower()}"
            if outcome
            else f"{'White' if self.board.turn else 'Black'} to move."
        )

