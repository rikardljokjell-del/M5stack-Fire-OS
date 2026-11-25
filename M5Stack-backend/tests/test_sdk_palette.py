"""Legibility of the actual shared themes on FIRE's RGB565 display."""
import json
from pathlib import Path
import re

import pytest


DATA = Path(__file__).parents[1] / "fire_backend/data/app_sdk"
SOURCE = (DATA / "ui.lua").read_text(encoding="utf-8")
THEMES = {
    name: {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", fields)}
    for name, fields in re.findall(r"^ ([a-z_]+)=\{([^}]+)\}", SOURCE, re.M)
}


def luminance(rgb565):
    channels = [((rgb565 >> 11) & 31) / 31, ((rgb565 >> 5) & 63) / 63, (rgb565 & 31) / 31]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def test_every_advertised_theme_has_a_complete_palette():
    assert set(THEMES) == set(json.loads((DATA / "sdk.json").read_text(encoding="utf-8"))["themes"])
    for palette in THEMES.values():
        assert set(palette) == {"bg", "panel", "fg", "muted", "accent", "good", "bad", "border"}
        assert all(0 <= value <= 65535 for value in palette.values())


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("foreground,background", [
    ("fg", "bg"), ("fg", "panel"), ("muted", "bg"), ("muted", "panel"),
    ("bg", "accent"), ("bg", "good"), ("bg", "bad"),
])
def test_small_text_has_readable_contrast(theme, foreground, background):
    palette = THEMES[theme]
    dark, light = sorted((luminance(palette[foreground]), luminance(palette[background])))
    assert (light + 0.05) / (dark + 0.05) >= 4.5
