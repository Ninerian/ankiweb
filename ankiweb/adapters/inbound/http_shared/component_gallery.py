from __future__ import annotations

from pathlib import Path

from ankiweb.adapters.inbound.http_shared import templating

_COMPONENTS_DIR = Path(__file__).parent / "templates" / "components"


def render_component_gallery_html() -> str:
    """Render every `templates/components/_demo_*.html.jinja` on one page (dev harness).

    Each ported ts/ component ships its own demo partial, so parallel migration work never
    edits a shared gallery template. Files are discovered and sorted at request time.
    """
    demos = []
    for path in sorted(_COMPONENTS_DIR.glob("_demo_*.html.jinja")):
        name = path.name.removeprefix("_demo_").removesuffix(".html.jinja")
        demos.append(
            {
                "name": name,
                "html": templating.render(f"components/{path.name}"),
            }
        )
    return templating.render("component_gallery.html.jinja", demos=demos)
