from pathlib import Path

import anki.import_export_pb2 as ie
import pytest
from anki.collection import Collection
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def test_setup(tmp_path: Path):
    col_path = tmp_path / "c.anki2"
    col = Collection(str(col_path))
    col.close()

    tmp_dir = tmp_path / "import-tmp"
    tmp_dir.mkdir()

    settings = Settings(
        collection_path=col_path,
        import_tmp_dir=tmp_dir,
    )
    with TestClient(create_app(settings)) as client:
        yield client, tmp_dir


def test_next_import_csv_page_serves_html(test_setup):
    client, tmp_dir = test_setup
    csv_file = tmp_dir / "simple.csv"
    csv_file.write_text("Front,Back\nhello,world\nfoo,bar\n")

    r = client.get(f"/import-csv/{csv_file}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "route-import-csv" in r.text
    assert "csv-delimiter-select" in r.text
    assert "csv-notetype-select" in r.text
    assert "csv-deck-select" in r.text
    assert "csv-field-col-0" in r.text


def test_next_import_csv_path_traversal_rejected(test_setup, tmp_path):
    client, _tmp_dir = test_setup
    outside = tmp_path / "outside.csv"
    outside.write_text("a,b\n")

    r = client.get(f"/import-csv/{outside}")
    assert r.status_code == 200
    assert "not allowed" in r.text.lower()


def test_next_import_csv_tab_separated(test_setup):
    client, tmp_dir = test_setup
    tsv_file = tmp_dir / "cards.tsv"
    tsv_file.write_text("Word\tMeaning\tSample\nw1\tm1\ts1\nw2\tm2\ts2\n")

    r = client.get(f"/import-csv/{tsv_file}")
    assert r.status_code == 200
    # Tab delimiter should be selected
    assert f'value="{ie.CsvMetadata.Delimiter.TAB}" selected' in r.text


def test_next_import_csv_semicolon_separated(test_setup):
    client, tmp_dir = test_setup
    csv_file = tmp_dir / "cards_semi.csv"
    csv_file.write_text("Word;Meaning\nw1;m1\nw2;m2\n")

    r = client.get(f"/import-csv/{csv_file}")
    assert r.status_code == 200
    assert f'value="{ie.CsvMetadata.Delimiter.SEMICOLON}" selected' in r.text


def test_next_import_csv_header_directives(test_setup):
    client, tmp_dir = test_setup
    csv_file = tmp_dir / "headers.csv"
    csv_file.write_text("#separator:Semicolon\n#html:true\n#deck:CustomDeck\nFront;Back\nF1;<b>B1</b>\n")

    r = client.get(f"/import-csv/{csv_file}")
    assert r.status_code == 200
    assert "CustomDeck" in r.text
    assert "A new deck will be created" in r.text


def test_next_import_csv_update_options_datastar(test_setup):
    client, tmp_dir = test_setup
    csv_file = tmp_dir / "test_opts.csv"
    csv_file.write_text("Col1,Col2,Col3\nv1,v2,v3\n")
    col = client.app.state.service._col
    notetypes = col.models.all_names_and_ids()
    ntid = notetypes[0].id
    payload = {
        "csv_path": str(csv_file),
        "delimiter": ie.CsvMetadata.Delimiter.PIPE,
        "is_html": True,
        "notetype_id": ntid,
        "deck_id": 1,
        "dupe_resolution": ie.CsvMetadata.DupeResolution.PRESERVE,
        "match_scope": ie.CsvMetadata.MatchScope.NOTETYPE_AND_DECK,
        "global_tags": "test_tag",
        "updated_tags": "",
        "tags_column": 3,
        "field_col_0": 1,
        "field_col_1": 2,
    }
    r = client.post(
        "/import-csv/update-options",
        headers={"Datastar-Request": "true"},
        json=payload,
    )
    assert r.status_code == 200
    assert "datastar-patch-elements" in r.text
    assert "#import-csv-content" in r.text


def test_next_import_csv_submit_round_trip(test_setup):
    client, tmp_dir = test_setup
    csv_file = tmp_dir / "import_me.csv"
    csv_file.write_text("HelloWord,WorldMeaning,tag1 tag2\nFooWord,BarMeaning,tag3\n")

    # Get initial page to find default notetype id
    r_page = client.get(f"/import-csv/{csv_file}")
    assert r_page.status_code == 200

    col = client.app.state.service._col
    assert col.card_count() == 0

    notetypes = col.models.all_names_and_ids()
    basic_ntid = notetypes[0].id

    payload = {
        "csv_path": str(csv_file),
        "delimiter": ie.CsvMetadata.Delimiter.COMMA,
        "is_html": False,
        "notetype_id": basic_ntid,
        "deck_id": 1,
        "dupe_resolution": ie.CsvMetadata.DupeResolution.UPDATE,
        "match_scope": ie.CsvMetadata.MatchScope.NOTETYPE,
        "global_tags": "extra_global_tag",
        "updated_tags": "",
        "tags_column": 3,
        "field_col_0": 1,
        "field_col_1": 2,
    }

    r_submit = client.post(
        "/import-csv/submit",
        headers={"Datastar-Request": "true"},
        json=payload,
    )
    assert r_submit.status_code == 200
    assert "datastar-patch-elements" in r_submit.text
    assert "Overview" in r_submit.text
    assert "Details" in r_submit.text
    assert "Import failed" not in r_submit.text

    # Verify notes and cards in collection
    assert col.card_count() == 2
    nids = col.models.nids(basic_ntid)
    assert len(nids) == 2

    note1 = col.get_note(nids[0])
    assert note1.fields[0] in ("HelloWord", "FooWord")
    assert "extra_global_tag" in note1.tags
    assert any(t in note1.tags for t in ("tag1", "tag2", "tag3"))
