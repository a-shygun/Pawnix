"""Matched board and piece color presets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeSet:
    key: str
    label: str
    light: int
    dark: int
    selected: int
    white: int
    black: int
    fallback_light: int
    fallback_dark: int
    fallback_selected: int
    fallback_white: int
    fallback_black: int


THEMES = (
    ThemeSet("sand", "Sand", 223, 137, 130, 255, 16, 7, 3, 1, 7, 0),
    ThemeSet("walnut", "Walnt", 180, 94, 136, 255, 16, 7, 3, 1, 7, 0),
    ThemeSet("copper", "Rust", 223, 130, 202, 255, 16, 7, 3, 1, 7, 0),
    ThemeSet("parchment", "Parch", 230, 94, 130, 255, 16, 7, 3, 1, 7, 0),
    ThemeSet("mist", "Mist", 248, 66, 172, 255, 16, 7, 6, 3, 7, 0),
    ThemeSet("ocean", "Ocean", 109, 67, 208, 255, 16, 7, 4, 6, 7, 0),
    ThemeSet("ice", "Ice", 152, 67, 208, 255, 16, 7, 6, 4, 7, 0),
    ThemeSet("olive", "Olive", 230, 108, 94, 255, 16, 7, 7, 2, 7, 0),
    ThemeSet("moss", "Moss", 102, 59, 223, 255, 16, 7, 2, 7, 7, 0),
    ThemeSet("stone", "Stone", 245, 101, 130, 255, 16, 7, 0, 7, 7, 0),
    ThemeSet("silver", "Steel", 250, 243, 166, 255, 16, 7, 0, 7, 7, 0),
    ThemeSet("graphite", "Graph", 250, 240, 214, 255, 16, 7, 0, 7, 7, 0),
    ThemeSet("linen", "Linen", 252, 245, 102, 255, 16, 7, 0, 7, 7, 0),
    ThemeSet("violet", "Mauve", 103, 90, 34, 255, 16, 5, 3, 7, 7, 0),
    ThemeSet("wood4", "Wood4", 180, 94, 166, 255, 16, 7, 3, 1, 7, 0),
)


def select_theme(key: str) -> ThemeSet:
    """Return a named theme, falling back to Ocean for unknown values."""
    fallback = next(theme for theme in THEMES if theme.key == "ocean")
    return next((theme for theme in THEMES if theme.key == key), fallback)
