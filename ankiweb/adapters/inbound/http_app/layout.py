from collections.abc import Sequence
from pathlib import Path

from ankiweb.adapters.inbound.http_app.pwa import (
    APP_MANIFEST_PATH,
    APP_SCOPE,
    APP_SERVICE_WORKER_PATH,
    APP_THEME_COLOR_DARK,
    APP_THEME_COLOR_LIGHT,
    build_hash,
)
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.lang import ResolvedLang

_DEFAULT_LANG = ResolvedLang("en", "ltr", "en")


def render_app_page(
    title: str,
    body: str,
    *,
    active: str,
    static_dir: Path,
    scripts: Sequence[str] = (),
    lang: ResolvedLang = _DEFAULT_LANG,
    show_error_toast: bool = True,
) -> str:
    version = build_hash(static_dir)
    versioned_scripts = [
        f"{script}?v={version}"
        if script.rpartition("/")[0] == "/shell/static/app" and script.endswith(".js")
        else script
        for script in scripts
    ]
    return render(
        "app/base.html.jinja",
        title=title,
        body=body,
        active=active,
        scripts=versioned_scripts,
        app_lang=lang,
        app_asset_version=version,
        app_manifest_path=APP_MANIFEST_PATH,
        app_scope=APP_SCOPE,
        app_service_worker_path=APP_SERVICE_WORKER_PATH,
        app_theme_color_light=APP_THEME_COLOR_LIGHT,
        app_theme_color_dark=APP_THEME_COLOR_DARK,
        show_error_toast=show_error_toast,
    )
