import pytest
from ankiweb.adapters.inbound.http_shared.routes import _MIME_EXT


def test_media_upload_mime_types():
    assert _MIME_EXT.get("image/png") == ".png"
    assert _MIME_EXT.get("image/jpeg") == ".jpg"
    assert _MIME_EXT.get("image/svg+xml") == ".svg"


def test_html_filter_rules_presence():
    import os
    bundle_path = "ankiweb/shell/static/bundles/editor-overlays.js"
    assert os.path.exists(bundle_path)
    with open(bundle_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Check that filterHTML, mathjax, image overlay are bundled
    assert "filterHTML" in content
    assert "toStoredMathjax" in content
    assert "ankiweb-image-handle" in content


def test_editor_plain_codemirror_bundle():
    import os
    bundle_path = "ankiweb/shell/static/bundles/editor-plain.js"
    assert os.path.exists(bundle_path)
    with open(bundle_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "EditorView" in content or "cm-editor" in content
    assert "toggleFieldPlainText" in content
