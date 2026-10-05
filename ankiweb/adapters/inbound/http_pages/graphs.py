"""Next Graphs router and presentation logic for Anki statistics rewrite.

Serves /graphs with pure Jinja + Datastar + pure-Python SVG generation.
"""

from __future__ import annotations
import math
from datetime import date, timedelta
from typing import Any, Callable, Sequence, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.core.i18n import tr
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator as SSE, ReadSignals
from ankiweb.adapters.inbound.http_pages.graph_svg import (
    LinearScale, BandScale, render_x_axis, render_y_axis, render_bars,
    render_stacked_bars, render_line, render_pie_slice, render_no_data_overlay,
    interpolate_color
)
from anki import stats_pb2


def _compute_median(numbers: Sequence[float]) -> float:
    """Compute median matching d3 quantile(numbers, 0.5)."""
    if not numbers:
        return 0.0
    sorted_nums = sorted(numbers)
    n = len(sorted_nums)
    if n % 2 == 1:
        return float(sorted_nums[n // 2])
    else:
        return float(sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2.0


def _compute_percentile(numbers: Sequence[float], p: float) -> float:
    """Compute quantile p (0.0 to 1.0) matching d3."""
    if not numbers:
        return 0.0
    sorted_nums = sorted(numbers)
    n = len(sorted_nums)
    if n == 1:
        return float(sorted_nums[0])
    pos = (n - 1) * p
    base = int(math.floor(pos))
    rest = pos - base
    if base + 1 < n:
        return sorted_nums[base] + rest * (sorted_nums[base + 1] - sorted_nums[base])
    return float(sorted_nums[base])


def generate_today_stats(today: stats_pb2.GraphsResponse.Today) -> dict[str, Any]:
    """Format Today statistics section matching upstream logic."""
    count = today.answer_count
    total_secs = today.answer_millis / 1000.0
    secs_per_card = (total_secs / count) if count > 0 else 0.0

    unit = "seconds" if total_secs < 60 else "minutes"
    amount = total_secs if unit == "seconds" else (total_secs / 60.0)

    # tr.statistics_studied_today(unit, secs_per_card, amount, cards)
    # Formats: 'Studied X cards in Y.YY seconds today (Z.ZZs/card)'
    studied_str = tr.statistics_studied_today(
        unit=unit,
        secs_per_card=cast(int, round(secs_per_card, 2)),
        amount=cast(int, round(amount, 2)),
        cards=count,
    )

    n_again = today.answer_count - today.correct_count
    again_pct = (n_again / count * 100.0) if count > 0 else 0.0
    # In legacy: Ir() is tr.statistics_today_again_count() which is "Again count:"
    again_label = tr.statistics_today_again_count()
    if not again_label.endswith(":"):
        again_label = f"{again_label}:"
    again_str = f"{again_label} {n_again} ({again_pct:.1f}%)" if again_pct % 1 != 0 else f"{again_label} {n_again} ({int(again_pct)}%)"

    breakdown_str = f"Learn: {today.learn_count}, Review: {today.review_count}, Relearn: {today.relearn_count}, Filtered: {today.early_review_count}"

    if today.mature_count > 0:
        mature_pct = today.mature_correct / today.mature_count * 100.0
        mature_str = tr.statistics_today_correct_mature(
            correct=today.mature_correct,
            total=today.mature_count,
            percent=f"{mature_pct:.1f}%",
        )
    else:
        mature_str = tr.statistics_today_no_mature_cards()

    return {
        "title": tr.statistics_today_title(),
        "has_data": count > 0,
        "studied_str": studied_str,
        "again_str": again_str,
        "breakdown_str": breakdown_str,
        "mature_str": mature_str,
        "no_cards_str": tr.statistics_today_no_cards(),
    }


def generate_future_due_chart(
    future_due: stats_pb2.GraphsResponse.FutureDue,
    range_days: int = 30,
    show_backlog: bool = True,
) -> dict[str, Any]:
    """Generate SVG chart for Future Due."""
    all_counts = dict(future_due.future_due)
    # Backlog filtering: if show_backlog is False, only non-negative days
    if show_backlog:
        active_counts = all_counts
    else:
        active_counts = {k: v for k, v in all_counts.items() if k >= 0}

    # Future total counts reviews in the charted slice (matching legacy f = sum(b, count))
    # Will be computed below as sum of counts in data
    has_any = len(active_counts) > 0 and sum(active_counts.values()) > 0

    min_day = min(active_counts.keys()) if active_counts else 0
    max_day_data = max(active_counts.keys()) if active_counts else 30

    if not show_backlog or min_day >= 0:
        start_day = 0
    else:
        start_day = min_day

    if range_days == 30:
        end_day = 31
    elif range_days == 90:
        end_day = 90
    elif range_days == 365:
        end_day = 365
    elif range_days == 0:
        end_day = max(max_day_data, 30)
    else:
        end_day = max(range_days, 1)

    # If backlog exists, negative start
    if show_backlog and min_day < 0:
        if range_days == 30:
            start_day = max(min_day, -30)
        elif range_days == 90:
            start_day = max(min_day, -90)
        elif range_days == 365:
            start_day = max(min_day, -365)
        else:
            start_day = min_day

    data: list[dict[str, Any]] = []
    max_count = 0
    running_tot = 0

    for d in range(start_day, end_day + 1):
        c = active_counts.get(d, 0)
        if d >= 0:
            running_tot += c
        max_count = max(max_count, c)
        if d < 0:
            day_label = f"{-d} days overdue"
            tt = f"{day_label}:&#10;{c} cards due (backlog)"
        elif d == 0:
            day_label = "Today"
            tt = f"{day_label}:&#10;{c} cards due&#10;Running total: {running_tot}"
        elif d == 1:
            day_label = "Tomorrow"
            tt = f"{day_label}:&#10;{c} cards due&#10;Running total: {running_tot}"
        else:
            day_label = f"in {d} days"
            tt = f"{day_label}:&#10;{c} cards due&#10;Running total: {running_tot}"
        data.append({"day": d, "count": c, "running": running_tot, "tooltip": tt, "is_backlog": d < 0})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25

    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom

    x_scale = LinearScale((start_day, end_day), (margin_left, width - margin_right))
    y_max = max(max_count, 1)
    y_scale = LinearScale((0, y_max), (height - margin_bottom, margin_top))

    c1 = (50, 155, 81)
    c2 = (183, 226, 177)
    backlog_color = "rgb(251, 106, 74)"  # reddish backlog color
    bar_w = chart_w / max(len(data), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']

    svg_parts.append('<g class="bars">')
    for idx, item in enumerate(data):
        bx = x_scale(item["day"])
        by = y_scale(item["count"])
        bh = (height - margin_bottom) - by
        if item["is_backlog"]:
            fill = backlog_color
        else:
            t = (item["day"] - 0) / max(end_day, 1)
            fill = interpolate_color(c1, c2, t)
        tt = item["tooltip"]
        svg_parts.append(
            f'  <rect rx="1" x="{bx:.2f}" y="{by:.2f}" width="{bar_w:.2f}" height="{bh:.2f}" fill="{fill}" data-tooltip="{tt}"></rect>'
        )
    svg_parts.append('</g>')

    svg_parts.append('<g class="hover-columns">')
    for item in data:
        bx = x_scale(item["day"])
        tt = item["tooltip"]
        svg_parts.append(
            f'  <rect x="{bx:.2f}" y="{margin_top}" width="{bar_w:.2f}" height="{chart_h}" fill="transparent" data-tooltip="{tt}" class="graph-element-clickable"></rect>'
        )
    svg_parts.append('</g>')

    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=7))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if not has_any:
        svg_parts.append(render_no_data_overlay(width, height))

    svg_parts.append('</svg>')

    span_days = end_day - min(0, start_day)
    slice_total = sum(item["count"] for item in data)
    avg_reviews = slice_total / max(span_days, 1)
    tomorrow_due = all_counts.get(1, 0)

    summary = [
        {"label": "Total", "value": f"{slice_total} reviews"},
        {"label": "Average", "value": f"{avg_reviews:.1f} reviews/day" if avg_reviews >= 1.0 else f"{int(round(avg_reviews))} reviews/day"},
        {"label": "Due tomorrow", "value": f"{tomorrow_due} reviews"},
        {"label": "Daily load", "value": f"{future_due.daily_load} reviews/day"},
    ]

    return {
        "title": tr.statistics_future_due_title(),
        "subtitle": tr.statistics_future_due_subtitle(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": has_any,
        "range_days": range_days,
        "show_backlog": show_backlog,
        "have_backlog": future_due.have_backlog,
    }


def generate_calendar_chart(revs: stats_pb2.GraphsResponse.ReviewCountsAndTimes, year: int = 2026) -> dict[str, Any]:
    """Generate year calendar activity heatmap matching legacy."""
    width = 600
    height = 120
    margin_left = 40
    margin_top = 20

    cell_size = 8.37
    cell_h = 10
    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']

    days_labels = ["S", "M", "T", "W", "T", "F", "S"]
    svg_parts.append('<g class="weekdays">')
    for d_idx, dl in enumerate(days_labels):
        pos_y = margin_top + d_idx * (cell_h + 2)
        svg_parts.append(
            f'  <text x="{margin_left - 3:.1f}" y="{pos_y:.1f}" fill="currentColor" '
            f'dominant-baseline="hanging" text-anchor="end" font-size="small" font-family="monospace">{dl}</text>'
        )
    svg_parts.append('</g>')

    start_date = date(year, 1, 1)
    today_dt = date.today()
    end_date = min(date(year, 12, 31), today_dt) if year == today_dt.year else date(year, 12, 31)
    cur = start_date
    counts = {k: v.learn + v.relearn + v.young + v.mature + v.filtered for k, v in revs.count.items()}
    max_c = max(counts.values()) if counts else 0

    svg_parts.append('<g class="days">')
    while cur <= end_date:
        day_of_year = cur.timetuple().tm_yday
        day_of_week = (cur.weekday() + 1) % 7
        week_of_year = (day_of_year + ((start_date.weekday() + 1) % 7) - 1) // 7

        cx = margin_left + week_of_year * (cell_size + 2)
        cy = margin_top + day_of_week * (cell_h + 2)

        days_ago = (date.today() - cur).days
        c = counts.get(-days_ago, 0)
        if c > 0:
            t = c / max(max_c, 1)
            fill = interpolate_color((220, 220, 221), (33, 102, 172), t)
        else:
            fill = "#ddd"

        tt = f"{cur.strftime('%Y-%m-%d')}: {c} reviews"
        svg_parts.append(
            f'  <rect x="{cx:.2f}" y="{cy:.2f}" width="{cell_size:.2f}" height="{cell_h:.2f}" fill="{fill}" data-tooltip="{tt}"></rect>'
        )
        cur += timedelta(days=1)
    svg_parts.append('</g>')

    if max_c == 0:
        svg_parts.append(render_no_data_overlay(width, height))

    svg_parts.append('</svg>')

    return {
        "title": tr.statistics_calendar_title(),
        "subtitle": "",
        "svg": "\n".join(svg_parts),
        "year": year,
        "has_data": max_c > 0,
    }


def generate_reviews_chart(
    revs: stats_pb2.GraphsResponse.ReviewCountsAndTimes,
    days_range: int = 30,
    show_time: bool = False,
) -> dict[str, Any]:
    """Generate Reviews history chart (count or time)."""
    data_map = revs.time if show_time else revs.count
    max_day = days_range if days_range > 0 else (max(abs(k) for k in data_map.keys()) if data_map else 30)
    max_day = max(max_day, 1)

    series_keys = ["learn", "relearn", "young", "mature", "filtered"]
    colors = [
        "rgb(253, 141, 60)",
        "rgb(251, 106, 74)",
        "rgb(116, 196, 118)",
        "rgb(49, 163, 84)",
        "rgb(107, 174, 214)",
    ]

    items: list[dict[str, Any]] = []
    total_val = 0.0
    days_studied_count = 0

    for d in range(-max_day, 1):
        entry = data_map.get(d)
        item: dict[str, Any] = {"day": d}
        running_base = 0.0
        day_tot = 0.0
        if entry:
            for k in series_keys:
                raw_v = getattr(entry, k, 0)
                v = (raw_v / 1000.0 / 60.0) if show_time else float(raw_v)
                item[f"_base_{k}"] = running_base
                item[k] = v
                running_base += v
                day_tot += v
        else:
            for k in series_keys:
                item[f"_base_{k}"] = 0.0
                item[k] = 0.0

        if day_tot > 0:
            days_studied_count += 1
            total_val += day_tot

        unit_str = "minutes" if show_time else "reviews"
        item["tooltip"] = f"{-d} days ago: {day_tot:.1f} {unit_str}" if show_time else f"{-d} days ago: {int(day_tot)} {unit_str}"
        items.append(item)

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25

    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom

    x_scale = LinearScale((-max_day, 0), (margin_left, width - margin_right))
    max_y = max(sum(float(it.get(k, 0)) for k in series_keys) for it in items) if items else 0
    max_y = max(max_y, 1.0)
    y_scale = LinearScale((0, max_y), (height - margin_bottom, margin_top))

    bar_w = chart_w / max(len(items), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append(render_stacked_bars(items, "day", series_keys, colors, x_scale, y_scale, bar_width=bar_w))

    svg_parts.append('<g class="hover-columns">')
    for item in items:
        bx = x_scale(item["day"])
        tt = item["tooltip"]
        svg_parts.append(
            f'  <rect x="{bx:.2f}" y="{margin_top}" width="{bar_w:.2f}" height="{chart_h}" fill="transparent" data-tooltip="{tt}" class="graph-element-clickable"></rect>'
        )
    svg_parts.append('</g>')

    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=7))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_val == 0:
        svg_parts.append(render_no_data_overlay(width, height))

    svg_parts.append('</svg>')

    pct_studied = (days_studied_count / max_day * 100.0) if max_day > 0 else 0.0
    unit_label = "minutes" if show_time else "reviews"
    rate_label = "minutes/day" if show_time else "reviews/day"
    val_str = f"{total_val:.1f} {unit_label}" if show_time else f"{int(total_val)} {unit_label}"
    avg_str = f"{total_val / max_day:.1f} {rate_label}" if max_day > 0 else f"0 {rate_label}"

    summary = [
        {"label": tr.statistics_days_studied(), "value": f"{days_studied_count} of {max_day} ({pct_studied:.2f}%)"},
        {"label": "Total", "value": val_str},
        {"label": tr.statistics_average_for_days_studied(), "value": f"{total_val / max(days_studied_count, 1):.1f} {rate_label}"},
        {"label": tr.statistics_average_over_period(), "value": avg_str},
    ]

    subtitle = tr.statistics_reviews_time_subtitle() if show_time else tr.statistics_reviews_count_subtitle()

    return {
        "title": tr.statistics_reviews_title(),
        "subtitle": subtitle,
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_val > 0,
        "show_time": show_time,
        "days_range": days_range,
    }


def generate_card_counts_chart(
    counts: stats_pb2.GraphsResponse.CardCounts,
    separate_inactive: bool = True,
) -> dict[str, Any]:
    """Generate Card Counts donut chart and summary table matching legacy."""
    # When separate_inactive is True, use excluding_inactive (so suspended/buried are separate).
    # When False, use including_inactive (all cards grouped into 5 active states).
    c = counts.excluding_inactive if separate_inactive else counts.including_inactive
    total = c.newCards + c.learn + c.relearn + c.young + c.mature + c.suspended + c.buried

    categories = [
        ("New", c.newCards, "#6baed6", "rgb(107, 174, 214)", '"is:new"'),
        ("Learning", c.learn, "#fd8d3c", "rgb(253, 141, 60)", '(-"is:review" AND "is:learn")'),
        ("Relearning", c.relearn, "#fb6a4a", "rgb(251, 106, 74)", '("is:review" AND "is:learn")'),
        ("Young", c.young, "#74c476", "rgb(116, 196, 118)", '("is:review" AND -"is:learn") AND "prop:ivl<21"'),
        ("Mature", c.mature, "#31a354", "rgb(49, 163, 84)", '("is:review" -"is:learn") AND "prop:ivl>=21"'),
    ]
    if separate_inactive:
        categories.extend([
            ("Suspended", c.suspended, "#FFDC41", "rgb(255, 220, 65)", '"is:suspended"'),
            ("Buried", c.buried, "grey", "grey", '"is:buried"'),
        ])

    width = 225
    height = 250
    cx = 105
    cy = 125
    outer_r = 105.0

    svg_parts = [f'<svg viewBox="0 0 {width} {height}" class="counts-svg">']
    svg_parts.append(f'<g class="counts" transform="translate({cx},{cy})">')

    cur_angle = 0.0
    for name, cnt, fill_hex, _, _ in categories:
        if total > 0 and cnt > 0:
            slice_angle = (cnt / total) * 2 * math.pi
            d = render_pie_slice(cur_angle, cur_angle + slice_angle, outer_r)
            cur_angle += slice_angle
            svg_parts.append(f'  <path fill="{fill_hex}" d="{d}"></path>')
        else:
            svg_parts.append(f'  <path fill="{fill_hex}" d="M0,-105L0,0Z"></path>')

    svg_parts.append('</g>')
    if total == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    table_rows = []
    for name, cnt, _, color_rgb, query in categories:
        pct = f"{cnt / total * 100:.2f}%" if total > 0 else "0%"
        table_rows.append({
            "name": name,
            "count": cnt,
            "percent": pct,
            "color": color_rgb,
            "query": query,
        })
    table_rows.append({
        "name": "Total",
        "count": total,
        "percent": "",
        "color": None,
        "query": "",
    })

    return {
        "title": tr.statistics_counts_title(),
        "subtitle": "",
        "svg": "\n".join(svg_parts),
        "rows": table_rows,
        "total": total,
        "separate_inactive": separate_inactive,
    }


def generate_intervals_chart(
    intervals: stats_pb2.GraphsResponse.Intervals,
    days_range_or_percentile: str = "95",
) -> dict[str, Any]:
    """Generate Review Intervals distribution chart with percentiles and median."""
    imap = dict(intervals.intervals)
    all_intervals: list[float] = []
    for ivl, cnt in imap.items():
        all_intervals.extend([float(ivl)] * cnt)

    total_cards = len(all_intervals)
    median_ivl = _compute_median(all_intervals) if all_intervals else 0.0

    if days_range_or_percentile == "month":
        max_interval = 30
    elif days_range_or_percentile == "50":
        max_interval = int(math.ceil(_compute_percentile(all_intervals, 0.5))) if all_intervals else 30
    elif days_range_or_percentile == "95":
        max_interval = int(math.ceil(_compute_percentile(all_intervals, 0.95))) if all_intervals else 30
    else:  # "all"
        max_interval = max(imap.keys()) if imap else 30

    max_interval = max(max_interval, 1)

    data: list[dict[str, Any]] = []
    max_count = 0
    running_tot = 0

    for d in range(max_interval + 1):
        c = imap.get(d, 0)
        running_tot += c
        max_count = max(max_count, c)
        pct = (running_tot / total_cards * 100.0) if total_cards > 0 else 0.0
        tt = f"Interval: {d} days&#10;Cards: {c}&#10;Running total: {pct:.1f}%"
        data.append({"interval": d, "count": c, "tooltip": tt})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right


    x_scale = LinearScale((0, max_interval), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_count, 1)), (height - margin_bottom, margin_top))
    bar_w = chart_w / max(len(data), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append(render_bars(data, "interval", "count", x_scale, y_scale, width=bar_w, fill="#6baed6"))

    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=7))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_cards == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    summary = []
    if total_cards > 0:
        summary.append({"label": tr.statistics_median_interval(), "value": f"{int(round(median_ivl))} days"})

    return {
        "title": tr.statistics_intervals_title(),
        "subtitle": tr.statistics_intervals_subtitle(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_cards > 0,
        "range_choice": days_range_or_percentile,
    }


def generate_ease_chart(eases: stats_pb2.GraphsResponse.Eases) -> dict[str, Any]:
    """Generate Card Ease distribution chart."""
    emap = dict(eases.eases)
    all_eases: list[float] = []
    for e_val, cnt in emap.items():
        all_eases.extend([float(e_val)] * cnt)

    total_cards = len(all_eases)
    median_e = _compute_median(all_eases) if all_eases else 0.0

    max_ease = max(emap.keys()) if emap else 300
    max_ease = max(max_ease, 320)

    data: list[dict[str, Any]] = []
    max_c = max(emap.values()) if emap else 0

    for ease_val in range(130, max_ease + 10, 10):
        c = emap.get(ease_val, 0)
        data.append({"ease": ease_val, "count": c, "tooltip": f"Ease {ease_val}%: {c} cards"})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right

    x_scale = LinearScale((130, max_ease), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_c, 1)), (height - margin_bottom, margin_top))
    bar_w = chart_w / max(len(data), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append(render_bars(data, "ease", "count", x_scale, y_scale, width=bar_w, fill="#74c476"))
    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=6, tick_format=lambda x: f"{int(round(x))}%"))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_cards == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    summary = []
    if total_cards > 0:
        # eases.average is already in percentage units (e.g. 250.0)
        avg_val = eases.average if eases.average > 1.0 else eases.average * 100.0
        summary.append({"label": tr.statistics_average_ease(), "value": f"{avg_val:.0f}%"})
        summary.append({"label": tr.statistics_median_ease(), "value": f"{int(round(median_e))}%"})

    return {
        "title": tr.statistics_card_ease_title(),
        "subtitle": tr.statistics_card_ease_subtitle(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_cards > 0,
    }


def generate_difficulty_chart(difficulty: stats_pb2.GraphsResponse.Eases) -> dict[str, Any]:
    """Generate Difficulty distribution chart for FSRS."""
    dmap = dict(difficulty.eases)
    all_d: list[float] = []
    for d_val, cnt in dmap.items():
        all_d.extend([float(d_val)] * cnt)

    total_cards = len(all_d)
    median_d = _compute_median(all_d) if all_d else 0.0

    data: list[dict[str, Any]] = []
    max_c = max(dmap.values()) if dmap else 0

    for d_pct in range(0, 101, 5):
        c = dmap.get(d_pct, 0)
        data.append({"pct": d_pct, "count": c, "tooltip": f"Difficulty {d_pct}%: {c} cards"})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right

    x_scale = LinearScale((0, 100), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_c, 1)), (height - margin_bottom, margin_top))
    bar_w = chart_w / max(len(data), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append(render_bars(data, "pct", "count", x_scale, y_scale, width=bar_w, fill="rgb(251, 106, 74)"))
    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=6, tick_format=lambda x: f"{int(round(x))}%"))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_cards == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    summary = []
    if total_cards > 0:
        avg_val = difficulty.average if difficulty.average > 1.0 else difficulty.average * 100.0
        summary.append({"label": tr.statistics_average_difficulty(), "value": f"{avg_val:.0f}%"})
        summary.append({"label": tr.statistics_median_difficulty(), "value": f"{int(round(median_d))}%"})

    return {
        "title": tr.statistics_card_difficulty_title(),
        "subtitle": tr.statistics_card_difficulty_subtitle2(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_cards > 0,
    }


def generate_retrievability_chart(retrievability: stats_pb2.GraphsResponse.Retrievability) -> dict[str, Any]:
    """Generate Retrievability distribution chart for FSRS."""
    rmap = dict(retrievability.retrievability)
    total_cards = sum(rmap.values())

    data: list[dict[str, Any]] = []
    max_c = max(rmap.values()) if rmap else 0

    for r_pct in range(0, 101, 5):
        c = rmap.get(r_pct, 0)
        data.append({"pct": r_pct, "count": c, "tooltip": f"Retrievability {r_pct}%: {c} cards"})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right

    x_scale = LinearScale((0, 100), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_c, 1)), (height - margin_bottom, margin_top))
    bar_w = chart_w / max(len(data), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append(render_bars(data, "pct", "count", x_scale, y_scale, width=bar_w, fill="rgb(49, 163, 84)"))
    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=6, tick_format=lambda x: f"{int(round(x))}%"))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_cards == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    summary = []
    if total_cards > 0:
        avg_val = retrievability.average if retrievability.average > 1.0 else retrievability.average * 100.0
        summary.append({"label": tr.statistics_average_retrievability(), "value": f"{avg_val:.0f}%"})
        summary.append({
            "label": tr.statistics_estimated_total_knowledge(),
            "value": f"{int(round(retrievability.sum_by_card))} cards / {int(round(retrievability.sum_by_note))} notes",
        })

    return {
        "title": tr.statistics_card_retrievability_title(),
        "subtitle": tr.statistics_retrievability_subtitle(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_cards > 0,
    }


def generate_stability_chart(stability: stats_pb2.GraphsResponse.Intervals, range_choice: str = "95") -> dict[str, Any]:
    """Generate Stability distribution chart for FSRS."""
    smap = dict(stability.intervals)
    all_s: list[float] = []
    for ivl, cnt in smap.items():
        all_s.extend([float(ivl)] * cnt)

    total_cards = len(all_s)
    median_s = _compute_median(all_s) if all_s else 0.0

    if range_choice == "month":
        max_days = 30
    elif range_choice == "50":
        max_days = int(math.ceil(_compute_percentile(all_s, 0.5))) if all_s else 30
    elif range_choice == "95":
        max_days = int(math.ceil(_compute_percentile(all_s, 0.95))) if all_s else 30
    else:
        max_days = max(smap.keys()) if smap else 30

    max_days = max(max_days, 1)

    data: list[dict[str, Any]] = []
    max_c = 0
    for d in range(max_days + 1):
        c = smap.get(d, 0)
        max_c = max(max_c, c)
        data.append({"days": d, "count": c, "tooltip": f"Stability: {d} days: {c} cards"})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right

    x_scale = LinearScale((0, max_days), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_c, 1)), (height - margin_bottom, margin_top))
    bar_w = chart_w / max(len(data), 1)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append(render_bars(data, "days", "count", x_scale, y_scale, width=bar_w, fill="rgb(107, 174, 214)"))
    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=7))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_cards == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    summary = []
    if total_cards > 0:
        summary.append({"label": tr.statistics_median_stability(), "value": f"{int(round(median_s))} days"})

    return {
        "title": tr.statistics_card_stability_title(),
        "subtitle": tr.statistics_card_stability_subtitle(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_cards > 0,
        "range_choice": range_choice,
    }


def generate_hours_chart(
    hours_list: Sequence[stats_pb2.GraphsResponse.Hours.Hour],
    days_range: int = 365,
) -> dict[str, Any]:
    """Generate Hourly Breakdown chart."""
    data: list[dict[str, Any]] = []
    max_tot = 0

    for h in range(24):
        item = hours_list[h] if h < len(hours_list) else None
        tot = item.total if item else 0
        corr = item.correct if item else 0
        pct = (corr / tot * 100.0) if tot > 0 else 0.0
        max_tot = max(max_tot, tot)
        tt = f"Hour {h}:00&#10;Reviews: {tot}&#10;Correct: {corr} ({pct:.1f}%)"
        data.append({"hour": h, "total": tot, "correct": corr, "pct": pct, "tooltip": tt})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right

    x_scale = LinearScale((0, 23), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_tot, 1)), (height - margin_bottom, margin_top))
    y2_scale = LinearScale((0, 100), (height - margin_bottom, margin_top))

    bar_w = chart_w / 24.0

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']

    svg_parts.append('<g class="bars">')
    for d in data:
        bx = x_scale(d["hour"])
        by = y_scale(d["total"])
        bh = (height - margin_bottom) - by
        tt = d["tooltip"]
        svg_parts.append(
            f'  <rect rx="1" x="{bx:.2f}" y="{by:.2f}" width="{bar_w:.2f}" height="{bh:.2f}" fill="rgb(227, 238, 249)" data-tooltip="{tt}"></rect>'
        )
    svg_parts.append('</g>')

    line_points = [(x_scale(d["hour"]) + bar_w / 2.0, y2_scale(d["pct"])) for d in data if d["total"] > 0]
    if line_points:
        svg_parts.append(render_line(line_points, stroke="rgb(24, 100, 170)", stroke_width=2.0))

    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, ticks=list(range(24))))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y2_scale, width - margin_right, right=True, tick_format=lambda y: f"{int(round(y))}%", ticks=[0, 20, 40, 60, 80, 100], css_class="y2-ticks"))

    if max_tot == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    return {
        "title": tr.statistics_hours_title(),
        "subtitle": tr.statistics_hours_subtitle(),
        "svg": "\n".join(svg_parts),
        "has_data": max_tot > 0,
        "days_range": days_range,
    }


def generate_buttons_chart(
    btn_counts: stats_pb2.GraphsResponse.Buttons.ButtonCounts,
    days_range: int = 365,
) -> dict[str, Any]:
    """Generate Answer Buttons chart."""
    categories = ["Learning", "Young", "Mature"]
    btn_colors = [
        "rgb(165, 0, 38)",
        "rgb(253, 190, 112)",
        "rgb(182, 224, 118)",
        "rgb(0, 104, 55)",
    ]

    total_clicks = 0
    cat_data = []

    for name in categories:
        counts = list(getattr(btn_counts, name.lower(), []))
        while len(counts) < 4:
            counts.append(0)
        tot = sum(counts)
        total_clicks += tot
        cat_data.append({"category": name, "counts": counts, "total": tot})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25


    b_scale = BandScale(categories, (margin_left, width - margin_right), padding_inner=0.2)
    max_tot = max(cd["total"] for cd in cat_data) if cat_data else 0
    y_scale = LinearScale((0, max(max_tot, 1)), (height - margin_bottom, margin_top))

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']

    for cd in cat_data:
        bx = b_scale(cd["category"])
        bw = b_scale.bandwidth
        cur_y = height - margin_bottom
        for b_idx in range(4):
            val = cd["counts"][b_idx]
            if val <= 0:
                continue
            bh = ((height - margin_bottom) - margin_top) * (val / max(max_tot, 1))
            top_y = cur_y - bh
            color = btn_colors[b_idx]
            pct = (val / cd["total"] * 100.0) if cd["total"] > 0 else 0.0
            tt = f"{cd['category']} Button {b_idx + 1}: {val} ({pct:.1f}%)"
            svg_parts.append(
                f'  <rect rx="1" x="{bx:.2f}" y="{top_y:.2f}" width="{bw:.2f}" height="{bh:.2f}" fill="{color}" data-tooltip="{tt}"></rect>'
            )
            cur_y = top_y

    svg_parts.append(render_x_axis(b_scale, height - margin_bottom))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_clicks == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    return {
        "title": tr.statistics_answer_buttons_title(),
        "subtitle": tr.statistics_answer_buttons_subtitle(),
        "svg": "\n".join(svg_parts),
        "has_data": total_clicks > 0,
        "days_range": days_range,
    }


def generate_added_chart(
    added: stats_pb2.GraphsResponse.Added,
    days_range: int = 30,
) -> dict[str, Any]:
    """Generate Added new cards history chart."""
    amap = dict(added.added)
    max_day = days_range if days_range > 0 else (max(abs(k) for k in amap.keys()) if amap else 30)
    max_day = max(max_day, 1)

    items: list[dict[str, Any]] = []
    total_added = 0
    max_c = 0

    for d in range(-max_day, 1):
        c = amap.get(d, 0)
        total_added += c
        max_c = max(max_c, c)
        items.append({"day": d, "count": c, "tooltip": f"{-d} days ago: {c} cards added"})

    width = 600
    height = 250
    margin_left = 70
    margin_right = 70
    margin_top = 20
    margin_bottom = 25
    chart_w = width - margin_left - margin_right

    x_scale = LinearScale((-max_day, 0), (margin_left, width - margin_right))
    y_scale = LinearScale((0, max(max_c, 1)), (height - margin_bottom, margin_top))
    bar_w = chart_w / max(len(items), 1)

    c1 = (177, 210, 232)
    c2 = (47, 126, 188)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}">']
    svg_parts.append('<g class="bars">')
    for idx, item in enumerate(items):
        bx = x_scale(item["day"])
        by = y_scale(item["count"])
        bh = (height - margin_bottom) - by
        t = idx / max(len(items) - 1, 1)
        fill = interpolate_color(c1, c2, t)
        tt = item["tooltip"]
        svg_parts.append(
            f'  <rect rx="1" x="{bx:.2f}" y="{by:.2f}" width="{bar_w:.2f}" height="{bh:.2f}" fill="{fill}" data-tooltip="{tt}"></rect>'
        )
    svg_parts.append('</g>')

    svg_parts.append(render_x_axis(x_scale, height - margin_bottom, tick_count=7))
    svg_parts.append(render_y_axis(y_scale, margin_left, tick_count=5))
    svg_parts.append(render_y_axis(y_scale, width - margin_right, right=True, tick_count=5, css_class="y2-ticks"))

    if total_added == 0:
        svg_parts.append(render_no_data_overlay(width, height))
    svg_parts.append('</svg>')

    avg_added = total_added / max_day if max_day > 0 else 0
    summary = [
        {"label": "Total", "value": f"{total_added} cards"},
        {"label": "Average", "value": f"{avg_added:.1f} cards/day" if avg_added >= 1.0 else f"{int(round(avg_added))} cards/day"},
    ]

    return {
        "title": tr.statistics_added_title(),
        "subtitle": tr.statistics_added_subtitle(),
        "svg": "\n".join(svg_parts),
        "summary": summary,
        "has_data": total_added > 0,
        "days_range": days_range,
    }


def generate_retention_chart(
    tr_stats: stats_pb2.GraphsResponse.TrueRetentionStats,
    filter_mode: str = "summary",  # "young", "mature", "all", "summary"
) -> dict[str, Any]:
    # Legacy yn(t, e) defines 5 rows for standard summary view:
    # Today, Yesterday, Last week, Last month, Last year
    periods = [
        (tr.statistics_true_retention_today(), tr_stats.today),
        (tr.statistics_true_retention_yesterday(), tr_stats.yesterday),
        (tr.statistics_true_retention_week(), tr_stats.week),
        (tr.statistics_true_retention_month(), tr_stats.month),
        (tr.statistics_true_retention_year(), tr_stats.year),
    ]
    table_rows = []
    has_any_data = False

    for label, item in periods:
        y_tot = item.young_passed + item.young_failed
        m_tot = item.mature_passed + item.mature_failed
        tot_passed = item.young_passed + item.mature_passed
        tot_all = y_tot + m_tot

        if tot_all > 0:
            has_any_data = True

        y_ret = f"{item.young_passed / y_tot * 100:.1f}%" if y_tot > 0 else "N/A"
        m_ret = f"{item.mature_passed / m_tot * 100:.1f}%" if m_tot > 0 else "N/A"
        t_ret = f"{tot_passed / tot_all * 100:.1f}%" if tot_all > 0 else "N/A"

        table_rows.append({
            "period": label,
            "young": y_ret,
            "mature": m_ret,
            "total": t_ret,
            "count": tot_all,
            "young_passed": item.young_passed,
            "young_failed": item.young_failed,
            "mature_passed": item.mature_passed,
            "mature_failed": item.mature_failed,
            "total_passed": tot_passed,
            "total_failed": tot_all - tot_passed,
        })

    return {
        "title": tr.statistics_true_retention_title(),
        "subtitle": tr.statistics_true_retention_subtitle(),
        "rows": table_rows,
        "has_data": has_any_data,
        "filter_mode": filter_mode,
    }


def make_router(get_service: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/graphs", response_class=HTMLResponse)
    async def graphs_page(
        request: Request,
        search: str = "deck:current",
        scope: str = "deck",
        days: int = 365,
    ) -> Response:
        service = get_service()

        def _get_graphs(col):
            actual_search = "" if scope == "collection" else search
            g = col._backend.graphs(search=actual_search, days=days)
            prefs = col._backend.get_graph_preferences()
            return g, prefs

        g_resp, prefs = await service.run(_get_graphs)

        # Default per-chart ranges match legacy: 1 month (30 days) independently of global days
        future_due_range = 30
        reviews_range = 30
        added_range = 30
        hours_range = 365
        buttons_range = 365

        hours_data_src = g_resp.hours.one_year
        buttons_data_src = g_resp.buttons.one_year
        today_data = generate_today_stats(g_resp.today)
        future_due_data = generate_future_due_chart(g_resp.future_due, range_days=future_due_range, show_backlog=prefs.future_due_show_backlog)
        calendar_data = generate_calendar_chart(g_resp.reviews, year=2026)
        reviews_data = generate_reviews_chart(g_resp.reviews, days_range=reviews_range, show_time=False)
        card_counts_data = generate_card_counts_chart(g_resp.card_counts, separate_inactive=prefs.card_counts_separate_inactive)
        intervals_data = generate_intervals_chart(g_resp.intervals, days_range_or_percentile="95")
        ease_data = generate_ease_chart(g_resp.eases)
        retention_data = generate_retention_chart(g_resp.true_retention, filter_mode="summary")
        hours_data = generate_hours_chart(hours_data_src, days_range=hours_range)
        buttons_data = generate_buttons_chart(buttons_data_src, days_range=buttons_range)
        added_data = generate_added_chart(g_resp.added, days_range=added_range)

        retrievability_data = generate_retrievability_chart(g_resp.retrievability) if g_resp.fsrs else None
        stability_data = generate_stability_chart(g_resp.stability, range_choice="95") if g_resp.fsrs else None
        difficulty_data = generate_difficulty_chart(g_resp.difficulty) if g_resp.fsrs else None

        body = templating.render(
            "pages/graphs.html.jinja",
            request=request,
            tr=tr,
            search=search,
            scope=scope,
            days=days,
            separate_inactive=prefs.card_counts_separate_inactive,
            show_backlog=prefs.future_due_show_backlog,
            today=today_data,
            future_due=future_due_data,
            calendar=calendar_data,
            reviews=reviews_data,
            card_counts=card_counts_data,
            intervals=intervals_data,
            ease=ease_data,
            retention=retention_data,
            hours=hours_data,
            buttons=buttons_data,
            added=added_data,
            fsrs_enabled=g_resp.fsrs,
            retrievability=retrievability_data,
            stability=stability_data,
            difficulty=difficulty_data,
        )

        return HTMLResponse(
            render_page(
                context="graphs",
                body=body,
            )
        )

    @router.post("/graphs/update")
    async def update_graphs(
        request: Request,
        payload: ReadSignals,
    ) -> Response:
        service = get_service()
        signals = payload if isinstance(payload, dict) else {}

        search = signals.get("search", "deck:current")
        scope = signals.get("scope", "deck")
        days = int(signals.get("days", 365))
        separate_inactive = bool(signals.get("separate_inactive", True))
        show_backlog = bool(signals.get("show_backlog", True))

        # Per-chart scoped toggles
        future_due_range = int(signals.get("future_due_range", 30))
        reviews_range = int(signals.get("reviews_range", 30))
        reviews_show_time = bool(signals.get("reviews_show_time", False))
        added_range = int(signals.get("added_range", 30))
        intervals_range = str(signals.get("intervals_range", "95"))
        stability_range = str(signals.get("stability_range", "95"))
        hours_range = int(signals.get("hours_range", days))
        buttons_range = int(signals.get("buttons_range", days))
        calendar_year = int(signals.get("calendar_year", 2026))
        retention_mode = str(signals.get("retention_mode", "summary"))

        def _fetch_and_set(col):
            prefs = col._backend.get_graph_preferences()
            prefs.card_counts_separate_inactive = separate_inactive
            prefs.future_due_show_backlog = show_backlog
            col._backend.set_graph_preferences(prefs)

            actual_search = "" if scope == "collection" else search
            return col._backend.graphs(search=actual_search, days=days), prefs

        g_resp, prefs = await service.run(_fetch_and_set)

        # Select hours / buttons source based on per-chart range
        if hours_range <= 30:
            h_src = g_resp.hours.one_month
        elif hours_range <= 90:
            h_src = g_resp.hours.three_months
        elif hours_range <= 365:
            h_src = g_resp.hours.one_year
        else:
            h_src = g_resp.hours.all_time

        if buttons_range <= 30:
            b_src = g_resp.buttons.one_month
        elif buttons_range <= 90:
            b_src = g_resp.buttons.three_months
        elif buttons_range <= 365:
            b_src = g_resp.buttons.one_year
        else:
            b_src = g_resp.buttons.all_time

        today_data = generate_today_stats(g_resp.today)
        future_due_data = generate_future_due_chart(g_resp.future_due, range_days=future_due_range, show_backlog=show_backlog)
        calendar_data = generate_calendar_chart(g_resp.reviews, year=calendar_year)
        reviews_data = generate_reviews_chart(g_resp.reviews, days_range=reviews_range, show_time=reviews_show_time)
        card_counts_data = generate_card_counts_chart(g_resp.card_counts, separate_inactive=separate_inactive)
        intervals_data = generate_intervals_chart(g_resp.intervals, days_range_or_percentile=intervals_range)
        ease_data = generate_ease_chart(g_resp.eases)
        retention_data = generate_retention_chart(g_resp.true_retention, filter_mode=retention_mode)
        hours_data = generate_hours_chart(h_src, days_range=hours_range)
        buttons_data = generate_buttons_chart(b_src, days_range=buttons_range)
        added_data = generate_added_chart(g_resp.added, days_range=added_range)

        retrievability_data = generate_retrievability_chart(g_resp.retrievability) if g_resp.fsrs else None
        stability_data = generate_stability_chart(g_resp.stability, range_choice=stability_range) if g_resp.fsrs else None
        difficulty_data = generate_difficulty_chart(g_resp.difficulty) if g_resp.fsrs else None

        updated_html = templating.render(
            "pages/graphs_content.html.jinja",
            tr=tr,
            today=today_data,
            future_due=future_due_data,
            calendar=calendar_data,
            reviews=reviews_data,
            card_counts=card_counts_data,
            intervals=intervals_data,
            ease=ease_data,
            retention=retention_data,
            hours=hours_data,
            buttons=buttons_data,
            added=added_data,
            fsrs_enabled=g_resp.fsrs,
            retrievability=retrievability_data,
            stability=stability_data,
            difficulty=difficulty_data,
        )

        return DatastarResponse(SSE.patch_elements(updated_html, selector="#graphs-cards-container"))

    return router
