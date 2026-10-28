import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "shell_src/app-client.css"
BUILT = ROOT / "ankiweb/shell/static/app-client.css"


def _theme_colors(name: str) -> dict[str, str]:
    css = SOURCE.read_text(encoding="utf-8")
    blocks = re.findall(r'@plugin "daisyui/theme"\s*\{([^}]*)\}', css)
    matches = [block for block in blocks if f'name: "{name}";' in block]
    assert len(matches) == 1, f"Expected exactly one {name} theme"
    return dict(re.findall(r"--color-([\w-]+):\s*(#[0-9a-fA-F]{6});", matches[0]))


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def test_app_css_is_built() -> None:
    assert BUILT.is_file(), "run: npm run build"
    css = BUILT.read_text(encoding="utf-8")
    for expected in ("aw-light", "aw-dark", "prefers-color-scheme"):
        assert expected in css


@pytest.mark.parametrize("theme", ["aw-light", "aw-dark"])
@pytest.mark.parametrize(
    "color", ["error", "warning", "success", "info", "primary", "accent"]
)
def test_theme_content_contrast(theme: str, color: str) -> None:
    colors = _theme_colors(theme)
    background = _luminance(colors[color])
    foreground = _luminance(colors[f"{color}-content"])
    ratio = (max(background, foreground) + 0.05) / (min(background, foreground) + 0.05)
    assert ratio >= 4.5, f"{theme} {color}: {ratio:.2f}:1, expected at least 4.5:1"
