from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from typing import Any, cast

import anki.deck_config_pb2 as deck_cfg_pb
import anki.scheduler_pb2 as sched_pb
from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_pages.graph_svg import (
    LinearScale,
    render_line,
    render_no_data_overlay,
    render_x_axis,
    render_y_axis,
)

logger = logging.getLogger(__name__)

# Colors matching schemeCategory10 in d3
CATEGORY10 = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
]


def moving_average(values: list[float], window_size: int) -> list[float]:
    if not values:
        return []
    if window_size <= 1:
        return list(values)
    res = []
    for i in range(len(values)):
        sub = values[max(0, i - window_size + 1): i + 1]
        res.append(sum(sub) / len(sub))
    return res


def format_time_span(seconds: float) -> str:
    s = round(seconds)
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h = m // 60
    rem_m = m % 60
    return f"{h}h {rem_m}m" if rem_m else f"{h}h"


def render_simulation_svg(
    simulations: list[dict[str, Any]],
    subgraph: str,  # "count", "time", "memorized"
    smooth: bool = True,
    width: float = 600,
    height: float = 250,
    margin_top: float = 20,
    margin_right: float = 50,
    margin_bottom: float = 30,
    margin_left: float = 50,
) -> str:
    if not simulations:
        return render_no_data_overlay(width, height, "No simulation data")

    # Find max x (days)
    max_x = 0
    for s in simulations:
        max_x = max(max_x, s.get("days", len(s.get("counts", [])) - 1))
    if max_x <= 0:
        max_x = 1

    scale_x = LinearScale((0, max_x), (margin_left, width - margin_right))

    series_data: list[tuple[int, list[tuple[float, float]], str]] = []
    global_max_y = 0.0

    for idx, sim in enumerate(simulations):
        label = sim.get("label", idx + 1)
        color = CATEGORY10[(label - 1) % len(CATEGORY10)]
        days = sim.get("days", 365)
        window_size = max(1, math.ceil(days / 365)) if smooth else 1

        if subgraph == "time":
            raw_y = sim.get("time_costs", [])
        elif subgraph == "memorized":
            raw_y = sim.get("memorized", [])
        else:
            raw_y = sim.get("counts", [])

        y_vals = moving_average(raw_y, window_size) if smooth else raw_y
        for y in y_vals:
            global_max_y = max(global_max_y, y)

        series_data.append((label, [(float(i), float(y)) for i, y in enumerate(y_vals)], color))

    if global_max_y <= 0:
        global_max_y = 10.0

    scale_y = LinearScale((0, global_max_y * 1.05), (height - margin_bottom, margin_top))

    # Build X ticks
    x_tick_count = min(7, max_x)
    step = max(1, max_x // x_tick_count)
    x_ticks = [float(i) for i in range(0, max_x + 1, step)]
    if max_x not in x_ticks:
        x_ticks.append(float(max_x))

    x_axis_svg = render_x_axis(
        scale_x,
        y=height - margin_bottom,
        ticks=x_ticks,
        tick_format=lambda d: f"{int(d)}d",
    )

    y_axis_svg = render_y_axis(
        scale_y,
        x=margin_left,
        tick_format=(lambda v: format_time_span(v)) if subgraph == "time" else (lambda v: f"{round(v)}"),
    )

    paths_svg = []
    for label, pts, color in series_data:
        screen_pts = [(scale_x(x), scale_y(y)) for x, y in pts]
        p_str = render_line(screen_pts, stroke=color, stroke_width=1.5, css_class=f"sim-line line-{label}")
        paths_svg.append(p_str)

    content = f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <g class="x-axis">{x_axis_svg}</g>
  <g class="y-axis">{y_axis_svg}</g>
  <g class="sim-lines">{''.join(paths_svg)}</g>
</svg>"""
    return content


def render_workload_svg(
    simulations: list[dict[str, Any]],
    subgraph: str,  # "ratio", "count", "time", "memorized"
    width: float = 600,
    height: float = 250,
    margin_top: float = 20,
    margin_right: float = 50,
    margin_bottom: float = 30,
    margin_left: float = 50,
) -> str:
    if not simulations:
        return render_no_data_overlay(width, height, "No workload data")

    scale_x = LinearScale((70, 99), (margin_left, width - margin_right))

    series_data = []
    global_max_y = 0.0

    for idx, sim in enumerate(simulations):
        label = sim.get("label", idx + 1)
        color = CATEGORY10[(label - 1) % len(CATEGORY10)]
        learn_span = max(1, sim.get("days", 365))

        cost_map = sim.get("cost", {})
        count_map = sim.get("review_count", {})
        mem_map = sim.get("memorized", {})

        pts = []
        for dr in range(70, 100):
            dr_str = str(dr)
            dr_int = dr
            time_cost = cost_map.get(dr_str) or cost_map.get(dr_int, 0.0)
            count = count_map.get(dr_str) or count_map.get(dr_int, 0.0)
            memorized = mem_map.get(dr_str) or mem_map.get(dr_int, 0.0)

            if subgraph == "ratio":
                y = time_cost / max(0.001, memorized)
            elif subgraph == "time":
                y = time_cost / learn_span
            elif subgraph == "count":
                y = count / learn_span
            else:  # memorized
                y = memorized

            global_max_y = max(global_max_y, y)
            pts.append((float(dr), float(y)))

        series_data.append((label, pts, color))

    if global_max_y <= 0:
        global_max_y = 10.0

    scale_y = LinearScale((0, global_max_y * 1.05), (height - margin_bottom, margin_top))

    x_ticks = [float(dr) for dr in [70, 75, 80, 85, 90, 95, 99]]
    x_axis_svg = render_x_axis(
        scale_x,
        y=height - margin_bottom,
        ticks=x_ticks,
        tick_format=lambda dr: f"{int(dr)}%",
    )

    y_axis_svg = render_y_axis(
        scale_y,
        x=margin_left,
        tick_format=(lambda v: format_time_span(v)) if (subgraph == "time" or subgraph == "ratio") else (lambda v: f"{round(v)}"),
    )

    paths_svg = []
    for label, pts, color in series_data:
        screen_pts = [(scale_x(x), scale_y(y)) for x, y in pts]
        p_str = render_line(screen_pts, stroke=color, stroke_width=1.5, css_class=f"workload-line line-{label}")
        paths_svg.append(p_str)

    content = f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <g class="x-axis">{x_axis_svg}</g>
  <g class="y-axis">{y_axis_svg}</g>
  <g class="workload-lines">{''.join(paths_svg)}</g>
</svg>"""
    return content


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/deck-options/sim")

    @router.post("/run-simulator")
    async def run_simulator(payload: ReadSignals):
        """Simulate FSRS reviews over time."""
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        cfg = payload.get("cfg", {})
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except (json.JSONDecodeError, TypeError, ValueError):
                cfg = {}

        params = (
            cfg.get("fsrs_params_6")
            or cfg.get("fsrs_params_5")
            or cfg.get("fsrs_params_4")
            or []
        )
        if isinstance(params, str):
            try:
                params = [float(x.strip()) for x in params.split(",") if x.strip()]
            except (ValueError, TypeError, AttributeError):
                params = []

        days = int(payload.get("simDaysToSimulate", 365))
        deck_size = int(payload.get("simDeckSize", 0))
        new_limit = int(payload.get("simNewLimit", cfg.get("new_per_day", 20)))
        review_limit = int(payload.get("simReviewLimit", cfg.get("reviews_per_day", 200)))
        max_interval = int(payload.get("simMaxInterval", cfg.get("maximum_review_interval", 36500)))
        desired_retention = float(payload.get("simDesiredRetention", cfg.get("desired_retention", 0.9)))
        review_order = int(payload.get("simReviewOrder", cfg.get("review_order", 0)))
        ignore_rev_limit = bool(payload.get("simNewCardsIgnoreReviewLimit", False))
        suspend_leeches = bool(payload.get("simSuspendLeeches", False))
        leech_thresh = int(payload.get("simLeechThreshold", cfg.get("leech_threshold", 8)))

        easy_days = payload.get("simEasyDaysPercentages")
        if not easy_days or not isinstance(easy_days, list):
            easy_days = cfg.get("easy_days_percentages", [1.0] * 7)
        easy_days = [float(x) for x in easy_days]
        search = cfg.get("param_search") or payload.get("param_search") or ""
        if not search:
            preset_id = int(payload.get("presetId", 1))
            def _get_preset_name(col):
                dconf = col.decks.get_config(preset_id)
                return dconf.get("name", "Default") if dconf else "Default"
            try:
                preset_name = await service.run(_get_preset_name)
            except Exception:
                logger.exception("Failed to get preset name for simulator")
                preset_name = "Default"
            search = f'preset:"{preset_name}" -is:suspended'

        req = sched_pb.SimulateFsrsReviewRequest(
            params=params,
            desired_retention=desired_retention,
            deck_size=deck_size,
            days_to_simulate=days,
            new_limit=new_limit,
            review_limit=review_limit,
            max_interval=max_interval,
            search=search,
            new_cards_ignore_review_limit=ignore_rev_limit,
            easy_days_percentages=easy_days,
            review_order=cast(deck_cfg_pb.DeckConfig.Config.ReviewCardOrder.ValueType, review_order),
            historical_retention=float(cfg.get("historical_retention", 0.9)),
            learning_step_count=len(cfg.get("learn_steps", [1.0, 10.0])),
            relearning_step_count=len(cfg.get("relearn_steps", [10.0])),
        )
        if suspend_leeches:
            req.suspend_after_lapse_count = leech_thresh
        try:
            raw_bytes = await service.backend_raw_concurrent("simulate_fsrs_review", req.SerializeToString())
            resp = sched_pb.SimulateFsrsReviewResponse.FromString(raw_bytes)

            daily_review = list(resp.daily_review_count)
            daily_new = list(resp.daily_new_count)
            counts = [r + n for r, n in zip(daily_review, daily_new)]
            time_costs = list(resp.daily_time_cost)
            memorized = list(resp.accumulated_knowledge_acquisition)
            print("SIMULATE_FSRS_REVIEW RESULT:", f"rev[:10]={daily_review[:10]}", f"new[:10]={daily_new[:10]}", f"time[:5]={time_costs[:5]}", f"sum={sum(counts)}", f"search={req.search!r}", f"memorized[:5]={memorized[:5]}")
            sim_history = payload.get("simHistory", [])
            if not isinstance(sim_history, list):
                sim_history = []

            sim_num = len(sim_history) + 1
            new_entry = {
                "label": sim_num,
                "days": days,
                "counts": counts,
                "time_costs": time_costs,
                "memorized": memorized,
                "total_reviews": sum(counts),
                "total_time": sum(time_costs),
                "final_memorized": memorized[-1] if memorized else 0,
            }
            sim_history.append(new_entry)

            subgraph = payload.get("simSubgraph", "count")
            smooth = bool(payload.get("simSmooth", True))
            svg_content = render_simulation_svg(sim_history, subgraph=subgraph, smooth=smooth)

            table_rows_html = "".join([
                f"<tr><td class='font-bold'>#{s['label']}</td><td>{s['days']}</td><td>{s['total_reviews']}</td><td>{round(s['total_time']/60)} min</td><td>{round(s['final_memorized'])}</td></tr>"
                for s in sim_history
            ])
            table_html = f"""<div id="simTableContainer" class="mt-3"><div class="overflow-x-auto"><table class="table table-xs table-zebra border border-base-300 mb-0"><thead><tr><th>#</th><th>Days to simulate</th><th>Total Reviews</th><th>Total Time</th><th>Final Memorized</th></tr></thead><tbody>{table_rows_html}</tbody></table></div></div>"""

            return DatastarResponse([
                SSE.patch_signals({
                    "simHistory": sim_history,
                    "simActiveSimulationNumber": sim_num,
                    "simProcessing": False,
                    "simError": "",
                }),
                SSE.patch_elements(
                    f'<div id="simChartContainer" class="sim-svg-container">{svg_content}</div>',
                    selector="#simChartContainer",
                ),
                SSE.patch_elements(
                    table_html,
                    selector="#simTableContainer",
                )
            ])
        except Exception as exc:
            logger.exception("simulate_fsrs_review failed")
            return DatastarResponse([
                SSE.patch_signals({
                    "simProcessing": False,
                    "simError": f"Simulation failed: {exc!s}",
                })
            ])

    @router.post("/run-workload")
    async def run_workload(payload: ReadSignals):
        """Simulate FSRS workload across retention values (70% - 99%)."""
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        cfg = payload.get("cfg", {})
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except (json.JSONDecodeError, TypeError, ValueError):
                cfg = {}

        params = (
            cfg.get("fsrs_params_6")
            or cfg.get("fsrs_params_5")
            or cfg.get("fsrs_params_4")
            or []
        )
        if isinstance(params, str):
            try:
                params = [float(x.strip()) for x in params.split(",") if x.strip()]
            except (ValueError, TypeError, AttributeError):
                params = []

        days = int(payload.get("workloadDaysToSimulate", 365))
        deck_size = int(payload.get("workloadDeckSize", 0))
        new_limit = int(payload.get("workloadNewLimit", cfg.get("new_per_day", 20)))
        review_limit = int(payload.get("workloadReviewLimit", 9999))
        max_interval = int(payload.get("workloadMaxInterval", cfg.get("maximum_review_interval", 36500)))
        review_order = int(payload.get("workloadReviewOrder", cfg.get("review_order", 0)))
        ignore_rev_limit = bool(payload.get("workloadNewCardsIgnoreReviewLimit", False))

        easy_days = payload.get("workloadEasyDaysPercentages")
        if not easy_days or not isinstance(easy_days, list):
            easy_days = cfg.get("easy_days_percentages", [1.0] * 7)
        easy_days = [float(x) for x in easy_days]

        search = cfg.get("param_search") or payload.get("param_search") or ""
        if not search:
            preset_id = int(payload.get("presetId", 1))
            def _get_preset_name(col):
                dconf = col.decks.get_config(preset_id)
                return dconf.get("name", "Default") if dconf else "Default"
            try:
                preset_name = await service.run(_get_preset_name)
            except Exception:
                logger.exception("Failed to get preset name for workload")
                preset_name = "Default"
            search = f'preset:"{preset_name}" -is:suspended'

        req = sched_pb.SimulateFsrsReviewRequest(
            params=params,
            desired_retention=0.9,
            deck_size=deck_size,
            days_to_simulate=days,
            new_limit=new_limit,
            review_limit=review_limit,
            max_interval=max_interval,
            search=search,
            new_cards_ignore_review_limit=ignore_rev_limit,
            easy_days_percentages=easy_days,
            review_order=cast(deck_cfg_pb.DeckConfig.Config.ReviewCardOrder.ValueType, review_order),
            historical_retention=float(cfg.get("historical_retention", 0.9)),
            learning_step_count=len(cfg.get("learn_steps", [1.0, 10.0])),
            relearning_step_count=len(cfg.get("relearn_steps", [10.0])),
        )

        try:
            raw_bytes = await service.backend_raw_concurrent("simulate_fsrs_workload", req.SerializeToString())
            resp = sched_pb.SimulateFsrsWorkloadResponse.FromString(raw_bytes)

            cost_dict = {int(k): float(v) for k, v in resp.cost.items()}
            mem_dict = {int(k): float(v) for k, v in resp.memorized.items()}
            count_dict = {int(k): int(v) for k, v in resp.review_count.items()}

            workload_history = payload.get("workloadHistory", [])
            if not isinstance(workload_history, list):
                workload_history = []

            sim_num = len(workload_history) + 1
            entry = {
                "label": sim_num,
                "days": days,
                "cost": cost_dict,
                "memorized": mem_dict,
                "review_count": count_dict,
            }
            workload_history.append(entry)

            subgraph = payload.get("workloadSubgraph", "ratio")
            svg_content = render_workload_svg(workload_history, subgraph=subgraph)

            return DatastarResponse([
                SSE.patch_signals({
                    "workloadHistory": workload_history,
                    "workloadActiveNumber": sim_num,
                    "workloadProcessing": False,
                    "workloadError": "",
                }),
                SSE.patch_elements(
                    f'<div id="workloadChartContainer" class="sim-svg-container">{svg_content}</div>',
                    selector="#workloadChartContainer",
                )
            ])
        except Exception as exc:
            logger.exception("simulate_fsrs_workload failed")
            return DatastarResponse([
                SSE.patch_signals({
                    "workloadProcessing": False,
                    "workloadError": f"Workload simulation failed: {exc!s}",
                })
            ])

    @router.post("/clear-simulation")
    async def clear_simulation(payload: ReadSignals):
        """Remove last simulation run from history."""
        if not payload or not isinstance(payload, dict):
            payload = {}
        sim_history = payload.get("simHistory", [])
        if isinstance(sim_history, list) and sim_history:
            sim_history.pop()
        subgraph = payload.get("simSubgraph", "count")
        smooth = bool(payload.get("simSmooth", True))
        svg_content = render_simulation_svg(sim_history, subgraph=subgraph, smooth=smooth)

        table_rows_html = "".join([
            f"<tr><td class='font-bold'>#{s['label']}</td><td>{s['days']}</td><td>{s['total_reviews']}</td><td>{round(s['total_time']/60)} min</td><td>{round(s['final_memorized'])}</td></tr>"
            for s in sim_history
        ])
        table_html = f"""<div id="simTableContainer" class="mt-3"><div class="overflow-x-auto"><table class="table table-xs table-zebra border border-base-300 mb-0"><thead><tr><th>#</th><th>Days to simulate</th><th>Total Reviews</th><th>Total Time</th><th>Final Memorized</th></tr></thead><tbody>{table_rows_html}</tbody></table></div></div>""" if sim_history else '<div id="simTableContainer" class="mt-3"></div>'

        return DatastarResponse([
            SSE.patch_signals({
                "simHistory": sim_history,
                "simActiveSimulationNumber": len(sim_history),
            }),
            SSE.patch_elements(
                f'<div id="simChartContainer" class="sim-svg-container">{svg_content}</div>',
                selector="#simChartContainer",
            ),
            SSE.patch_elements(
                table_html,
                selector="#simTableContainer",
            )
        ])

    @router.post("/clear-workload")
    async def clear_workload(payload: ReadSignals):
        """Remove last workload simulation run from history."""
        if not payload or not isinstance(payload, dict):
            payload = {}
        workload_history = payload.get("workloadHistory", [])
        if isinstance(workload_history, list) and workload_history:
            workload_history.pop()
        subgraph = payload.get("workloadSubgraph", "ratio")
        svg_content = render_workload_svg(workload_history, subgraph=subgraph)

        return DatastarResponse([
            SSE.patch_signals({
                "workloadHistory": workload_history,
                "workloadActiveNumber": len(workload_history),
            }),
            SSE.patch_elements(
                f'<div id="workloadChartContainer" class="sim-svg-container">{svg_content}</div>',
                selector="#workloadChartContainer",
            )
        ])

    @router.post("/switch-subgraph")
    async def switch_subgraph(payload: ReadSignals):
        """Re-render simulation or workload chart with different metric."""
        if not payload or not isinstance(payload, dict):
            payload = {}
        mode = payload.get("simMode", "review")
        if mode == "workload":
            workload_history = payload.get("workloadHistory", [])
            subgraph = payload.get("workloadSubgraph", "ratio")
            svg_content = render_workload_svg(workload_history, subgraph=subgraph)
            return DatastarResponse(
                SSE.patch_elements(f'<div id="workloadChartContainer" class="sim-svg-container">{svg_content}</div>', selector="#workloadChartContainer")
            )
        else:
            sim_history = payload.get("simHistory", [])
            subgraph = payload.get("simSubgraph", "count")
            smooth = bool(payload.get("simSmooth", True))
            svg_content = render_simulation_svg(sim_history, subgraph=subgraph, smooth=smooth)
            return DatastarResponse(
                SSE.patch_elements(f'<div id="simChartContainer" class="sim-svg-container">{svg_content}</div>', selector="#simChartContainer")
            )

    @router.post("/save-sim-to-preset")
    async def save_sim_to_preset(payload: ReadSignals):
        """Copy simulation parameters to deck config preset and mark dirty."""
        if not payload or not isinstance(payload, dict):
            payload = {}
        cfg = payload.get("cfg", {})
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except (json.JSONDecodeError, TypeError, ValueError):
                cfg = {}

        mode = payload.get("simMode", "review")
        if mode == "workload":
            cfg["new_per_day"] = int(payload.get("workloadNewLimit", cfg.get("new_per_day", 20)))
            cfg["reviews_per_day"] = int(payload.get("workloadReviewLimit", cfg.get("reviews_per_day", 200)))
            cfg["maximum_review_interval"] = int(payload.get("workloadMaxInterval", cfg.get("maximum_review_interval", 36500)))
            cfg["review_order"] = int(payload.get("workloadReviewOrder", cfg.get("review_order", 0)))
            easy_days = payload.get("workloadEasyDaysPercentages")
            if easy_days and isinstance(easy_days, list):
                cfg["easy_days_percentages"] = [float(x) for x in easy_days]
        else:
            cfg["new_per_day"] = int(payload.get("simNewLimit", cfg.get("new_per_day", 20)))
            cfg["reviews_per_day"] = int(payload.get("simReviewLimit", cfg.get("reviews_per_day", 200)))
            cfg["maximum_review_interval"] = int(payload.get("simMaxInterval", cfg.get("maximum_review_interval", 36500)))
            cfg["desired_retention"] = float(payload.get("simDesiredRetention", cfg.get("desired_retention", 0.9)))
            cfg["review_order"] = int(payload.get("simReviewOrder", cfg.get("review_order", 0)))
            suspend = bool(payload.get("simSuspendLeeches", False))
            cfg["leech_action"] = 1 if suspend else 0  # SUSPEND vs TAG_ONLY
            cfg["leech_threshold"] = int(payload.get("simLeechThreshold", cfg.get("leech_threshold", 8)))
            easy_days = payload.get("simEasyDaysPercentages")
            if easy_days and isinstance(easy_days, list):
                cfg["easy_days_percentages"] = [float(x) for x in easy_days]

        return DatastarResponse(
            SSE.patch_signals({
                "cfg": cfg,
                "dirty": True,
                "simSavedSuccess": True,
            })
        )


    return router
