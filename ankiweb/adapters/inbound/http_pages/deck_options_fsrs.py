from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import cast

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

from ankiweb.adapters.inbound.http_datastar.common import signals_response
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/deck-options/fsrs")

    @router.post("/optimize")
    async def optimize(payload: ReadSignals):
        """Compute optimal FSRS parameters for the given preset / search query."""
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        cfg = payload.get("cfg", {})
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except (json.JSONDecodeError, TypeError, ValueError):
                cfg = {}

        # Search parameter or default preset search
        search = cfg.get("param_search") or payload.get("param_search") or ""
        if not search:
            preset_name = payload.get("preset_name") or ""
            if preset_name:
                search = f'preset:"{preset_name}" -is:suspended'
            else:
                search = '-is:suspended'

        # Current params
        current_params = (
            cfg.get("fsrs_params_6")
            or cfg.get("fsrs_params_5")
            or cfg.get("fsrs_params_4")
            or []
        )
        if isinstance(current_params, str):
            try:
                current_params = [float(x.strip()) for x in current_params.split(",") if x.strip()]
            except (ValueError, TypeError, AttributeError):
                current_params = []

        # Relearn steps
        relearn_steps = cfg.get("relearn_steps") or []
        num_relearning_steps = 0
        total_time = 0
        for step in relearn_steps:
            total_time += step
            if total_time >= 1440:
                break
            num_relearning_steps += 1

        # Health check setting
        health_check = bool(payload.get("fsrs_health_check", True))

        req = sched_pb.ComputeFsrsParamsRequest(
            search=search,
            current_params=current_params,
            ignore_revlogs_before_ms=0,
            num_of_relearning_steps=num_relearning_steps,
            health_check=health_check,
        )

        async def _run_optimize():
            # Emit running signal
            yield SSE.patch_signals({
                "fsrsComputing": True,
                "fsrsProgressLabel": tr.deck_config_optimizing_preset(current_count=1, total_count=1) if hasattr(tr, "deck_config_optimizing_preset") else "Optimizing...",
                "fsrsProgressPercent": 50,
            })

            try:
                raw_bytes = await service.backend_raw_concurrent(
                    "compute_fsrs_params", req.SerializeToString()
                )
                resp = sched_pb.ComputeFsrsParamsResponse.FromString(raw_bytes)
                params_list = list(resp.params)

                # Check if identical or empty
                is_identical = (
                    len(current_params) > 0
                    and len(current_params) == len(params_list)
                    and all(round(a, 4) == round(b, 4) for a, b in zip(current_params, params_list))
                ) or len(params_list) == 0

                messages = []
                if is_identical:
                    if resp.fsrs_items:
                        messages.append(tr.deck_config_fsrs_params_optimal())
                    else:
                        messages.append(tr.deck_config_fsrs_params_no_reviews())
                if resp.health_check_passed:
                    messages.append(tr.deck_config_fsrs_good_fit())
                elif resp.health_check_passed is False and len(params_list) > 0:
                    messages.append(tr.deck_config_fsrs_bad_fit_warning())

                alert_text = "\n\n".join(messages)

                signals_patch = {
                    "fsrsComputing": False,
                    "fsrsProgressLabel": "",
                    "fsrsProgressPercent": 100,
                    "fsrsReviewCount": resp.fsrs_items,
                    "fsrsHealthCheckPassed": resp.health_check_passed,
                }
                if not is_identical and params_list:
                    # Update config with new parameters and mark dirty
                    cfg["fsrs_params_6"] = params_list
                    signals_patch["cfg"] = cfg
                    signals_patch["dirty"] = True

                yield SSE.patch_signals(signals_patch)
                if alert_text:
                    yield SSE.execute_script(f"alert({json.dumps(alert_text)});")

            except Exception as exc:
                logger.exception("FSRS parameter optimization failed")
                yield SSE.patch_signals({
                    "fsrsComputing": False,
                    "fsrsProgressLabel": "",
                    "fsrsProgressPercent": 0,
                })
                yield SSE.execute_script(f"alert({json.dumps(str(exc))});")

        return DatastarResponse(_run_optimize())

    @router.post("/evaluate")
    async def evaluate(payload: ReadSignals):
        """Evaluate current FSRS parameters (Log loss and RMSE)."""
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        cfg = payload.get("cfg", {})
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except (json.JSONDecodeError, TypeError, ValueError):
                cfg = {}

        search = cfg.get("param_search") or payload.get("param_search") or ""
        if not search:
            preset_name = payload.get("preset_name") or ""
            if preset_name:
                search = f'preset:"{preset_name}" -is:suspended'
            else:
                search = '-is:suspended'

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

        req = sched_pb.EvaluateParamsLegacyRequest(
            search=search,
            params=params,
            ignore_revlogs_before_ms=0,
        )

        async def _run_eval():
            yield SSE.patch_signals({
                "fsrsEvaluating": True,
                "fsrsProgressLabel": "Evaluating...",
                "fsrsProgressPercent": 50,
            })
            try:
                raw_bytes = await service.backend_raw_concurrent(
                    "evaluate_params_legacy", req.SerializeToString()
                )
                resp = sched_pb.EvaluateParamsResponse.FromString(raw_bytes)
                smaller_better = tr.deck_config_smaller_is_better() if hasattr(tr, "deck_config_smaller_is_better") else "Smaller is better"
                eval_msg = f"Log loss: {resp.log_loss:.4f}, RMSE(bins): {resp.rmse_bins * 100:.2f}%. {smaller_better}"

                yield SSE.patch_signals({
                    "fsrsEvaluating": False,
                    "fsrsProgressLabel": "",
                    "fsrsProgressPercent": 100,
                    "fsrsEvalLogLoss": resp.log_loss,
                    "fsrsEvalRmse": resp.rmse_bins,
                })
                yield SSE.execute_script(f"alert({json.dumps(eval_msg)});")
            except Exception as exc:
                logger.exception("FSRS evaluation failed")
                yield SSE.patch_signals({
                    "fsrsEvaluating": False,
                    "fsrsProgressLabel": "",
                    "fsrsProgressPercent": 0,
                })
                yield SSE.execute_script(f"alert({json.dumps(str(exc))});")

        return DatastarResponse(_run_eval())

    @router.post("/calculate-retention")
    async def calculate_retention(payload: ReadSignals):
        """Compute optimal retention for current preset configuration."""
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

        search = cfg.get("param_search") or payload.get("param_search") or ""
        if not search:
            preset_name = payload.get("preset_name") or ""
            if preset_name:
                search = f'preset:"{preset_name}" -is:suspended'
            else:
                search = '-is:suspended'

        req = sched_pb.SimulateFsrsReviewRequest(
            params=params,
            desired_retention=float(cfg.get("desired_retention", 0.9)),
            deck_size=int(payload.get("deck_size", 1000)),
            days_to_simulate=int(payload.get("days_to_simulate", 365)),
            new_limit=int(cfg.get("new_per_day", 20)),
            review_limit=int(cfg.get("reviews_per_day", 200)),
            max_interval=int(cfg.get("maximum_review_interval", 36500)),
            search=search,
            new_cards_ignore_review_limit=bool(payload.get("new_cards_ignore_review_limit", False)),
            easy_days_percentages=cfg.get("easy_days_percentages") or [1.0] * 7,
            review_order=cast(deck_cfg_pb.DeckConfig.Config.ReviewCardOrder.ValueType, int(cfg.get("review_order", 0))),
            suspend_after_lapse_count=0,
            historical_retention=float(cfg.get("historical_retention", 0.9)),
            learning_step_count=len(cfg.get("learn_steps") or [1, 10]),
            relearning_step_count=len(cfg.get("relearn_steps") or [10]),
        )

        async def _run_calc():
            yield SSE.patch_signals({
                "fsrsComputingRetention": True,
                "fsrsProgressLabel": "Computing optimal retention...",
                "fsrsProgressPercent": 50,
            })
            try:
                raw_bytes = await service.backend_raw_concurrent(
                    "compute_optimal_retention", req.SerializeToString()
                )
                resp = sched_pb.ComputeOptimalRetentionResponse.FromString(raw_bytes)
                opt_ret = round(resp.optimal_retention, 4)

                yield SSE.patch_signals({
                    "fsrsComputingRetention": False,
                    "fsrsProgressLabel": "",
                    "fsrsProgressPercent": 100,
                    "fsrsOptimalRetention": opt_ret,
                })
            except Exception as exc:
                logger.exception("Computing optimal retention failed")
                yield SSE.patch_signals({
                    "fsrsComputingRetention": False,
                    "fsrsProgressLabel": "",
                    "fsrsProgressPercent": 0,
                })
                yield SSE.execute_script(f"alert({json.dumps(str(exc))});")

        return DatastarResponse(_run_calc())

    @router.post("/workload")
    async def workload(payload: ReadSignals):
        """Fetch retention workload factor for comparison with previous DR."""
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

        search = cfg.get("param_search") or payload.get("param_search") or ""
        if not search:
            preset_name = payload.get("preset_name") or ""
            if preset_name:
                search = f'preset:"{preset_name}" -is:suspended'
            else:
                search = '-is:suspended'

        cur_dr = float(cfg.get("desired_retention", 0.9))
        prev_dr = float(payload.get("previous_dr", cur_dr))

        try:
            req = deck_cfg_pb.GetRetentionWorkloadRequest(w=params, search=search)
            raw_bytes = await service.backend_raw_concurrent(
                "get_retention_workload", req.SerializeToString()
            )
            resp = deck_cfg_pb.GetRetentionWorkloadResponse.FromString(raw_bytes)
            costs = resp.costs

            cur_key = round(cur_dr * 100)
            prev_key = round(prev_dr * 100)

            cur_cost = costs.get(cur_key, 1.0)
            prev_cost = costs.get(prev_key, 1.0)

            factor = round(cur_cost / prev_cost, 2) if prev_cost else 1.0

            if round(cur_dr, 2) == round(prev_dr, 2) or factor == 1.0:
                workload_msg = tr.deck_config_workload_factor_unchanged() if hasattr(tr, "deck_config_workload_factor_unchanged") else ""
            else:
                workload_msg = tr.deck_config_workload_factor_change(factor=f"{factor:.2f}", previous_dr=str(prev_key)) if hasattr(tr, "deck_config_workload_factor_change") else f"Workload factor: {factor:.2f}"

            return signals_response({
                "fsrsWorkloadMsg": workload_msg,
                "fsrsWorkloadFactor": factor,
            })
        except Exception:
            logger.exception("Failed to get retention workload")
            return DatastarResponse()

    @router.post("/abort")
    async def abort(payload: ReadSignals):
        """Cancel running FSRS compute / simulation."""
        service = get_service()
        try:
            await service.backend_raw_concurrent("set_wants_abort", b"")
        except Exception:
            logger.exception("Failed to set abort flag")
        return signals_response({
            "fsrsComputing": False,
            "fsrsEvaluating": False,
            "fsrsComputingRetention": False,
            "fsrsProgressLabel": "Aborted",
            "fsrsProgressPercent": 0,
        })

    return router
