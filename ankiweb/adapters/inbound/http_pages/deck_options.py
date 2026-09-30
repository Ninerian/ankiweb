from __future__ import annotations
import json
import logging
from typing import Any, Callable

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, Response
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)
from google.protobuf.json_format import MessageToDict

from ankiweb.core.i18n import tr
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.adapters.inbound.http_pages.deck_options_help import HELP_MODALS
import anki.deck_config_pb2 as dc

logger = logging.getLogger(__name__)

# Map section title -> help modal definition from upstream
HELP_MODALS_BY_TITLE = {m["title"]: m for m in HELP_MODALS}


def _cfg_to_dict(config_pb: dc.DeckConfig.Config) -> dict[str, Any]:
    """Convert DeckConfig.Config proto to dict preserving proto field names."""
    d = MessageToDict(config_pb, preserving_proto_field_name=True)
    # Ensure repeated fields are Python lists
    if "learn_steps" not in d:
        d["learn_steps"] = [float(x) for x in config_pb.learn_steps]
    else:
        d["learn_steps"] = [float(x) for x in d["learn_steps"]]

    if "relearn_steps" not in d:
        d["relearn_steps"] = [float(x) for x in config_pb.relearn_steps]
    else:
        d["relearn_steps"] = [float(x) for x in d["relearn_steps"]]

    if "easy_days_percentages" not in d:
        d["easy_days_percentages"] = [float(x) for x in config_pb.easy_days_percentages] if config_pb.easy_days_percentages else [1.0] * 7
    else:
        d["easy_days_percentages"] = [float(x) for x in d["easy_days_percentages"]]

    if "fsrs_params_6" not in d:
        d["fsrs_params_6"] = [float(x) for x in config_pb.fsrs_params_6]
    else:
        d["fsrs_params_6"] = [float(x) for x in d["fsrs_params_6"]]

    # Convert enum numbers if MessageToDict output string names
    enums = {
        "new_card_insert_order": dc.DeckConfig.Config.NewCardInsertOrder,
        "new_card_gather_priority": dc.DeckConfig.Config.NewCardGatherPriority,
        "new_card_sort_order": dc.DeckConfig.Config.NewCardSortOrder,
        "new_mix": dc.DeckConfig.Config.ReviewMix,
        "review_order": dc.DeckConfig.Config.ReviewCardOrder,
        "interday_learning_mix": dc.DeckConfig.Config.ReviewMix,
        "leech_action": dc.DeckConfig.Config.LeechAction,
        "question_action": dc.DeckConfig.Config.QuestionAction,
        "answer_action": dc.DeckConfig.Config.AnswerAction,
    }
    for k, enum_cls in enums.items():
        val = d.get(k)
        if isinstance(val, str):
            d[k] = enum_cls.Value(val)
        elif val is None:
            d[k] = getattr(config_pb, k)

    # Ensure numeric scalar defaults and ignore bytes fields like 'other'
    for f in config_pb.DESCRIPTOR.fields:
        if f.name == "other" or f.type == f.TYPE_BYTES:
            continue
        if f.name not in d:
            val = getattr(config_pb, f.name)
            if hasattr(f, "is_repeated") and f.is_repeated:
                d[f.name] = [float(x) for x in val]
            else:
                d[f.name] = val
    if "other" in d:
        del d["other"]
    return d


def _dict_to_cfg(d: dict[str, Any], config_pb: dc.DeckConfig.Config) -> None:
    """Populate DeckConfig.Config proto from dict."""
    for f in config_pb.DESCRIPTOR.fields:
        name = f.name
        if name not in d or name == "other" or f.type == f.TYPE_BYTES:
            continue
        val = d[name]
        is_rep = getattr(f, "is_repeated", False)
        if is_rep:
            items_to_add: list[float] = []
            if isinstance(val, dict):
                # Datastar serialized array as object {"0": x, "1": y}
                # Sort by numeric key
                sorted_keys = sorted([k for k in val.keys() if str(k).isdigit()], key=lambda k: int(k))
                for k in sorted_keys:
                    item_val = val[k]
                    if item_val is not None and str(item_val).strip() != "":
                        try:
                            items_to_add.append(float(item_val))
                        except (ValueError, TypeError):
                            pass
            elif isinstance(val, list):
                for item in val:
                    if item is not None and str(item).strip() != "":
                        try:
                            items_to_add.append(float(item))
                        except (ValueError, TypeError):
                            pass
            elif isinstance(val, str):
                parts = [p.strip() for p in val.replace(",", " ").split() if p.strip()]
                for p in parts:
                    try:
                        items_to_add.append(float(p))
                    except (ValueError, TypeError):
                        pass

            # Only overwrite if items_to_add is non-empty or val was explicitly an empty list
            if items_to_add or val == []:
                del getattr(config_pb, name)[:]
                for num in items_to_add:
                    getattr(config_pb, name).append(num)
        elif f.type == f.TYPE_BOOL:
            setattr(config_pb, name, bool(val))
        elif f.type in (f.TYPE_INT32, f.TYPE_INT64, f.TYPE_UINT32, f.TYPE_UINT64, f.TYPE_ENUM):
            if val is not None and str(val).strip() != "":
                try:
                    setattr(config_pb, name, int(val))
                except (ValueError, TypeError):
                    pass
        elif f.type in (f.TYPE_FLOAT, f.TYPE_DOUBLE):
            if val is not None and str(val).strip() != "":
                try:
                    setattr(config_pb, name, float(val))
                except (ValueError, TypeError):
                    pass
        elif f.type == f.TYPE_STRING:
            setattr(config_pb, name, str(val))


def _extract_limits_from_payload(payload: dict[str, Any]) -> dc.DeckConfigsForUpdate.CurrentDeck.Limits:
    limits = dc.DeckConfigsForUpdate.CurrentDeck.Limits()
    limit_mode = payload.get("limitMode", "preset")
    if limit_mode == "deck":
        if "deckLimitNew" in payload and payload["deckLimitNew"] is not None and str(payload["deckLimitNew"]).strip() != "":
            try:
                limits.new = int(payload["deckLimitNew"])
            except ValueError:
                pass
        if "deckLimitRev" in payload and payload["deckLimitRev"] is not None and str(payload["deckLimitRev"]).strip() != "":
            try:
                limits.review = int(payload["deckLimitRev"])
            except ValueError:
                pass
    if payload.get("todayLimitNewActive"):
        limits.new_today_active = True
        if "todayLimitNew" in payload and payload["todayLimitNew"] is not None and str(payload["todayLimitNew"]).strip() != "":
            try:
                limits.new_today = int(payload["todayLimitNew"])
            except ValueError:
                pass
    if payload.get("todayLimitRevActive"):
        limits.review_today_active = True
        if "todayLimitRev" in payload and payload["todayLimitRev"] is not None and str(payload["todayLimitRev"]).strip() != "":
            try:
                limits.review_today = int(payload["todayLimitRev"])
            except ValueError:
                pass
    return limits


def render_preset_selector_html(all_configs: list[dict[str, Any]], current_preset_id: int) -> str:
    html = '<div id="presetSelectorWrap">\n'
    html += '    <select id="presetSelector" class="select select-sm w-auto" data-bind="presetId" data-on:change="@post(\'/deck-options/change-preset\')">\n'
    for p in all_configs:
        sel = ' selected' if p["id"] == current_preset_id else ''
        count_str = f" ({p['use_count']})" if p.get("use_count") else ""
        html += f'        <option value="{p["id"]}"{sel}>{p["name"]}{count_str}</option>\n'
    html += '    </select>\n'
    html += '</div>'
    return html


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/deck-options/{deck_id}")
    async def deck_options_page(deck_id: int):
        service = get_service()

        def load_state(col):
            deck = col.decks.get(deck_id)
            if not deck:
                raise ValueError(f"Deck not found: {deck_id}")
            if deck.get("dyn"):
                return {"is_dyn": True, "deck": deck}
            return {"is_dyn": False, "res": col.decks.get_deck_configs_for_update(deck_id)}

        try:
            state_info = await service.run(load_state)
        except Exception as e:
            msg = str(e)
            if "deck not normal" in msg or "dyn" in msg:
                err_html = """
                <div class="mx-auto max-w-2xl py-4 px-4">
                    <div class="error-box p-6 border border-base-300 rounded-box bg-base-100 shadow-sm">
                        <h4 class="text-error font-bold text-lg mb-2">deck not normal</h4>
                        <p class="text-base-content/60 mb-4">Options cannot be configured for a filtered deck.</p>
                        <a href="/deckbrowser" class="btn btn-primary">Decks</a>
                    </div>
                </div>
                """
                return HTMLResponse(render_page(context="deckoptions", body=err_html, toolbar=True))
            raise

        if state_info.get("is_dyn"):
            err_html = """
            <div class="mx-auto max-w-2xl py-4 px-4">
                <div class="error-box p-6 border border-base-300 rounded-box bg-base-100 shadow-sm">
                    <h4 class="text-error font-bold text-lg mb-2">deck not normal</h4>
                    <p class="text-base-content/60 mb-4">Options cannot be configured for a filtered deck.</p>
                    <a href="/deckbrowser" class="btn btn-primary">Decks</a>
                </div>
            </div>
            """
            return HTMLResponse(render_page(context="deckoptions", body=err_html, toolbar=True))

        state = state_info["res"]

        all_configs = []
        for c_extra in state.all_config:
            all_configs.append({
                "id": c_extra.config.id,
                "name": c_extra.config.name,
                "use_count": c_extra.use_count,
                "config": _cfg_to_dict(c_extra.config.config),
            })

        current_preset_id = state.current_deck.config_id
        current_cfg_extra = next((c for c in all_configs if c["id"] == current_preset_id), all_configs[0])
        current_cfg = current_cfg_extra["config"]

        has_deck_new = state.current_deck.limits.HasField("new")
        has_deck_rev = state.current_deck.limits.HasField("review")
        limit_mode = "deck" if (has_deck_new or has_deck_rev) else "preset"

        today_new_active = state.current_deck.limits.new_today_active
        today_rev_active = state.current_deck.limits.review_today_active
        deck_new = state.current_deck.limits.new if has_deck_new else current_cfg.get("new_per_day", 20)
        deck_rev = state.current_deck.limits.review if has_deck_rev else current_cfg.get("reviews_per_day", 200)
        today_new = state.current_deck.limits.new_today if state.current_deck.limits.HasField("new_today") else current_cfg.get("new_per_day", 20)
        today_rev = state.current_deck.limits.review_today if state.current_deck.limits.HasField("review_today") else current_cfg.get("reviews_per_day", 200)

        learn_steps_str = " ".join(f"{x:g}" for x in current_cfg.get("learn_steps", [1.0, 10.0]))
        relearn_steps_str = " ".join(f"{x:g}" for x in current_cfg.get("relearn_steps", [10.0]))

        default_weights = [float(x) for x in state.defaults.config.fsrs_params_6]

        signals = {
            "deckId": deck_id,
            "deckName": state.current_deck.name,
            "presetId": current_preset_id,
            "cfg": current_cfg,
            "allConfigs": all_configs,
            "fsrs": bool(state.fsrs),
            "dirty": False,
            "activeTab": "daily-limits",
            "activeLimitSubTab": limit_mode,
            "limitMode": limit_mode,
            "deckLimitNew": deck_new,
            "deckLimitRev": deck_rev,
            "todayLimitNewActive": today_new_active,
            "todayLimitRevActive": today_rev_active,
            "todayLimitNew": today_new,
            "todayLimitRev": today_rev,
            "learnStepsStr": learn_steps_str,
            "relearnStepsStr": relearn_steps_str,
            "applyAllParentLimits": bool(state.apply_all_parent_limits),
            "newCardsIgnoreReviewLimit": bool(state.new_cards_ignore_review_limit),
            "cardStateCustomizer": state.card_state_customizer,
            "newPresetName": "",
            "clonePresetName": "",
            "renamePresetName": "",
            "applyToSubdecks": False,
            "fsrsComputing": False,
            "fsrsEvaluating": False,
            "fsrsComputingRetention": False,
            "fsrsProgressLabel": "",
            "fsrsProgressPercent": 0,
            "fsrsOptimalRetention": 0,
            "fsrsWorkloadMsg": "",
            "warnings": [],
            "statusMessage": "",
        }

        context = {
            "deck_id": deck_id,
            "deck_name": state.current_deck.name,
            "preset_id": current_preset_id,
            "all_configs": all_configs,
            "signals": signals,
            "default_weights": default_weights,
            "help_modals": HELP_MODALS_BY_TITLE,
            "tr": tr,
        }

        body = templating.render("pages/deck_options.html.jinja", **context)
        html = render_page(
            context="deckoptions",
            body=body,
            toolbar=True,
        )
        return HTMLResponse(html)

    @router.post("/deck-options/change-preset")
    async def change_preset(payload: ReadSignals):
        service = get_service()
        target_preset_id = int(payload.get("presetId", 1))
        deck_id = int(payload.get("deckId", 1))

        def get_all(col):
            return col.decks.get_deck_configs_for_update(deck_id)

        state = await service.run(get_all)
        target_extra = next((c for c in state.all_config if c.config.id == target_preset_id), state.all_config[0])
        cfg_dict = _cfg_to_dict(target_extra.config.config)

        learn_steps_str = " ".join(f"{x:g}" for x in cfg_dict.get("learn_steps", [1.0, 10.0]))
        relearn_steps_str = " ".join(f"{x:g}" for x in cfg_dict.get("relearn_steps", [10.0]))

        signals_update = {
            "presetId": target_preset_id,
            "cfg": cfg_dict,
            "learnStepsStr": learn_steps_str,
            "relearnStepsStr": relearn_steps_str,
            "dirty": True,
        }
        return DatastarResponse(SSE.patch_signals(signals_update))

    @router.post("/deck-options/add-preset")
    async def add_preset(payload: ReadSignals):
        service = get_service()
        deck_id = int(payload.get("deckId", 1))
        preset_name = str(payload.get("newPresetName", "")).strip() or "New Preset"

        def do_add(col):
            res = col.decks.get_deck_configs_for_update(deck_id)
            new_cfg = res.all_config.add()
            new_cfg.config.CopyFrom(res.defaults)
            new_cfg.config.id = 0
            new_cfg.config.name = preset_name
            new_cfg.use_count = 0

            req = dc.UpdateDeckConfigsRequest(
                target_deck_id=deck_id,
                configs=[c.config for c in res.all_config],
                mode=dc.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
                limits=res.current_deck.limits,
                card_state_customizer=res.card_state_customizer,
                new_cards_ignore_review_limit=res.new_cards_ignore_review_limit,
                apply_all_parent_limits=res.apply_all_parent_limits,
                fsrs=res.fsrs,
            )
            col.decks.update_deck_configs(req)
            return col.decks.get_deck_configs_for_update(deck_id)

        state = await service.run_op(do_add, initiator="deck-options")
        new_extra = next((c for c in state.all_config if c.config.name == preset_name), state.all_config[0])
        new_preset_id = new_extra.config.id
        new_cfg_dict = _cfg_to_dict(new_extra.config.config)

        all_configs = [{
            "id": c.config.id,
            "name": c.config.name,
            "use_count": c.use_count,
            "config": _cfg_to_dict(c.config.config),
        } for c in state.all_config]

        signals_update = {
            "allConfigs": all_configs,
            "presetId": new_preset_id,
            "cfg": new_cfg_dict,
            "learnStepsStr": " ".join(f"{x:g}" for x in new_cfg_dict.get("learn_steps", [1.0, 10.0])),
            "relearnStepsStr": " ".join(f"{x:g}" for x in new_cfg_dict.get("relearn_steps", [10.0])),
            "newPresetName": "",
            "dirty": True,
            "statusMessage": f"Added preset '{preset_name}'",
        }
        selector_html = render_preset_selector_html(all_configs, new_preset_id)
        return DatastarResponse([
            SSE.patch_elements(selector_html, selector="#presetSelectorWrap"),
            SSE.patch_signals(signals_update),
            SSE.execute_script("document.getElementById('addPresetModal')?.close()"),
        ])

    @router.post("/deck-options/clone-preset")
    async def clone_preset(payload: ReadSignals):
        service = get_service()
        deck_id = int(payload.get("deckId", 1))
        current_preset_id = int(payload.get("presetId", 1))
        clone_name = str(payload.get("clonePresetName", "")).strip() or "Cloned Preset"

        def do_clone(col):
            res = col.decks.get_deck_configs_for_update(deck_id)
            source_cfg = next((c.config for c in res.all_config if c.config.id == current_preset_id), res.all_config[0].config)
            new_cfg = res.all_config.add()
            new_cfg.config.CopyFrom(source_cfg)
            _dict_to_cfg(payload.get("cfg", {}), new_cfg.config.config)
            new_cfg.config.id = 0
            new_cfg.config.name = clone_name
            new_cfg.use_count = 0

            req = dc.UpdateDeckConfigsRequest(
                target_deck_id=deck_id,
                configs=[c.config for c in res.all_config],
                mode=dc.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
                limits=res.current_deck.limits,
                card_state_customizer=res.card_state_customizer,
                new_cards_ignore_review_limit=res.new_cards_ignore_review_limit,
                apply_all_parent_limits=res.apply_all_parent_limits,
                fsrs=res.fsrs,
            )
            col.decks.update_deck_configs(req)
            return col.decks.get_deck_configs_for_update(deck_id)

        state = await service.run_op(do_clone, initiator="deck-options")
        new_extra = next((c for c in state.all_config if c.config.name == clone_name), state.all_config[0])
        new_preset_id = new_extra.config.id
        new_cfg_dict = _cfg_to_dict(new_extra.config.config)

        all_configs = [{
            "id": c.config.id,
            "name": c.config.name,
            "use_count": c.use_count,
            "config": _cfg_to_dict(c.config.config),
        } for c in state.all_config]

        signals_update = {
            "allConfigs": all_configs,
            "presetId": new_preset_id,
            "cfg": new_cfg_dict,
            "learnStepsStr": " ".join(f"{x:g}" for x in new_cfg_dict.get("learn_steps", [1.0, 10.0])),
            "relearnStepsStr": " ".join(f"{x:g}" for x in new_cfg_dict.get("relearn_steps", [10.0])),
            "clonePresetName": "",
            "dirty": True,
            "statusMessage": f"Cloned preset to '{clone_name}'",
        }
        selector_html = render_preset_selector_html(all_configs, new_preset_id)
        return DatastarResponse([
            SSE.patch_elements(selector_html, selector="#presetSelectorWrap"),
            SSE.patch_signals(signals_update),
            SSE.execute_script("document.getElementById('clonePresetModal')?.close()"),
        ])

    @router.post("/deck-options/rename-preset")
    async def rename_preset(payload: ReadSignals):
        service = get_service()
        deck_id = int(payload.get("deckId", 1))
        current_preset_id = int(payload.get("presetId", 1))
        rename_to = str(payload.get("renamePresetName", "")).strip()
        if not rename_to:
            return DatastarResponse([
                SSE.patch_signals({"statusMessage": "Preset name cannot be empty"}),
                SSE.execute_script("document.getElementById('renamePresetModal')?.close()"),
            ])
        def do_rename(col):
            res = col.decks.get_deck_configs_for_update(deck_id)
            target = next((c.config for c in res.all_config if c.config.id == current_preset_id), None)
            if target:
                target.name = rename_to
            req = dc.UpdateDeckConfigsRequest(
                target_deck_id=deck_id,
                configs=[c.config for c in res.all_config],
                mode=dc.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
                limits=res.current_deck.limits,
                card_state_customizer=res.card_state_customizer,
                new_cards_ignore_review_limit=res.new_cards_ignore_review_limit,
                apply_all_parent_limits=res.apply_all_parent_limits,
                fsrs=res.fsrs,
            )
            col.decks.update_deck_configs(req)
            return col.decks.get_deck_configs_for_update(deck_id)

        state = await service.run_op(do_rename, initiator="deck-options")
        all_configs = [{
            "id": c.config.id,
            "name": c.config.name,
            "use_count": c.use_count,
            "config": _cfg_to_dict(c.config.config),
        } for c in state.all_config]

        selector_html = render_preset_selector_html(all_configs, current_preset_id)
        return DatastarResponse([
            SSE.patch_elements(selector_html, selector="#presetSelectorWrap"),
            SSE.patch_signals({
                "allConfigs": all_configs,
                "renamePresetName": "",
                "statusMessage": f"Renamed preset to '{rename_to}'",
            }),
            SSE.execute_script("document.getElementById('renamePresetModal')?.close()"),
        ])

    @router.post("/deck-options/delete-preset")
    async def delete_preset(payload: ReadSignals):
        service = get_service()
        deck_id = int(payload.get("deckId", 1))
        current_preset_id = int(payload.get("presetId", 1))

        if current_preset_id == 1:
            return DatastarResponse([
                SSE.patch_signals({"statusMessage": "The Default preset cannot be deleted."}),
                SSE.execute_script("document.getElementById('deletePresetModal')?.close()"),
            ])

        def do_delete(col):
            col.decks.remove_config(current_preset_id)
            return col.decks.get_deck_configs_for_update(deck_id)

        state = await service.run_op(do_delete, initiator="deck-options")
        new_preset_id = state.current_deck.config_id
        target_extra = next((c for c in state.all_config if c.config.id == new_preset_id), state.all_config[0])
        new_cfg_dict = _cfg_to_dict(target_extra.config.config)

        all_configs = [{
            "id": c.config.id,
            "name": c.config.name,
            "use_count": c.use_count,
            "config": _cfg_to_dict(c.config.config),
        } for c in state.all_config]

        signals_update = {
            "allConfigs": all_configs,
            "presetId": new_preset_id,
            "cfg": new_cfg_dict,
            "learnStepsStr": " ".join(f"{x:g}" for x in new_cfg_dict.get("learn_steps", [1.0, 10.0])),
            "relearnStepsStr": " ".join(f"{x:g}" for x in new_cfg_dict.get("relearn_steps", [10.0])),
            "dirty": False,
            "statusMessage": "Preset deleted",
        }
        selector_html = render_preset_selector_html(all_configs, new_preset_id)
        return DatastarResponse([
            SSE.patch_elements(selector_html, selector="#presetSelectorWrap"),
            SSE.patch_signals(signals_update),
            SSE.execute_script("document.getElementById('deletePresetModal')?.close()"),
        ])

    @router.post("/deck-options/save")
    async def save_options(payload: ReadSignals):
        service = get_service()
        deck_id = int(payload.get("deckId", 1))
        current_preset_id = int(payload.get("presetId", 1))
        apply_to_subdecks = bool(payload.get("applyToSubdecks", False))

        cfg_dict = dict(payload.get("cfg", {}))
        learn_steps_str = payload.get("learnStepsStr")
        if learn_steps_str is not None:
            parts = [float(x) for x in str(learn_steps_str).replace(",", " ").split() if x.strip()]
            cfg_dict["learn_steps"] = parts
        relearn_steps_str = payload.get("relearnStepsStr")
        if relearn_steps_str is not None:
            parts = [float(x) for x in str(relearn_steps_str).replace(",", " ").split() if x.strip()]
            cfg_dict["relearn_steps"] = parts

        limits = _extract_limits_from_payload(payload)

        warnings = []
        try:
            grad_good = int(cfg_dict.get("graduating_interval_good", 1))
            grad_easy = int(cfg_dict.get("graduating_interval_easy", 4))
            if grad_good >= grad_easy:
                warnings.append(tr.deck_config_good_above_easy())

            min_lapse = int(cfg_dict.get("minimum_lapse_interval", 1))
            for step in cfg_dict.get("relearn_steps", []):
                if float(step) / 1440.0 >= min_lapse:
                    warnings.append(tr.deck_config_relearning_steps_above_minimum_interval())
                    break

            for step in cfg_dict.get("learn_steps", []):
                if float(step) / 1440.0 >= grad_good:
                    warnings.append(tr.deck_config_learning_step_above_graduating_interval())
                    break
        except Exception:
            pass

        def do_save(col):
            res = col.decks.get_deck_configs_for_update(deck_id)
            configs_to_update = []
            for c_extra in res.all_config:
                c_copy = dc.DeckConfig()
                c_copy.CopyFrom(c_extra.config)
                if c_copy.id == current_preset_id:
                    _dict_to_cfg(cfg_dict, c_copy.config)
                configs_to_update.append(c_copy)

            deck = col.decks.get(deck_id)
            if deck and deck.get("conf") != current_preset_id:
                deck["conf"] = current_preset_id
                col.decks.save(deck)

            mode = (
                dc.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_APPLY_TO_CHILDREN
                if apply_to_subdecks
                else dc.UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL
            )

            req = dc.UpdateDeckConfigsRequest(
                target_deck_id=deck_id,
                configs=configs_to_update,
                mode=mode,
                limits=limits,
                card_state_customizer=str(payload.get("cardStateCustomizer", res.card_state_customizer)),
                new_cards_ignore_review_limit=bool(payload.get("newCardsIgnoreReviewLimit", res.new_cards_ignore_review_limit)),
                apply_all_parent_limits=bool(payload.get("applyAllParentLimits", res.apply_all_parent_limits)),
                fsrs=bool(payload.get("fsrs", res.fsrs)),
            )
            col.decks.update_deck_configs(req)

            if apply_to_subdecks:
                for name, child_id in col.decks.children(deck_id):
                    child = col.decks.get(child_id)
                    if child:
                        child["conf"] = current_preset_id
                        col.decks.save(child)

            return col.decks.get_deck_configs_for_update(deck_id)

        try:
            state = await service.run_op(do_save, initiator="deck-options")
        except Exception as e:
            logger.exception("Failed to save deck options")
            return DatastarResponse(SSE.patch_signals({
                "statusMessage": f"Error saving: {e}",
            }))

        target_extra = next((c for c in state.all_config if c.config.id == current_preset_id), state.all_config[0])
        saved_cfg_dict = _cfg_to_dict(target_extra.config.config)

        all_configs = [{
            "id": c.config.id,
            "name": c.config.name,
            "use_count": c.use_count,
            "config": _cfg_to_dict(c.config.config),
        } for c in state.all_config]

        signals_update = {
            "allConfigs": all_configs,
            "cfg": saved_cfg_dict,
            "dirty": False,
            "warnings": warnings,
            "statusMessage": "Saved successfully!" if not apply_to_subdecks else "Saved to deck and all subdecks!",
        }

        return DatastarResponse([
            SSE.patch_signals(signals_update),
        ])

    @router.post("/deck-options/revert")
    async def revert_options(payload: ReadSignals):
        service = get_service()
        deck_id = int(payload.get("deckId", 1))
        current_preset_id = int(payload.get("presetId", 1))

        def get_saved(col):
            return col.decks.get_deck_configs_for_update(deck_id)

        state = await service.run(get_saved)
        target_extra = next((c for c in state.all_config if c.config.id == current_preset_id), state.all_config[0])
        saved_cfg_dict = _cfg_to_dict(target_extra.config.config)

        learn_steps_str = " ".join(f"{x:g}" for x in saved_cfg_dict.get("learn_steps", [1.0, 10.0]))
        relearn_steps_str = " ".join(f"{x:g}" for x in saved_cfg_dict.get("relearn_steps", [10.0]))

        signals_update = {
            "cfg": saved_cfg_dict,
            "learnStepsStr": learn_steps_str,
            "relearnStepsStr": relearn_steps_str,
            "dirty": False,
            "warnings": [],
            "statusMessage": "Changes reverted",
        }
        return DatastarResponse(SSE.patch_signals(signals_update))

    return router
