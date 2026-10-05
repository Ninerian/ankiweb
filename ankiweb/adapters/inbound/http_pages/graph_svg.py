"""Reusable SVG chart helpers for AnkiWeb statistics and graphs.

This module provides pure-Python SVG generation primitives modeled after upstream
D3 / Svelte chart components used in Anki's statistics and deck options simulator:
- Scales:
  - LinearScale: domain -> range mapping, nice tick generation matching d3-array / d3-scale.
  - BandScale: discrete categorical domain -> range with padding.
  - TimeScale: datetime/timestamp domain -> range with day/month/year tick formatting.
- Axes:
  - render_x_axis: bottom/top horizontal SVG axis (<g class="x-ticks">) with tick lines and labels.
  - render_y_axis: left/right vertical SVG axis (<g class="y-ticks"> / <g class="y2-ticks">).
- Chart Marks:
  - render_bars: single-series bar elements with rx, color, width, height, and hover data attributes.
  - render_stacked_bars: multi-category stacked bars (e.g. Reviews, Answer Buttons).
  - render_line: SVG path string / element for trend lines (e.g. cumulative line, retention rate line).
  - render_area: SVG closed area polygon/path.
  - render_pie_slice: SVG arc path d="M...A..." for donut/pie charts (e.g. Card Counts).
  - render_calendar_cells: 7xN grid cells for daily review activity heatmap.
- Tooltip attributes:
  - data-tooltip, data-tooltip-html, data-tooltip-title for lightweight client-side hover display.
"""

from __future__ import annotations
import math
from typing import Any, Callable, Sequence


class LinearScale:
    """Linear scale mapping continuous domain [d0, d1] to range [r0, r1]."""

    def __init__(self, domain: tuple[float, float], range: tuple[float, float], clamp: bool = False):
        self.d0, self.d1 = float(domain[0]), float(domain[1])
        self.r0, self.r1 = float(range[0]), float(range[1])
        self.clamp = clamp

    def __call__(self, x: float) -> float:
        if self.d1 == self.d0:
            return self.r0
        t = (x - self.d0) / (self.d1 - self.d0)
        if self.clamp:
            t = max(0.0, min(1.0, t))
        return self.r0 + t * (self.r1 - self.r0)

    def invert(self, y: float) -> float:
        if self.r1 == self.r0:
            return self.d0
        t = (y - self.r0) / (self.r1 - self.r0)
        return self.d0 + t * (self.d1 - self.d0)

    def ticks(self, count: int = 5) -> list[float]:
        """Generate nice tick values matching standard D3 tick algorithm."""
        start, stop = self.d0, self.d1
        if start == stop:
            return [start]
        reverse = stop < start
        if reverse:
            start, stop = stop, start

        step = self._tick_increment(start, stop, count)
        if step == 0 or not math.isfinite(step):
            return []

        if step > 0:
            r0 = math.ceil(start / step) * step
            r1 = math.floor(stop / step) * step + step / 2
            ticks: list[float] = []
            val = r0
            while val <= r1:
                ticks.append(round(val, 10))
                val += step
        else:
            step = -step
            r0 = math.floor(start * step) / step
            r1 = math.ceil(stop * step) / step - 1 / (step * 2)
            ticks = []
            val = r0
            while val <= r1:
                ticks.append(round(val, 10))
                val += 1.0 / step

        if reverse:
            ticks.reverse()
        return ticks

    @staticmethod
    def _tick_increment(start: float, stop: float, count: int) -> float:
        if count <= 0:
            return 0.0
        step = (stop - start) / count
        power = math.floor(math.log10(step))
        err = step / (10 ** power)
        if err >= math.sqrt(50):
            factor = 10
        elif err >= math.sqrt(10):
            factor = 5
        elif err >= math.sqrt(2):
            factor = 2
        else:
            factor = 1
        return factor * (10 ** power) if power >= 0 else - (10 ** -power) / factor


class BandScale:
    """Discrete band scale for bar charts with categorical domains."""

    def __init__(
        self,
        domain: Sequence[Any],
        range: tuple[float, float],
        padding_inner: float = 0.1,
        padding_outer: float = 0.1,
    ):
        self.domain = list(domain)
        self.r0, self.r1 = float(range[0]), float(range[1])
        self.padding_inner = padding_inner
        self.padding_outer = padding_outer

        n = len(self.domain)
        total_width = self.r1 - self.r0
        if n == 0:
            self.step = 0.0
            self.bandwidth = 0.0
        else:
            # outer padding on both sides
            steps = n - self.padding_inner + 2 * self.padding_outer
            self.step = total_width / max(1, steps)
            self.bandwidth = self.step * (1.0 - self.padding_inner)

    def __call__(self, x: Any) -> float:
        try:
            idx = self.domain.index(x)
        except ValueError:
            return self.r0
        return self.r0 + (idx + self.padding_outer) * self.step


def format_tick_number(val: float) -> str:
    """Format tick value compactly (e.g. 5, -20, 1.5)."""
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    return f"{val:.1f}"


def format_percent(val: float) -> str:
    """Format ratio 0.0-1.0 or percent 0-100 as percentage string."""
    if val <= 1.0 and val >= 0.0:
        val = val * 100
    return f"{int(round(val))}%"


def render_x_axis(
    scale: LinearScale | BandScale,
    y: float,
    ticks: list[float] | list[Any] | None = None,
    tick_format: Callable[[Any], str] | None = None,
    tick_count: int = 6,
    css_class: str = "x-ticks",
    tick_line_length: float = 6.0,
) -> str:
    """Render horizontal axis with lines and labels."""
    if ticks is None:
        if isinstance(scale, LinearScale):
            ticks = scale.ticks(tick_count)
        elif isinstance(scale, BandScale):
            ticks = list(scale.domain)
        else:
            ticks = []

    if tick_format is None:
        tick_format = str if isinstance(scale, BandScale) else format_tick_number

    lines = [f'<g class="{css_class}" transform="translate(0, {y:.1f})" fill="none" font-size="10" font-family="sans-serif" text-anchor="middle" direction="ltr" pointer-events="none">']
    for t in ticks:
        if isinstance(scale, BandScale):
            pos_x = scale(t) + scale.bandwidth / 2.0
        else:
            pos_x = scale(t)
        label = tick_format(t)
        lines.append(
            f'  <g class="tick" opacity="1" transform="translate({pos_x:.2f},0)">'
            f'<line stroke="currentColor" y2="{tick_line_length:.1f}"></line>'
            f'<text fill="currentColor" y="{tick_line_length + 3:.1f}" dy="0.71em">{label}</text></g>'
        )
    lines.append("</g>")
    return "\n".join(lines)


def render_y_axis(
    scale: LinearScale,
    x: float,
    ticks: list[float] | None = None,
    tick_format: Callable[[float], str] | None = None,
    tick_count: int = 5,
    right: bool = False,
    css_class: str = "y-ticks",
    tick_line_length: float = 6.0,
    show_domain: bool = True,
) -> str:
    """Render vertical axis with tick lines, domain path and labels."""
    if ticks is None:
        ticks = scale.ticks(tick_count)

    if tick_format is None:
        tick_format = format_tick_number

    text_anchor = "start" if right else "end"
    label_offset = (tick_line_length + 3.0) if right else -(tick_line_length + 3.0)
    line_x2 = tick_line_length if right else -tick_line_length

    lines = [f'<g class="{css_class}" transform="translate({x:.1f}, 0)" fill="none" font-size="10" font-family="sans-serif" text-anchor="{text_anchor}" direction="ltr" pointer-events="none">']
    if show_domain and len(ticks) > 0:
        y_min = min(scale.r0, scale.r1)
        y_max = max(scale.r0, scale.r1)
        lines.append(f'  <path class="domain" stroke="currentColor" d="M0.5,{y_max:.1f}V{y_min:.1f}" pointer-events="none"></path>')

    for t in ticks:
        pos_y = scale(t)
        label = tick_format(t)
        lines.append(
            f'  <g class="tick" opacity="1" transform="translate(0,{pos_y:.2f})">'
            f'<line stroke="currentColor" x2="{line_x2:.1f}"></line>'
            f'<text fill="currentColor" x="{label_offset:.1f}" dy="0.32em">{label}</text></g>'
        )
    lines.append("</g>")
    return "\n".join(lines)


def render_bars(
    data: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    x_scale: LinearScale | BandScale,
    y_scale: LinearScale,
    width: float | None = None,
    fill: str | Callable[[dict[str, Any]], str] = "#6baed6",
    rx: float = 1.0,
    css_class: str = "bars",
) -> str:
    """Render a series of SVG <rect> bars."""
    y_zero = y_scale(0)
    elements = [f'<g class="{css_class}">']

    for d in data:
        xv = d[x_key]
        yv = float(d.get(y_key, 0))
        if isinstance(x_scale, BandScale):
            bx = x_scale(xv)
            bw = width or x_scale.bandwidth
        else:
            bx = x_scale(xv)
            bw = width or 10.0

        by = y_scale(yv)
        bh = abs(y_zero - by)
        top_y = min(by, y_zero)

        color = fill(d) if callable(fill) else fill
        tooltip = d.get("tooltip", "")
        tt_attr = f' data-tooltip="{tooltip}"' if tooltip else ""
        clickable = ' class="graph-element-clickable"' if d.get("query") else ""

        elements.append(
            f'  <rect rx="{rx}" x="{bx:.2f}" y="{top_y:.2f}" width="{bw:.2f}" height="{bh:.2f}" fill="{color}"{tt_attr}{clickable}></rect>'
        )
    elements.append("</g>")
    return "\n".join(elements)


def render_stacked_bars(
    data: list[dict[str, Any]],
    x_key: str,
    keys: list[str],
    colors: list[str],
    x_scale: LinearScale | BandScale,
    y_scale: LinearScale,
    bar_width: float | None = None,
    rx: float = 1.0,
) -> str:
    """Render stacked vertical bars for multi-category data."""
    elements = []

    for cat_idx, key in enumerate(keys):
        elements.append(f'<g class="bars{cat_idx}">')
        color = colors[cat_idx % len(colors)]
        for d in data:
            xv = d[x_key]
            base_val = float(d.get(f"_base_{key}", 0))
            val = float(d.get(key, 0))
            if val <= 0:
                continue

            if isinstance(x_scale, BandScale):
                bx = x_scale(xv)
                bw = bar_width or x_scale.bandwidth
            else:
                bx = x_scale(xv)
                bw = bar_width or 10.0

            top_y = y_scale(base_val + val)
            bot_y = y_scale(base_val)
            bh = abs(bot_y - top_y)

            tooltip = d.get(f"tooltip_{key}", d.get("tooltip", ""))
            tt_attr = f' data-tooltip="{tooltip}"' if tooltip else ""
            elements.append(
                f'  <rect rx="{rx}" x="{bx:.2f}" y="{top_y:.2f}" width="{bw:.2f}" height="{bh:.2f}" fill="{color}"{tt_attr}></rect>'
            )
        elements.append("</g>")

    return "\n".join(elements)


def render_line(
    points: list[tuple[float, float]],
    stroke: str = "rgb(150, 150, 150)",
    stroke_width: float = 1.5,
    stroke_dasharray: str | None = None,
    css_class: str = "trend-line",
) -> str:
    """Render smooth or polyline path from coordinate points."""
    if not points:
        return ""
    d_parts = [f"M{points[0][0]:.2f},{points[0][1]:.2f}"]
    for px, py in points[1:]:
        d_parts.append(f"L{px:.2f},{py:.2f}")

    dash = f' stroke-dasharray="{stroke_dasharray}"' if stroke_dasharray else ""
    return (
        f'<path class="{css_class}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"'
        f'{dash} d="{"".join(d_parts)}"></path>'
    )


def render_area(
    top_points: list[tuple[float, float]],
    bottom_y: float,
    fill: str = "rgba(107, 174, 214, 0.2)",
    css_class: str = "area-path",
) -> str:
    """Render filled SVG area under curve."""
    if not top_points:
        return ""
    d_parts = [f"M{top_points[0][0]:.2f},{bottom_y:.2f}"]
    for px, py in top_points:
        d_parts.append(f"L{px:.2f},{py:.2f}")
    d_parts.append(f"L{top_points[-1][0]:.2f},{bottom_y:.2f}Z")
    return f'<path class="{css_class}" fill="{fill}" d="{"".join(d_parts)}"></path>'


def render_pie_slice(
    start_angle: float,
    end_angle: float,
    outer_radius: float,
    inner_radius: float = 0.0,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Calculate SVG path `d` for a pie or donut slice (angles in radians, 0 at 12 o'clock)."""
    # 0 radians is top (-Y direction)
    x1 = cx + outer_radius * math.sin(start_angle)
    y1 = cy - outer_radius * math.cos(start_angle)
    x2 = cx + outer_radius * math.sin(end_angle)
    y2 = cy - outer_radius * math.cos(end_angle)

    large_arc = 1 if (end_angle - start_angle) > math.pi else 0

    if inner_radius <= 0:
        return f"M{cx:.2f},{cy:.2f}L{x1:.2f},{y1:.2f}A{outer_radius:.2f},{outer_radius:.2f},0,{large_arc},1,{x2:.2f},{y2:.2f}Z"
    else:
        x3 = cx + inner_radius * math.sin(end_angle)
        y3 = cy - inner_radius * math.cos(end_angle)
        x4 = cx + inner_radius * math.sin(start_angle)
        y4 = cy - inner_radius * math.cos(start_angle)
        return (
            f"M{x1:.2f},{y1:.2f}A{outer_radius:.2f},{outer_radius:.2f},0,{large_arc},1,{x2:.2f},{y2:.2f}"
            f"L{x3:.2f},{y3:.2f}A{inner_radius:.2f},{inner_radius:.2f},0,{large_arc},0,{x4:.2f},{y4:.2f}Z"
        )


def interpolate_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    """Interpolate linearly between two RGB colors (t between 0.0 and 1.0)."""
    t = max(0.0, min(1.0, t))
    r = int(round(c1[0] + t * (c2[0] - c1[0])))
    g = int(round(c1[1] + t * (c2[1] - c1[1])))
    b = int(round(c1[2] + t * (c2[2] - c1[2])))
    return f"rgb({r}, {g}, {b})"


def render_no_data_overlay(width: float, height: float, message: str = "NO DATA") -> str:
    """Render empty/no-data watermark text matching upstream .no-data class."""
    cx = width / 2.0
    cy = height / 2.0
    return (
        f'<g class="no-data" transform="translate({cx:.1f},{cy:.1f})" pointer-events="none">'
        f'<text text-anchor="middle" dominant-baseline="central" fill="currentColor" opacity="0.3" '
        f'font-size="24" font-weight="bold">{message}</text></g>'
    )
