"""Command-line entry point for Pawnix."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError

from pawnix import __version__
from pawnix.lichess.client import LichessClient
from pawnix.ui.app import PawnixApp
from pawnix.ui.themes import THEMES


DEFAULT_MINUTES = 5
DEFAULT_INCREMENT = 3
MAX_LICHESS_MINUTES = 180
MAX_LICHESS_INCREMENT = 180


def _bounded_int(label: str, minimum: int, maximum: int):
    """Build an argparse converter with clear bounds in its error message."""
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} must be an integer") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"{label} must be between {minimum} and {maximum}"
            )
        return number

    return parse


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pawnix",
        description=(
            "Play chess in the terminal. With no command, Pawnix opens the interactive lobby; "
            "from there you can choose local or Lichess games."
        ),
        epilog=(
            "Examples:\n"
            "  pawnix\n"
            "  pawnix --minutes 3 --increment 2 --theme moss\n"
            "  pawnix profile DrNykterstein\n"
            "  pawnix profile DrNykterstein --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"Pawnix {__version__}")

    launch = parser.add_argument_group("interactive launch options")
    launch.add_argument(
        "--minutes", type=_bounded_int("minutes", 1, MAX_LICHESS_MINUTES), default=None,
        metavar="N",
        help=f"initial clock minutes per player, 1–{MAX_LICHESS_MINUTES} "
             f"(default: {DEFAULT_MINUTES})",
    )
    launch.add_argument(
        "--increment", type=_bounded_int("increment", 0, MAX_LICHESS_INCREMENT), default=None,
        metavar="SECONDS",
        help=f"clock increment per move, 0–{MAX_LICHESS_INCREMENT} seconds "
             f"(default: {DEFAULT_INCREMENT})",
    )
    launch.add_argument(
        "--theme", choices=[theme.key for theme in THEMES], default=None, metavar="PRESET",
        help=("use this board and piece theme for this run; presets: "
              + ", ".join(theme.key for theme in THEMES)),
    )

    commands = parser.add_subparsers(
        dest="command", title="commands", metavar="COMMAND",
        help="optional command (default: open the interactive lobby)",
    )
    profile = commands.add_parser(
        "profile", help="look up a public Lichess profile",
        description="Fetch public Lichess profile data. No account or token is required.",
    )
    profile.add_argument("username", metavar="USERNAME", help="Lichess username to look up")
    profile.add_argument(
        "--json", action="store_true", dest="as_json",
        help="print the full API response as formatted JSON for scripts",
    )
    return parser


def _print_profile(user: dict, requested_username: str) -> None:
    username = user.get("username") or requested_username
    print(username)
    title = user.get("title")
    if isinstance(title, str) and title:
        print(f"Title: {title}")

    online = user.get("online")
    if isinstance(online, bool):
        print(f"Online: {'yes' if online else 'no'}")

    perfs = user.get("perfs")
    if isinstance(perfs, dict):
        ratings = []
        for name, info in sorted(perfs.items()):
            if isinstance(info, dict) and isinstance(info.get("rating"), (int, float)):
                ratings.append(f"{name}: {info['rating']}")
        if ratings:
            print("Ratings: " + " | ".join(ratings))


def main() -> None:
    parser = _parser()
    args = parser.parse_args()

    if args.command == "profile":
        if args.minutes is not None or args.increment is not None or args.theme is not None:
            parser.error("--minutes, --increment, and --theme apply only when launching the lobby")
        try:
            user = LichessClient().get_public_profile(args.username)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            print(f"Pawnix: Lichess profile lookup failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if args.as_json:
            print(json.dumps(user, indent=2, sort_keys=True))
        else:
            _print_profile(user, args.username)
        return

    PawnixApp(
        minutes=args.minutes if args.minutes is not None else DEFAULT_MINUTES,
        increment=args.increment if args.increment is not None else DEFAULT_INCREMENT,
        theme=args.theme,
    ).run()


if __name__ == "__main__":
    main()
