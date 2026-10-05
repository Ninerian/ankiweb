import anki.lang

from ankiweb.adapters.inbound.http_shared.templating import tr_clean
from ankiweb.core.i18n import tr


def test_tr_clean_accelerators():
    assert tr_clean("&Notiztypen verwalten") == "Notiztypen verwalten"
    assert tr_clean("E&xtras") == "Extras"
    assert tr_clean("&File") == "File"
    assert tr_clean("Save && re-push") == "Save & re-push"
    assert tr_clean("&&") == "&"


def test_tr_clean_colons():
    assert tr_clean("Notiztypen:") == "Notiztypen"
    assert tr_clean("Name: ") == "Name"
    assert tr_clean("Export:   ") == "Export"
    assert tr_clean("  Zielfeld:  ") == "Zielfeld"


def test_tr_clean_isolates_and_whitespace():
    assert tr_clean("\u20683\u2069 notes") == "3 notes"
    assert tr_clean("  \u20685\u2069\xa0Notizen  ") == "5\xa0Notizen"
    assert tr_clean(None) == ""
    assert tr_clean("") == ""


def test_tr_clean_combined():
    assert tr_clean("&Leere Karten löschen …") == "Leere Karten löschen …"
    assert tr_clean("  &Options:  ") == "Options"


def test_tr_clean_with_anki_keys():
    anki.lang.set_lang("de")
    assert tr_clean(tr.qt_misc_manage_note_types()) == "Notiztypen verwalten"
    assert tr_clean(tr.notetypes_note_types()) == "Notiztypen"
    assert tr_clean(tr.qt_accel_tools()) == "Extras"
    assert tr_clean(tr.actions_name()) == "Name"
