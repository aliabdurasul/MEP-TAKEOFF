"""V1 drawing loading: valid, empty, non-DXF and damaged files (V1-ERR rules)."""

from __future__ import annotations

import pytest

import app
from dxf_reader import InvalidDrawingError, load_dxf
from synthetic_dxf import INSUNITS_MM, MM_TO_M, add_line, new_doc, to_text


def _drawing_text(lines: int = 40) -> str:
    doc = new_doc(INSUNITS_MM)
    for index in range(lines):
        add_line(doc, (0, index * 1000), (1000, index * 1000))
    return to_text(doc)


def test_valid_drawing_loads_strictly(tmp_path, validation):
    """V1-ERR-01: a valid DXF opens in strict mode without recovery."""
    path = tmp_path / "valid.dxf"
    path.write_text(_drawing_text(3), encoding="utf-8")
    doc, info = load_dxf(path)
    validation.equal(
        "LD-01",
        "valid DXF -> strict mode",
        expected=("strict", 3),
        actual=(info["mode"], len(doc.modelspace().query("LINE"))),
        basis="R2018 DXF with 3 LINEs",
        kind="CONTRACT",
    )


@pytest.mark.parametrize(
    ("case_id", "content", "basis"),
    [
        ("LD-02", b"", "0-byte file"),
        ("LD-03", b"this is not a dxf file\n", "plain text"),
        ("LD-04", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "PDF header"),
    ],
)
def test_non_dxf_files_rejected(tmp_path, validation, case_id, content, basis):
    """V1-ERR-02: empty and non-DXF files are rejected with InvalidDrawingError."""
    path = tmp_path / "bad.dxf"
    path.write_bytes(content)
    try:
        load_dxf(path)
        outcome = "loaded"
    except InvalidDrawingError:
        outcome = "InvalidDrawingError"
    validation.equal(case_id, "invalid file rejected", expected="InvalidDrawingError", actual=outcome, basis=basis, kind="CONTRACT")


def test_comment_header_accepted(tmp_path, validation):
    """V1-ERR-01: a DXF starting with a 999 comment group is a valid DXF."""
    path = tmp_path / "comment.dxf"
    path.write_text("999\ncreated by test\n" + _drawing_text(1), encoding="utf-8")
    _doc, info = load_dxf(path)
    validation.equal("LD-05", "999 comment header", expected="strict", actual=info["mode"], basis="999 group before first SECTION", kind="CONTRACT")


def test_truncated_drawing_never_silently_partial(tmp_path, validation):
    """V1-ERR-03: a truncated DXF is either rejected or opened in recovery mode with a DRAWING_RECOVERED warning."""
    text = _drawing_text(40)
    path = tmp_path / "truncated.dxf"
    path.write_text(text[: int(len(text) * 0.6)], encoding="utf-8")
    try:
        doc, info = load_dxf(path)
    except InvalidDrawingError:
        outcome = ("rejected", True)
    else:
        report = app.calculate_dxf_quantities(doc, "m", MM_TO_M, load_info=info)
        warned = any(warning["Code"] == "DRAWING_RECOVERED" for warning in report["warnings"])
        outcome = (info["mode"], info["mode"] == "recovered" and warned)
    validation.equal(
        "LD-06",
        "damaged drawing is never a silent partial result",
        expected=True,
        actual=outcome[1],
        basis=f"first 60% of a 40-LINE DXF; outcome={outcome[0]}",
        kind="CONTRACT",
    )


def test_recovered_load_info_produces_warning(validation):
    """V1-ERR-03: load_info with mode 'recovered' adds a DRAWING_RECOVERED warning to the report."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    report = app.calculate_dxf_quantities(doc, "m", MM_TO_M, load_info={"mode": "recovered", "fixes": 2, "errors": 1, "messages": ["x"]})
    codes = [warning["Code"] for warning in report["warnings"]]
    validation.equal(
        "LD-07",
        "recovered drawing warned",
        expected=(True, 1.0),
        actual=("DRAWING_RECOVERED" in codes, report["summary"]["total_pipe_length"]),
        basis="synthetic load_info: 2 fixes, 1 error",
        kind="CONTRACT",
    )
