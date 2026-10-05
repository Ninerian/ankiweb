#!/usr/bin/env python3
"""Generate icon data and Jinja templates from Anki's upstream icons.ts.

Fetches SVG icons referenced in anki's `ts/lib/components/icons.ts` and `ts/icons/`,
normalizes them, and outputs:
- ankiweb/shell/static/icons/icons_data.json
- ankiweb/adapters/inbound/http_shared/templates/components/icons.html.jinja
"""

import json
import re
import urllib.request
from pathlib import Path

ICONS_TS_URL = "https://raw.githubusercontent.com/ankitects/anki/main/ts/lib/components/icons.ts"
MDI_RAW = "https://raw.githubusercontent.com/Templarian/MaterialDesign-SVG/master/svg/"
BS_RAW = "https://raw.githubusercontent.com/twbs/icons/main/icons/"
TS_ICONS_RAW = "https://raw.githubusercontent.com/ankitects/anki/main/ts/icons/"

ROOT = Path(__file__).resolve().parent.parent
STATIC_ICONS_DIR = ROOT / "ankiweb" / "shell" / "static" / "icons"
COMPONENTS_DIR = ROOT / "ankiweb" / "adapters" / "inbound" / "http_shared" / "templates" / "components"


def fetch_icons():
    req = urllib.request.Request(ICONS_TS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        icons_ts = resp.read().decode()

    imports = dict(re.findall(r'import (\w+) from "([^"]+)";', icons_ts))
    exports = re.findall(r'export const (\w+) = \{ url: (\w+), component: (\w+) \};', icons_ts)

    icons = {}
    for exp, url_name, comp_name in exports:
        import_path = imports.get(comp_name, imports.get(url_name, ""))
        clean_path = import_path.split("?")[0]
        if clean_path.startswith("@mdi/svg/svg/"):
            svg_file = clean_path.replace("@mdi/svg/svg/", "")
            fetch_url = MDI_RAW + svg_file
        elif clean_path.startswith("bootstrap-icons/icons/"):
            svg_file = clean_path.replace("bootstrap-icons/icons/", "")
            fetch_url = BS_RAW + svg_file
        elif clean_path.startswith("../../icons/"):
            svg_file = clean_path.replace("../../icons/", "")
            fetch_url = TS_ICONS_RAW + svg_file
        else:
            continue

        try:
            req = urllib.request.Request(fetch_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp:
                raw_svg = resp.read().decode()
                s = re.sub(r"<\?xml[^>]*\?>", "", raw_svg)
                s = re.sub(r"<!DOCTYPE[^>]*>", "", s)
                s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
                icons[exp] = s.strip()
        except Exception as e:
            print(f"Warning: could not fetch {exp} from {fetch_url}: {e}")

    return icons


def build_jinja(icons: dict[str, str]) -> str:
    keys = sorted(icons.keys())
    lines = [
        "{# Upstream icon map generated from ts/lib/components/icons.ts and ts/icons/ #}",
        "{% set icon_data = {",
    ]
    for k in keys:
        val = icons[k].replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"  '{k}': '{val}',")

    lines.append("} %}")
    lines.append("")
    lines.append("{% macro icon(name, size=none, class_=\"\") %}")
    lines.append("  {% set svg = icon_data.get(name, '') %}")
    lines.append("  {% if svg %}")
    lines.append("    {% set extra_attrs = '' %}")
    lines.append("    {% if size %}{% set extra_attrs = extra_attrs ~ ' width=\"' ~ size ~ '\" height=\"' ~ size ~ '\"' %}{% endif %}")
    lines.append("    {% if class_ %}{% set extra_attrs = extra_attrs ~ ' class=\"anki-icon ' ~ class_ ~ '\"' %}{% else %}{% set extra_attrs = extra_attrs ~ ' class=\"anki-icon\"' %}{% endif %}")
    lines.append("    {% for k, v in kwargs.items() %}")
    lines.append("      {% set extra_attrs = extra_attrs ~ ' ' ~ k ~ '=\"' ~ v ~ '\"' %}")
    lines.append("    {% endfor %}")
    lines.append("    {# Inject extra_attrs into the first <svg tag #}")
    lines.append("    {{ svg | replace('<svg', '<svg ' ~ extra_attrs, 1) | safe }}")
    lines.append("  {% endif %}")
    lines.append("{% endmacro %}")
    return "\n".join(lines)


def main():
    STATIC_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = STATIC_ICONS_DIR / "icons_data.json"

    if json_path.exists():
        with open(json_path) as f:
            icons = json.load(f)
    else:
        icons = fetch_icons()
        with open(json_path, "w") as f:
            json.dump(icons, f, indent=2)

    clean_icons = {}
    for name, raw_svg in icons.items():
        s = re.sub(r"<\?xml[^>]*\?>", "", raw_svg)
        s = re.sub(r"<!DOCTYPE[^>]*>", "", s)
        s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
        clean_icons[name] = s.strip()

    with open(json_path, "w") as f:
        json.dump(clean_icons, f, indent=2)
    print(f"Wrote {len(clean_icons)} icons to {json_path}")

    jinja_content = build_jinja(clean_icons)
    jinja_path = COMPONENTS_DIR / "icons.html.jinja"
    with open(jinja_path, "w") as f:
        f.write(jinja_content)
    print(f"Wrote icon macro to {jinja_path}")


if __name__ == "__main__":
    main()
