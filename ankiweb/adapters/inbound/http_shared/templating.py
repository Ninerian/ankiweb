from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import jinja2

from ankiweb.core.i18n import tr


def tr_clean(val: str | None) -> str:
    """Clean accelerator markers, trailing colons, isolate markers, and whitespace.

    Strips Qt accelerator '&' markers ('&Notiztypen verwalten' -> 'Notiztypen verwalten',
    '&&' -> '&'), trailing ':' and surrounding whitespace, and Unicode isolates.
    """
    if val is None:
        return ""
    if not isinstance(val, str):
        val = str(val)
    val = val.replace("&&", "\x00").replace("&", "").replace("\x00", "&")
    val = val.replace("\u2068", "").replace("\u2069", "")
    val = val.strip()
    val = re.sub(r":\s*$", "", val)
    return val.strip()


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
cast(dict[str, Any], _env.globals)["tr"] = tr
_env.filters["tr_clean"] = tr_clean


def render(template_name: str, **context) -> str:
    return _env.get_template(template_name).render(**context)
