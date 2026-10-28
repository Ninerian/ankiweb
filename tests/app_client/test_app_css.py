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


@pytest.fixture
def css_page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(
                '<div class="card neo-press" role="button" '
                'style="width: 100px; height: 50px">Press</div>'
                '<div dir="ltr"><div class="meter-fill" data-testid="ltr" '
                'style="width: 80px; height: 20px"></div></div>'
                '<div dir="rtl"><div class="meter-fill" data-testid="rtl" '
                'style="width: 80px; height: 20px"></div></div>'
            )
            page.add_style_tag(content=BUILT.read_text(encoding="utf-8"))
            page.add_style_tag(
                content="*, *::before, *::after { transition: none !important; }"
            )
            yield page
        finally:
            browser.close()


def test_neo_press_overrides_card_and_responds_to_press(css_page) -> None:
    card = css_page.get_by_role("button", name="Press")
    border = card.evaluate(
        "(el) => { el.style.setProperty('--border', '5px'); "
        "return getComputedStyle(el).borderTopWidth; }"
    )
    assert border == "5px"
    shadow = card.evaluate("(el) => getComputedStyle(el).boxShadow")
    assert "3px 3px 0px" in shadow
    before = card.bounding_box()
    assert before is not None
    css_page.mouse.move(
        before["x"] + before["width"] / 2, before["y"] + before["height"] / 2
    )
    css_page.mouse.down()
    pressed = card.bounding_box()
    assert pressed is not None
    assert pressed["x"] - before["x"] == pytest.approx(2)
    assert pressed["y"] - before["y"] == pytest.approx(2)
    assert "3px 3px 0px" not in card.evaluate("(el) => getComputedStyle(el).boxShadow")
    css_page.mouse.up()
    assert card.evaluate("(el) => getComputedStyle(el).boxShadow") == shadow


@pytest.mark.parametrize(
    ("direction", "end", "start"), [("ltr", "right", "left"), ("rtl", "left", "right")]
)
def test_meter_fill_border_follows_text_direction(
    css_page, direction, end, start
) -> None:
    border = css_page.get_by_test_id(direction).evaluate(
        """(el) => {
            const style = getComputedStyle(el);
            return {
                left: [style.borderLeftWidth, style.borderLeftStyle, style.borderLeftColor],
                right: [style.borderRightWidth, style.borderRightStyle, style.borderRightColor],
            };
        }"""
    )
    assert border[end][:2] == ["2px", "solid"]
    assert border[end][2] != "rgba(0, 0, 0, 0)"
    assert border[start][0] == "0px"


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
