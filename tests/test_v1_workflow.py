"""V1 end-to-end workflow through the real Streamlit app (upload -> takeoff -> UI -> Excel)."""

from __future__ import annotations

import io

import pandas as pd
import pytest

import app
from synthetic_dxf import INSUNITS_MM, PIPE_LAYER, add_line, add_lwpolyline, add_text, new_doc, to_bytes, to_text

pytest.importorskip("streamlit.testing.v1")

from streamlit_harness import (  # noqa: E402
    dataframes,
    download_button_count,
    error_texts,
    exceptions,
    metric_values,
    render_app,
    rerun,
    warning_texts,
)


def _pipe_drawing(length_mm: float = 5000.0) -> bytes:
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (length_mm, 0))
    return to_bytes(doc)


def _first_metric(app_test):
    values = metric_values(app_test)
    return values[0] if values else None


def test_same_content_different_name_reuses_result(tmp_path, monkeypatch, validation):
    """WF-02: identical bytes under a new file name give the same result and are stored once."""
    data = _pipe_drawing()
    app_test = render_app(data, tmp_path, monkeypatch, name="a.dxf")
    first = _first_metric(app_test)
    rerun(app_test, data, tmp_path, monkeypatch, name="b.dxf")
    stored = sorted(path.name for path in (tmp_path / "data" / "input").rglob("*") if path.is_file())
    validation.equal(
        "WF-02",
        "V1-UP-03 same content, different name",
        expected=("5.00 m", "5.00 m", 1, []),
        actual=(first, _first_metric(app_test), len(stored), exceptions(app_test)),
        basis="LINE 5000 mm uploaded as a.dxf then b.dxf",
        kind="WORKFLOW",
    )


def test_invalid_file_after_valid_clears_previous_result(tmp_path, monkeypatch, validation):
    """WF-03: after a valid drawing, uploading a non-DXF file shows an error and no previous result."""
    app_test = render_app(_pipe_drawing(), tmp_path, monkeypatch, name="plan.dxf")
    first = _first_metric(app_test)
    rerun(app_test, b"this is not a dxf file\n", tmp_path, monkeypatch, name="plan.dxf")
    errors = error_texts(app_test)
    validation.equal(
        "WF-03",
        "V1-UP-04 previous result cleared when the new file is invalid",
        expected=("5.00 m", None, True, []),
        actual=(first, _first_metric(app_test), any("DXF" in text for text in errors), exceptions(app_test)),
        basis="valid plan.dxf then a text file named plan.dxf",
        kind="WORKFLOW",
    )


def test_empty_file_rejected(tmp_path, monkeypatch, validation):
    """WF-04: a 0-byte upload shows an error and no result."""
    app_test = render_app(b"", tmp_path, monkeypatch, name="empty.dxf")
    validation.equal(
        "WF-04",
        "V1-UP-05 empty upload",
        expected=(None, True, []),
        actual=(_first_metric(app_test), any("пуст" in text for text in error_texts(app_test)), exceptions(app_test)),
        basis="0-byte upload",
        kind="WORKFLOW",
    )


def test_truncated_file_is_never_a_silent_result(tmp_path, monkeypatch, validation):
    """WF-05: a truncated DXF is either rejected or shown with a DRAWING_RECOVERED warning."""
    doc = new_doc(INSUNITS_MM)
    for index in range(40):
        add_line(doc, (0, index * 1000), (1000, index * 1000))
    text = to_text(doc)
    app_test = render_app(text[: int(len(text) * 0.6)].encode("utf-8"), tmp_path, monkeypatch, name="truncated.dxf")
    shown = _first_metric(app_test) is not None
    recovered_warning = any("DRAWING_RECOVERED" in text for text in warning_texts(app_test))
    rejected = any("DXF" in text for text in error_texts(app_test))
    validation.equal(
        "WF-05",
        "V1-ERR-03 truncated drawing",
        expected=(True, []),
        actual=((recovered_warning if shown else rejected), exceptions(app_test)),
        basis=f"first 60% of a 40-LINE DXF; result shown={shown}, recovered warning={recovered_warning}, rejected={rejected}",
        kind="WORKFLOW",
    )


def test_excel_export_failure_and_recovery(tmp_path, monkeypatch, validation):
    """WF-06: an Excel failure shows an error but keeps the takeoff; the next run offers the download again."""
    data = _pipe_drawing()
    app_test = render_app(data, tmp_path, monkeypatch, name="plan.dxf")
    rerun(app_test, data, tmp_path, monkeypatch, name="plan.dxf", fail_export=True)
    failed = (
        _first_metric(app_test),
        any("Excel" in text for text in error_texts(app_test)),
        download_button_count(app_test),
        exceptions(app_test),
    )
    rerun(app_test, data, tmp_path, monkeypatch, name="plan.dxf")
    recovered = (download_button_count(app_test), any("Excel" in text for text in error_texts(app_test)))
    validation.equal(
        "WF-06",
        "V1-OUT-05 export failure is visible and recoverable",
        expected=(("5.00 m", True, 0, []), (1, False)),
        actual=(failed, recovered),
        basis="LINE 5000 mm; Excel builder forced to raise on the second run only",
        kind="WORKFLOW",
    )


def _mixed_drawing() -> bytes:
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_text(doc, "ø16", (1500, 2500))
    add_line(doc, (0, 20000), (2000, 20000))
    add_text(doc, "DN20", (1000, 21000))
    add_line(doc, (40000, 0), (60000, 0))
    add_text(doc, "ø25", (40500, 300))
    add_lwpolyline(doc, [(0, 60000, 0), (1000, 60000, 0), (1000, 61000, 0), (0, 61000, 0)], closed=True)
    return to_bytes(doc)


def _ui_diameter_rows(app_test):
    for frame in dataframes(app_test):
        columns = list(frame.columns)
        if len(columns) == 3 and columns[:2] == ["Diameter", "Diameter Type"]:
            return sorted((str(row[0]), str(row[1]), round(float(row[2]), 6)) for row in frame.itertuples(index=False))
    return None


def test_ui_and_excel_are_consistent(tmp_path, monkeypatch, validation):
    """WF-07: diameter totals and warning codes in the UI equal those in the Excel workbook."""
    app_test = render_app(_mixed_drawing(), tmp_path, monkeypatch, name="mixed.dxf")
    report = app_test.session_state["dxf_report"]
    layer = app_test.session_state["dxf_layer_calculation"]
    excel = app.build_dxf_takeoff_excel(file_name="mixed.dxf", report=report, layer_calculation=layer, selected_layer=PIPE_LAYER, display_unit="m")
    sheets = pd.read_excel(io.BytesIO(excel), sheet_name=None)
    by_diameter = sheets["ПО ДИАМЕТРУ"]
    excel_rows = sorted((str(row[0]), str(row[1]), round(float(row[2]), 6)) for row in by_diameter[["Диаметр", "Тип диаметра", "Длина (м)"]].itertuples(index=False))
    ui_codes = sorted(code for code in {text.split(":")[0] for text in warning_texts(app_test)} if code.isupper())
    excel_codes = sorted(sheets["ПРЕДУПРЕЖДЕНИЯ"]["Code"].tolist())
    validation.equal(
        "WF-07",
        "V1-OUT-04 UI and Excel agree",
        expected=(True, True, []),
        actual=(_ui_diameter_rows(app_test) == excel_rows, ui_codes == excel_codes, exceptions(app_test)),
        basis=f"mixed drawing; UI rows={_ui_diameter_rows(app_test)}, Excel rows={excel_rows}, UI codes={ui_codes}, Excel codes={excel_codes}",
        kind="WORKFLOW",
    )


def test_unresolved_diameter_candidates_visible(tmp_path, monkeypatch, validation):
    """WF-08: a pipe with a marker beside it but far from its midpoint shows the candidate in the UI."""
    app_test = render_app(_mixed_drawing(), tmp_path, monkeypatch, name="mixed.dxf")
    candidates = []
    for frame in dataframes(app_test):
        if "Diameter Candidates" in frame.columns:
            candidates.extend(str(value) for value in frame["Diameter Candidates"].tolist() if value)
    validation.equal(
        "WF-08",
        "V1-DIA-06 candidates visible",
        expected=(True, True),
        actual=("Ø25" in candidates, any("DIAMETER_CANDIDATES_UNRESOLVED" in text for text in warning_texts(app_test))),
        basis="LINE 20000 mm with 'ø25' 300 mm beside it near one end",
        kind="WORKFLOW",
    )


def test_review_geometry_visible(tmp_path, monkeypatch, validation):
    """WF-09: closed polylines are flagged for review in the detail table and warned."""
    app_test = render_app(_mixed_drawing(), tmp_path, monkeypatch, name="mixed.dxf")
    flags = []
    for frame in dataframes(app_test):
        if "Geometry Flags" in frame.columns:
            flags.extend(str(value) for value in frame["Geometry Flags"].tolist() if value)
    validation.equal(
        "WF-09",
        "V1-POL-01 review geometry visible",
        expected=(True, True),
        actual=("CLOSED_POLYLINE" in flags, any("CLOSED_POLYLINES_COUNTED" in text for text in warning_texts(app_test))),
        basis="closed 1000x1000 LWPOLYLINE on П_Трубы",
        kind="WORKFLOW",
    )
