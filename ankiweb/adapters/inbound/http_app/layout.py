from collections.abc import Sequence

from ankiweb.adapters.inbound.http_shared.templating import render


def render_app_page(
    title: str, body: str, *, active: str, scripts: Sequence[str] = ()
) -> str:
    return render(
        "app/base.html.jinja", title=title, body=body, active=active, scripts=scripts
    )
