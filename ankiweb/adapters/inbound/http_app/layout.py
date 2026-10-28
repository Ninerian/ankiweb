from collections.abc import Sequence

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
    )
