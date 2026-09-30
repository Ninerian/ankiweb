"""Tests for Image Occlusion shape serialization, cloze formatting, and backend round-trip."""

from __future__ import annotations
import re
import pytest
from pathlib import Path
from anki.collection import Collection
import anki.image_occlusion_pb2 as pb


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f1f0000000049454e44ae426082"
)


def float_to_display(num: float) -> str:
    if num == 0.0:
        return ".0000"
    s = f"{num:.4f}"
    # strip leading zeroes before decimal and trailing zeroes
    parts = s.split(".")
    integer_part = parts[0].lstrip("0")
    fraction_part = parts[1].rstrip("0")
    if not fraction_part:
        return integer_part if integer_part else ".0000"
    return f"{integer_part}.{fraction_part}"


def test_float_to_display():
    assert float_to_display(0.0) == ".0000"
    assert float_to_display(0.1) == ".1"
    assert float_to_display(0.25) == ".25"
    assert float_to_display(0.1234) == ".1234"


def test_cloze_format_against_backend(tmp_path):
    col_path = tmp_path / "collection.anki2"
    col = Collection(str(col_path))
    col.add_image_occlusion_notetype()

    img_file = tmp_path / "test.png"
    img_file.write_bytes(PNG_BYTES)

    # Test rect, ellipse, polygon, and text shapes
    cloze_str = (
        "{{c1::image-occlusion:rect:left=.05:top=.0704:width=.25:height=.3333:oi=1}}<br>"
        "{{c2::image-occlusion:ellipse:left=.525:top=.4037:rx=.125:ry=.1667:oi=1}}<br>"
        "{{c3::image-occlusion:polygon:points=.1,.1 .2,.3 .4,.2:oi=1}}<br>"
        "{{c0::image-occlusion:text:left=.2:top=.3:text=Sample:scale=1:oi=1}}<br>"
    )

    req = pb.AddImageOcclusionNoteRequest(
        notetype_id=0,
        image_path=str(img_file),
        occlusions=cloze_str,
        header="Test Header",
        back_extra="Test Extra",
        tags=["io-test"]
    )
    col._backend.add_image_occlusion_note_raw(req.SerializeToString())

    note_ids = col.find_notes("tag:io-test")
    assert len(note_ids) == 1
    note_id = note_ids[0]

    get_req = pb.GetImageOcclusionNoteRequest(note_id=note_id)
    get_res = pb.GetImageOcclusionNoteResponse()
    raw = col._backend.get_image_occlusion_note_raw(get_req.SerializeToString())
    get_res.ParseFromString(raw)

    note_pb = get_res.note
    assert note_pb.header == "Test Header"
    assert note_pb.back_extra == "Test Extra"
    assert "io-test" in note_pb.tags

    # Verify shapes
    ordinals = [occ.ordinal for occ in note_pb.occlusions]
    assert 1 in ordinals
    assert 2 in ordinals
    assert 3 in ordinals

    col.close()
