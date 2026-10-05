"""Card Info page router and helpers for strangler-fig migration.

Serves /card-info/{ids:path}.
"""

from __future__ import annotations
import math
import datetime
import json
from typing import Any, Callable, cast
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator as SSE
from ankiweb.core.i18n import tr

# Constants matching upstream
SECONDS = 0
MINUTES = 1
HOURS = 2
DAYS = 3
MONTHS = 4
YEARS = 5

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
YEAR = 365 * DAY
MONTH = YEAR / 12


def _unit_size(unit: int) -> float:
    if unit == SECONDS:
        return 1.0
    if unit == MINUTES:
        return float(MINUTE)
    if unit == HOURS:
        return float(HOUR)
    if unit == DAYS:
        return float(DAY)
    if unit == MONTHS:
        return float(MONTH)
    if unit == YEARS:
        return float(YEAR)
    return 1.0


def _pick_unit(t: float) -> int:
    t = abs(t)
    if t < MINUTE:
        return SECONDS
    if t < HOUR:
        return MINUTES
    if t < DAY:
        return HOURS
    if t < MONTH:
        return DAYS
    if t < YEAR:
        return MONTHS
    return YEARS


def format_timespan(
    t: float, short: bool = False, exact: bool = True, max_unit: int = YEARS
) -> str:
    """Replicates upstream timeSpan(t, short, exact, maxUnit)."""
    r = min(_pick_unit(t), max_unit)
    n = t / _unit_size(r)
    if not exact and r < MONTHS:
        n = round(n)
    else:
        if isinstance(n, float) and n.is_integer():
            n = int(n)
        elif isinstance(n, float):
            n = round(n, 2)
            if n.is_integer():
                n = int(n)

    if short:
        lookup = {
            SECONDS: tr.statistics_elapsed_time_seconds,
            MINUTES: tr.statistics_elapsed_time_minutes,
            HOURS: tr.statistics_elapsed_time_hours,
            DAYS: tr.statistics_elapsed_time_days,
            MONTHS: tr.statistics_elapsed_time_months,
            YEARS: tr.statistics_elapsed_time_years,
        }
    else:
        lookup = {
            SECONDS: tr.scheduling_time_span_seconds,
            MINUTES: tr.scheduling_time_span_minutes,
            HOURS: tr.scheduling_time_span_hours,
            DAYS: tr.scheduling_time_span_days,
            MONTHS: tr.scheduling_time_span_months,
            YEARS: tr.scheduling_time_span_years,
        }
    return lookup[r](amount=cast(int, n))


def format_date(timestamp: int | float) -> str:
    dt = datetime.datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d")


def format_time(timestamp: int | float) -> str:
    dt = datetime.datetime.fromtimestamp(timestamp)
    return dt.strftime("%H:%M")


def _review_kind_text(kind: int) -> str:
    if kind == 0:
        return tr.card_stats_review_log_type_learn()
    if kind == 1:
        return tr.card_stats_review_log_type_review()
    if kind == 2:
        return tr.card_stats_review_log_type_relearn()
    if kind == 3:
        return tr.card_stats_review_log_type_filtered()
    if kind == 4:
        return tr.card_stats_review_log_type_manual()
    if kind == 5:
        return tr.card_stats_review_log_type_rescheduled()
    return ""


def _review_kind_class(kind: int) -> str:
    if kind == 0:
        return "revlog-learn"
    if kind == 1:
        return "revlog-review"
    if kind == 2:
        return "revlog-relearn"
    return ""


def _ease_text(ease: int) -> str:
    if ease == 0:
        return ""
    u = ease / 10.0
    if u <= 110:
        return f"D:{(u - 10):.0f}%"
    return f"{u:.0f}%"


def _is_revlog_counted(kind: int, ease: int) -> bool:
    return kind != 4 and kind != 5 and (kind != 3 or ease != 0)


def _fsrs_decay(stats_proto) -> float:
    params = list(stats_proto.fsrs_params)
    if not params:
        return 0.1542
    if len(params) < 21:
        return 0.5
    return params[20] if params[20] is not None else 0.1542


def _fsrs_retrievability(stability: float, elapsed_days: float, decay: float) -> float:
    if stability <= 0:
        return 0.0
    factor = math.pow(0.9, 1.0 / -decay) - 1.0
    val = (elapsed_days / stability) * factor + 1.0
    if val <= 0:
        return 0.0
    return math.pow(val, -decay)


def build_card_data(stats_proto, selected_range: int = -1) -> dict[str, Any]:
    if stats_proto is None:
        return {}

    card_id = stats_proto.card_id
    rows = []

    # 1. Added
    rows.append({"label": tr.card_stats_added(), "value": format_date(stats_proto.added)})

    # 2. First review
    if stats_proto.HasField("first_review"):
        rows.append({"label": tr.card_stats_first_review(), "value": format_date(stats_proto.first_review)})

    # 3. Latest review
    if stats_proto.HasField("latest_review"):
        rows.append({"label": tr.card_stats_latest_review(), "value": format_date(stats_proto.latest_review)})

    # 4. Due date
    if stats_proto.HasField("due_date"):
        rows.append({"label": tr.statistics_due_date(), "value": format_date(stats_proto.due_date)})

    # 5. Due position
    if stats_proto.HasField("due_position"):
        rows.append({"label": tr.card_stats_new_card_position(), "value": stats_proto.due_position})

    # 6. Interval
    if stats_proto.interval:
        rows.append({"label": tr.card_stats_interval(), "value": format_timespan(stats_proto.interval * 86400)})

    # 7. Memory state vs Ease
    has_memory_state = stats_proto.HasField("memory_state")
    if has_memory_state:
        stab = stats_proto.memory_state.stability
        val_stab = format_timespan(stab * 86400, short=False, exact=False)
        if stab > 31:
            val_days = format_timespan(stab * 86400, short=False, exact=False, max_unit=DAYS)
            val_stab += f" ({val_days})"
        rows.append({"label": tr.card_stats_fsrs_stability(), "value": val_stab})

        diff = ((stats_proto.memory_state.difficulty - 1.0) / 9.0 * 100.0)
        rows.append({"label": tr.card_stats_fsrs_difficulty(), "value": f"{diff:.0f}%"})

        # Retrievability row: shown when fsrs_retrievability is set by backend
        if stats_proto.HasField("fsrs_retrievability") and stats_proto.fsrs_retrievability > 0:
            ret = stats_proto.fsrs_retrievability * 100.0
            rows.append({"label": tr.card_stats_fsrs_retrievability(), "value": f"{ret:.0f}%"})
    else:
        if stats_proto.ease and not stats_proto.HasField("desired_retention"):
            rows.append({"label": tr.card_stats_ease(), "value": f"{stats_proto.ease / 10.0:.0f}%"})

    # 8. Reviews & Lapses
    rows.append({"label": tr.card_stats_review_count(), "value": stats_proto.reviews})
    rows.append({"label": tr.card_stats_lapse_count(), "value": stats_proto.lapses})

    # 9. Times
    if stats_proto.total_secs:
        rows.append({"label": tr.card_stats_average_time(), "value": format_timespan(stats_proto.average_secs)})
        rows.append({"label": tr.card_stats_total_time(), "value": format_timespan(stats_proto.total_secs)})

    # 10. Card type & Notetype
    rows.append({"label": tr.card_stats_card_template(), "value": stats_proto.card_type})
    rows.append({"label": tr.card_stats_note_type(), "value": stats_proto.notetype})

    # 11. Deck
    if stats_proto.HasField("original_deck") and stats_proto.original_deck:
        deck_str = f"{stats_proto.deck} ({stats_proto.original_deck})"
    else:
        deck_str = stats_proto.deck
    rows.append({"label": tr.card_stats_deck_name(), "value": deck_str})

    # 12. Preset, Card ID, Note ID
    rows.append({"label": tr.card_stats_preset(), "value": stats_proto.preset})
    rows.append({"label": tr.card_stats_card_id(), "value": stats_proto.card_id})
    rows.append({"label": tr.card_stats_note_id(), "value": stats_proto.note_id})

    # 13. Custom data
    if stats_proto.custom_data:
        try:
            parsed = json.loads(stats_proto.custom_data)
            custom_str = " ".join(f"{k}={v}" for k, v in parsed.items())
        except Exception:
            custom_str = stats_proto.custom_data
        rows.append({"label": tr.card_stats_custom_data(), "value": custom_str})

    # Build revlogs
    raw_revlogs = list(stats_proto.revlog)
    revlog_rows = []
    for u, log in enumerate(raw_revlogs):
        m = None
        for s_idx in range(u + 1, len(raw_revlogs)):
            if _is_revlog_counted(raw_revlogs[s_idx].review_kind, raw_revlogs[s_idx].ease):
                m = raw_revlogs[s_idx]
                break
        elapsed = "N/A"
        if _is_revlog_counted(log.review_kind, log.ease):
            elapsed = format_timespan(log.time - m.time) if m else "0"

        rating_class = "revlog-ease1" if log.button_chosen == 1 else ""
        revlog_rows.append({
            "date": format_date(log.time),
            "time": format_time(log.time),
            "review_kind": _review_kind_text(log.review_kind),
            "review_kind_class": _review_kind_class(log.review_kind),
            "rating": log.button_chosen,
            "rating_class": rating_class,
            "interval": format_timespan(log.interval),
            "ease": _ease_text(log.ease),
            "taken_secs": format_timespan(log.taken_secs, short=True),
            "elapsed_time": elapsed,
        })

    # Forgetting curve SVG
    decay = _fsrs_decay(stats_proto)
    desired_retention = stats_proto.desired_retention if stats_proto.HasField("desired_retention") else 0.9
    curve_svg, max_span, sel_range = render_forgetting_curve_svg(raw_revlogs, desired_retention, decay, selected_range)

    return {
        "card_id": card_id,
        "rows": rows,
        "revlogs": revlog_rows,
        "fsrs_enabled": has_memory_state,
        "curve_svg": curve_svg,
        "max_span": max_span,
        "selected_range": sel_range,
        "show_time_selector": max_span > 7,
    }


def d3_bisect_right(a: list, x: float) -> int:
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid][2]:
            hi = mid
        else:
            lo = mid + 1
    return lo


_D3_SECOND = 1000
_D3_MINUTE = 60 * _D3_SECOND
_D3_HOUR = 60 * _D3_MINUTE
_D3_DAY = 24 * _D3_HOUR
_D3_WEEK = 7 * _D3_DAY
_D3_MONTH = 30 * _D3_DAY
_D3_YEAR = 365 * _D3_DAY

_D3_TIME_INTERVALS = [
    ("second", 1, _D3_SECOND),
    ("second", 5, 5 * _D3_SECOND),
    ("second", 15, 15 * _D3_SECOND),
    ("second", 30, 30 * _D3_SECOND),
    ("minute", 1, _D3_MINUTE),
    ("minute", 5, 5 * _D3_MINUTE),
    ("minute", 15, 15 * _D3_MINUTE),
    ("minute", 30, 30 * _D3_MINUTE),
    ("hour", 1, _D3_HOUR),
    ("hour", 3, 3 * _D3_HOUR),
    ("hour", 6, 6 * _D3_HOUR),
    ("hour", 12, 12 * _D3_HOUR),
    ("day", 1, _D3_DAY),
    ("day", 2, 2 * _D3_DAY),
    ("week", 1, _D3_WEEK),
    ("month", 1, _D3_MONTH),
    ("month", 3, 3 * _D3_MONTH),
    ("year", 1, _D3_YEAR),
]


def d3_time_ticks(start_dt: datetime.datetime, stop_dt: datetime.datetime, count: int = 5) -> list[datetime.datetime]:
    span_ms = (stop_dt.timestamp() - start_dt.timestamp()) * 1000.0
    if span_ms <= 0:
        return [start_dt]

    target = span_ms / max(1, count)
    p = d3_bisect_right(_D3_TIME_INTERVALS, target)
    if p == len(_D3_TIME_INTERVALS):
        unit, step, _ = _D3_TIME_INTERVALS[-1]
    elif p == 0:
        unit, step, _ = _D3_TIME_INTERVALS[0]
    else:
        if target / _D3_TIME_INTERVALS[p - 1][2] < _D3_TIME_INTERVALS[p][2] / target:
            unit, step, _ = _D3_TIME_INTERVALS[p - 1]
        else:
            unit, step, _ = _D3_TIME_INTERVALS[p]

    if unit == "second":
        curr = start_dt.replace(second=(start_dt.second // step) * step, microsecond=0)
        delta = datetime.timedelta(seconds=step)
    elif unit == "minute":
        curr = start_dt.replace(minute=(start_dt.minute // step) * step, second=0, microsecond=0)
        delta = datetime.timedelta(minutes=step)
    elif unit == "hour":
        curr = start_dt.replace(hour=(start_dt.hour // step) * step, minute=0, second=0, microsecond=0)
        delta = datetime.timedelta(hours=step)
    elif unit == "day":
        curr = start_dt.replace(day=((start_dt.day - 1) // step) * step + 1, hour=0, minute=0, second=0, microsecond=0)
        delta = datetime.timedelta(days=step)
    elif unit == "week":
        days_since_sunday = (start_dt.weekday() + 1) % 7
        curr = (start_dt - datetime.timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
        delta = datetime.timedelta(weeks=step)
    elif unit == "month":
        curr = start_dt.replace(month=((start_dt.month - 1) // step) * step + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        delta = None
    else:
        curr = start_dt.replace(year=(start_dt.year // step) * step, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        delta = None

    if curr < start_dt:
        if delta:
            curr += delta
        elif unit == "month":
            m = curr.month + step
            y = curr.year + (m - 1) // 12
            curr = curr.replace(year=y, month=((m - 1) % 12) + 1)
        else:
            curr = curr.replace(year=curr.year + step)

    ticks = []
    while curr <= stop_dt:
        ticks.append(curr)
        if delta:
            curr += delta
        elif unit == "month":
            m = curr.month + step
            y = curr.year + (m - 1) // 12
            curr = curr.replace(year=y, month=((m - 1) % 12) + 1)
        else:
            curr = curr.replace(year=curr.year + step)
    return ticks


def d3_format_time(d: datetime.datetime) -> str:
    """Matches d3.timeFormat default multi-scale tick formatter."""
    if d.microsecond != 0:
        return f".{int(d.microsecond / 1000):03d}"
    if d.second != 0:
        return f":{d.second:02d}"
    if d.minute != 0:
        return d.strftime("%I:%M")
    if d.hour != 0:
        return d.strftime("%I %p")
    if d.day != 1:
        return d.strftime("%b %d")
    if d.month != 1:
        return d.strftime("%B")
    return d.strftime("%Y")


def d3_linear_ticks(start: float, stop: float, count: int = 10) -> tuple[list[float], str]:
    """Matches d3.ticks and d3.tickFormat for scaleLinear."""
    step = (stop - start) / max(1, count)
    power = math.floor(math.log10(step))
    error = step / (10 ** power)
    if error >= math.sqrt(50):
        factor = 10
    elif error >= math.sqrt(10):
        factor = 5
    elif error >= math.sqrt(2):
        factor = 2
    else:
        factor = 1
    inc = factor * (10 ** power)
    precision = max(0, -math.floor(math.log10(inc)))

    nstart = math.ceil(start / inc) * inc
    nstop = math.floor(stop / inc) * inc

    ticks = []
    curr = nstart
    while curr <= nstop + inc * 0.5:
        ticks.append(round(curr, 8))
        curr += inc
    fmt = f"{{:.{precision}f}}"
    return ticks, fmt


def render_forgetting_curve_svg(
    raw_revlogs: list,
    desired_retention: float,
    decay: float,
    selected_range: int = -1,
    bounds: dict | None = None,
) -> tuple[str, float, int]:
    if bounds is None:
        bounds = {"width": 600, "height": 250, "marginLeft": 70, "marginRight": 70, "marginTop": 20, "marginBottom": 25}

    e = []
    for r in raw_revlogs:
        has_ms = r.HasField("memory_state")
        if (r.review_kind == 4 and r.ease == 0) or not has_ms:
            break
        e.append(r)
    e = [r for r in e if _is_revlog_counted(r.review_kind, r.ease)]

    if not e:
        return "", 0.0, 0

    now_ts = datetime.datetime.now().timestamp()
    t_days = (now_ts - e[-1].time) / 86400.0
    h_days = (now_ts - e[0].time) / 86400.0
    s_days = e[0].interval / 86400.0
    n_days = max(s_days * 1.5 - h_days, s_days * 0.5)
    max_span = t_days + n_days

    range_limits = {0: 7.0, 1: 30.0, 2: 365.0, 3: float("inf")}

    if selected_range == -1:
        if max_span > 365:
            selected_range = 3
        elif max_span > 30:
            selected_range = 2
        elif max_span > 7:
            selected_range = 1
        else:
            selected_range = 0

    active_span = min(max_span, range_limits.get(selected_range, 7.0))

    ta = 1000.0
    step = min(active_span / ta, 1.0)
    pts = []
    h = 0.0
    s = 0.0
    D = 0.0

    rev_rev = list(reversed(e))
    for m, u in enumerate(rev_rev):
        S = float(u.time)
        stab = float(u.memory_state.stability) if u.HasField("memory_state") else 0.0
        if m == 0:
            h = S
            s = stab
            pts.append({
                "time": S,
                "daysSinceFirstLearn": 0.0,
                "elapsedDaysSinceLastReview": 0.0,
                "retrievability": 100.0,
                "stability": s,
            })
            continue

        M = (S - h) / 86400.0
        elapsed_days = 0.0
        while elapsed_days < M - step:
            elapsed_days += step
            ret = _fsrs_retrievability(s, elapsed_days, decay)
            pts.append({
                "time": h + elapsed_days * 86400.0,
                "daysSinceFirstLearn": pts[-1]["daysSinceFirstLearn"] + step,
                "elapsedDaysSinceLastReview": elapsed_days,
                "retrievability": ret * 100.0,
                "stability": s,
            })
        D += M
        pts.append({
            "time": h + M * 86400.0,
            "daysSinceFirstLearn": D,
            "retrievability": 100.0,
            "elapsedDaysSinceLastReview": 0.0,
            "stability": s,
        })
        h = S
        s = stab

    if not pts:
        return "", max_span, selected_range

    elapsed_to_now = (now_ts - h) / 86400.0
    b = 0.0
    while b < elapsed_to_now - step:
        b += step
        ret = _fsrs_retrievability(s, b, decay)
        pts.append({
            "time": h + b * 86400.0,
            "daysSinceFirstLearn": pts[-1]["daysSinceFirstLearn"] + step,
            "elapsedDaysSinceLastReview": b,
            "retrievability": ret * 100.0,
            "stability": s,
        })
    D += elapsed_to_now
    ret_now = _fsrs_retrievability(s, elapsed_to_now, decay)
    pts.append({
        "time": now_ts,
        "daysSinceFirstLearn": D,
        "elapsedDaysSinceLastReview": elapsed_to_now,
        "retrievability": ret_now * 100.0,
        "stability": s,
    })

    x_future = active_span - elapsed_to_now
    E = 0.0
    while E < x_future:
        E += step
        ret = _fsrs_retrievability(s, b + E, decay)
        pts.append({
            "time": now_ts + E * 86400.0,
            "daysSinceFirstLearn": pts[-1]["daysSinceFirstLearn"] + step,
            "elapsedDaysSinceLastReview": elapsed_to_now + E,
            "retrievability": ret * 100.0,
            "stability": s,
        })

    pts = [p for p in pts if p["daysSinceFirstLearn"] <= active_span]
    if not pts:
        return "", max_span, selected_range

    min_time = pts[0]["time"]
    max_time = pts[-1]["time"]
    time_range = max_time - min_time if max_time > min_time else 1.0

    min_ret = min(p["retrievability"] for p in pts)
    E_min = max(0.0, 100.0 - 1.2 * (100.0 - min_ret))
    ret_range = 100.0 - E_min if 100.0 > E_min else 1.0

    w = bounds["width"]
    h_svg = bounds["height"]
    ml = bounds["marginLeft"]
    mr = bounds["marginRight"]
    mt = bounds["marginTop"]
    mb = bounds["marginBottom"]
    plot_w = w - ml - mr
    plot_h = h_svg - mt - mb

    def scale_x(t: float) -> float:
        return ml + ((t - min_time) / time_range) * plot_w

    def scale_y(ret: float) -> float:
        return (h_svg - mb) - ((ret - E_min) / ret_range) * plot_h

    past_pts = [p for p in pts if p["time"] <= now_ts]
    future_pts = [p for p in pts if p["time"] >= now_ts]

    def build_path_d(points: list) -> str:
        if not points:
            return ""
        d_parts = [f"M{scale_x(points[0]['time']):.3f},{scale_y(points[0]['retrievability']):.3f}"]
        for p in points[1:]:
            d_parts.append(f"L{scale_x(p['time']):.3f},{scale_y(p['retrievability']):.3f}")
        return "".join(d_parts)

    d_past = build_path_d(past_pts)
    d_future = build_path_d(future_pts)

    m_desired = desired_retention * 100.0
    y_desired = scale_y(m_desired)

    # Ticks for Y matching D3 linear scale
    y_ticks_vals, y_fmt = d3_linear_ticks(E_min, 100.0, 10)
    y_ticks_svg = []
    for yv in y_ticks_vals:
        yp = scale_y(yv)
        y_ticks_svg.append(
            f'<g class="tick" opacity="1" transform="translate(0,{yp:.1f})">'
            f'<line stroke="currentColor" x2="-6"></line>'
            f'<text fill="currentColor" x="-9" dy="0.32em">{y_fmt.format(yv)}</text>'
            f'</g>'
        )

    # Ticks for X matching D3 time scale
    dt_start = datetime.datetime.fromtimestamp(min_time)
    dt_stop = datetime.datetime.fromtimestamp(max_time)
    x_tick_dts = d3_time_ticks(dt_start, dt_stop, 5)
    x_ticks_svg = []
    for dt_tick in x_tick_dts:
        xp = scale_x(dt_tick.timestamp())
        fmt_str = d3_format_time(dt_tick)
        x_ticks_svg.append(
            f'<g class="tick" opacity="1" transform="translate({xp:.1f},0)">'
            f'<line stroke="currentColor" y2="6"></line>'
            f'<text fill="currentColor" y="9" dy="0.71em">{fmt_str}</text>'
            f'</g>'
        )

    desired_line_svg = ""
    if m_desired > E_min:
        desired_line_svg = f'<line class="desired-retention-line" x1="{ml}" x2="{w - mr}" y1="{y_desired:.1f}" y2="{y_desired:.1f}" stroke="steelblue" stroke-dasharray="4 4" stroke-width="1.2"></line>'

    svg_content = f"""<svg viewBox="0 0 {w} {h_svg}">
  <g class="x-ticks svelte-2itjvo" transform="translate(0, {h_svg - mb})" fill="none" font-size="10" font-family="sans-serif" text-anchor="middle" direction="ltr">
    <path class="domain" stroke="currentColor" d="M{ml + 0.5},0.5H{w - mr + 0.5}"></path>
    {''.join(x_ticks_svg)}
  </g>
  <g class="y-ticks svelte-2itjvo" transform="translate({ml},0)" fill="none" font-size="10" font-family="sans-serif" text-anchor="end" direction="ltr">
    <path class="domain" stroke="currentColor" d="M0.5,{h_svg - mb + 0.5}V{mt + 0.5}"></path>
    <text class="y-axis-title" transform="rotate(-90)" y="{-ml}" x="{-h_svg / 2}" font-size="1rem" dy="1.1em" fill="currentColor"></text>
    {''.join(y_ticks_svg)}
  </g>
  <g class="y2-ticks svelte-2itjvo" transform="translate({w - mr}, 0)"></g>
  <g class="no-data svelte-adkmdc" opacity="0">
    <rect x="0" y="0" width="{w}" height="{h_svg}" class="svelte-adkmdc"></rect>
    <text x="{w / 2}," y="{h_svg / 2}" class="svelte-adkmdc">NO DATA</text>
  </g>
  <linearGradient id="line-gradient" gradientUnits="userSpaceOnUse" x1="0" y1="{scale_y(0.0):.1f}" x2="0" y2="{scale_y(100.0):.1f}">
    <stop offset="0%" stop-color="tomato"></stop>
    <stop offset="{m_desired:.1f}%" stop-color="steelblue"></stop>
    <stop offset="100%" stop-color="green"></stop>
  </linearGradient>
  {f'<path class="forgetting-curve-line" fill="none" stroke="url(#line-gradient)" stroke-width="1.5" d="{d_past}"></path>' if d_past else ''}
  {f'<path class="forgetting-curve-line" fill="none" stroke="url(#line-gradient)" stroke-width="1.5" stroke-dasharray="4 4" d="{d_future}"></path>' if d_future else ''}
  {desired_line_svg}
  <line class="focus-line" y1="{mt}" y2="{h_svg - mb}" stroke="black" stroke-width="1" style="opacity: 0;"></line>
  <g class="hover-columns"></g>
</svg>"""

    return svg_content, max_span, selected_range


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/card-info/{ids:path}", response_class=HTMLResponse)
    async def card_info_page(ids: str, request: Request):
        service = get_service()
        show_revlog = request.query_params.get("revlog") != "0"
        show_curve = request.query_params.get("curve") != "0"

        parts = [p for p in ids.split("/") if p]
        cids = []
        for p in parts:
            if p.isdigit():
                if len(p) > 18:
                    # Huge int beyond 64-bit: legacy returns "int64 invalid: <p>"
                    return HTMLResponse(
                        render_page("card-info", f"int64 invalid: {p}")
                    )
                cids.append(int(p))

        if not cids:
            body = templating.render(
                "pages/card_info.html.jinja",
                is_multi=False,
                current_card={},
                previous_card={},
                show_revlog=show_revlog,
                show_curve=show_curve,
            )
            return HTMLResponse(render_page("card-info", body))

        if len(cids) == 1:
            cid = cids[0]
            try:
                stats_proto = await service.run(lambda col: col.card_stats_data(cid))
            except Exception:
                inconsistent_msg = (
                    "Your database appears to be in an inconsistent state. "
                    f"Please use the Check Database action. No such card: '{cid}'"
                )
                return HTMLResponse(render_page("card-info", inconsistent_msg))

            card_data = build_card_data(stats_proto)
            body = templating.render(
                "pages/card_info.html.jinja",
                is_multi=False,
                current_card=card_data,
                previous_card={},
                show_revlog=show_revlog,
                show_curve=show_curve,
            )
            return HTMLResponse(render_page("card-info", body))

        curr_id = cids[0]
        prev_id = cids[1]

        def fetch_both(col):
            c_p = col.card_stats_data(curr_id)
            p_p = col.card_stats_data(prev_id)
            return c_p, p_p

        try:
            c_proto, p_proto = await service.run(fetch_both)
        except Exception:
            # Determine which card failed
            def check_which(col):
                try:
                    col.card_stats_data(curr_id)
                except Exception:
                    return curr_id
                return prev_id

            missing_id = await service.run(check_which)
            inconsistent_msg = (
                "Your database appears to be in an inconsistent state. "
                f"Please use the Check Database action. No such card: '{missing_id}'"
            )
            return HTMLResponse(render_page("card-info", inconsistent_msg))

        c_data = build_card_data(c_proto)
        p_data = build_card_data(p_proto)

        body = templating.render(
            "pages/card_info.html.jinja",
            is_multi=True,
            current_title="Current",
            previous_title="Previous",
            current_card=c_data,
            previous_card=p_data,
            show_revlog=show_revlog,
            show_curve=show_curve,
        )
        return HTMLResponse(render_page("card-info", body))

    @router.post("/card-info/curve/{cid}")
    async def update_curve(cid: int, request: Request):
        service = get_service()
        range_val = int(request.query_params.get("range", 0))
        stats_proto = await service.run(lambda col: col.card_stats_data(cid))
        card_data = build_card_data(stats_proto, selected_range=range_val)

        chart_html = templating.render(
            "pages/card_info_components.html.jinja",
            comp_block=True,
            card_data=card_data,
        )
        return DatastarResponse(SSE.patch_elements(chart_html, selector=f"#curve-{cid}"))

    return router
