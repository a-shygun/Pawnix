"""Small persistent settings for the Pawnix terminal interface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pawnix.ui.themes import THEMES


def preferences_path() -> Path:
    """Return the platform-appropriate Pawnix settings path."""
    if os.environ.get("XDG_CONFIG_HOME"):
        root = Path(os.environ["XDG_CONFIG_HOME"])
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path.home() / ".config"
    return root / "pawnix" / "settings.json"


def load_theme(default: str = "ocean") -> str:
    """Load the saved theme key, returning a valid fallback if unavailable."""
    try:
        value = json.loads(preferences_path().read_text(encoding="utf-8"))
        key = value.get("theme") if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        key = None
    valid = {theme.key for theme in THEMES}
    return key if key in valid else default


def save_theme(key: str) -> None:
    """Persist a selected theme using an atomic replace."""
    if key not in {theme.key for theme in THEMES}:
        raise ValueError(f"Unknown Pawnix theme: {key}")
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    settings["theme"] = key
    # Discard the old custom-color editor data; presets now live in themes.py.
    settings.pop("theme_colors", None)
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
