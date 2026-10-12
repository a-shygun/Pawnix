"""Portable PGN storage for Pawnix games and autosaves."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import chess
import chess.pgn

from pawnix.game.session import GameSession


def games_directory() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "pawnix" / "games"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "pawnix" / "games"


def _to_pgn(session: GameSession) -> chess.pgn.Game:
    game = chess.pgn.Game()
    root = session.board.root()
    if root.fen() != chess.STARTING_FEN:
        game.setup(root)
    game.headers["Event"] = "Pawnix game"
    game.headers["Date"] = time.strftime("%Y.%m.%d")
    game.headers["White"] = "White"
    game.headers["Black"] = "Black"
    if session.flagged is not None:
        result = "0-1" if session.flagged == chess.WHITE else "1-0"
    elif session.finished and "draw" in session.status.lower():
        result = "1/2-1/2"
    else:
        result = session.board.result()
    game.headers["Result"] = result
    game.headers["PawnixIncrement"] = str(session.increment)
    game.headers["PawnixMinutes"] = str(session.minutes)
    game.headers["PawnixWhiteSeconds"] = str(round(session.remaining[chess.WHITE], 2))
    game.headers["PawnixBlackSeconds"] = str(round(session.remaining[chess.BLACK], 2))
    node = game
    for move in session.board.move_stack:
        node = node.add_variation(move)
    return game


def save_game(session: GameSession, path: Path | None = None, *, archive: bool = False) -> Path:
    directory = games_directory()
    directory.mkdir(parents=True, exist_ok=True)
    if path is None:
        if archive:
            path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}.pgn"
        else:
            path = directory / "current.pgn"
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        print(_to_pgn(session), file=stream, end="\n\n")
    return path


def load_game(path: Path | None = None) -> GameSession:
    if path is None:
        path = games_directory() / "current.pgn"
    with path.expanduser().open(encoding="utf-8") as stream:
        parsed = chess.pgn.read_game(stream)
    if parsed is None or parsed.errors:
        detail = "; ".join(str(error) for error in (parsed.errors if parsed else ()))
        raise ValueError(f"Could not read PGN game{': ' + detail if detail else ''}")
    session = GameSession(int(parsed.headers.get("PawnixMinutes", 5)),
                          int(parsed.headers.get("PawnixIncrement", 0)))
    session.board = parsed.board()
    for move in parsed.mainline_moves():
        session.push_move(move)
    session.remaining[chess.WHITE] = float(parsed.headers.get("PawnixWhiteSeconds", 300))
    session.remaining[chess.BLACK] = float(parsed.headers.get("PawnixBlackSeconds", 300))
    session.increment = int(parsed.headers.get("PawnixIncrement", 0))
    session.minutes = int(parsed.headers.get("PawnixMinutes", session.minutes))
    session.last_tick = time.monotonic()
    session.status = f"Loaded {path.name}; continue the game or review its moves."
    session._undo.clear()
    session._redo.clear()
    return session


def recent_games(limit: int = 10) -> list[Path]:
    directory = games_directory()
    if not directory.exists():
        return []
    return sorted(
        (path for path in directory.glob("*.pgn") if path.name != "current.pgn"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]
