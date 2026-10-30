from collections.abc import Sequence

from ankiweb.adapters.inbound.http_app.pwa import (
    APP_MANIFEST_PATH,
    APP_SCOPE,
    APP_SERVICE_WORKER_PATH,
    APP_THEME_COLOR_DARK,
    APP_THEME_COLOR_LIGHT,
)
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.lang import ResolvedLang

_DEFAULT_LANG = ResolvedLang("en", "ltr", "en")


def render_app_page(
    title: str,
    body: str,
    *,
    active: str,
    scripts: Sequence[str] = (),
    lang: ResolvedLang = _DEFAULT_LANG,
) -> str:
    return render(
        "app/base.html.jinja",
        title=title,
        body=body,
        active=active,
        scripts=scripts,
        app_lang=lang,
        app_manifest_path=APP_MANIFEST_PATH,
        app_scope=APP_SCOPE,
        app_service_worker_path=APP_SERVICE_WORKER_PATH,
        app_theme_color_light=APP_THEME_COLOR_LIGHT,
        app_theme_color_dark=APP_THEME_COLOR_DARK,
    )
