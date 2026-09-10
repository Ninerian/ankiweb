from __future__ import annotations
from pathlib import Path
import jinja2
from ankiweb.i18n import tr

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals["tr"] = tr


def render(template_name: str, **context) -> str:
    return _env.get_template(template_name).render(**context)
