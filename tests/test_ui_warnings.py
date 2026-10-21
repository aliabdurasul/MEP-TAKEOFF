"""Stage 2A: warnings and unit labels as actually rendered by the Streamlit app."""

from __future__ import annotations

import pytest

from stage2a_fixtures import XREF_NAME, clean_drawing, no_pipe_drawing, unknown_units_drawing, unsupported_drawing, xref_drawing
from synthetic_dxf import PIPE_LAYER, to_bytes

pytest.importorskip("streamlit.testing.v1")

from streamlit_harness import dataframes, exceptions, render_app, warning_texts  # noqa: E402

WARNING_CODES = ("UNKNOWN_UNITS", "NO_PIPE_GEOMETRY", "UNSUPPORTED_PIPE_ENTITIES", "XREF_NOT_PROCESSED")


def _diameter_summary_rows(app_test):
    rows = []
    for frame in dataframes(app_test):
        columns = list(frame.columns)
        if len(columns) == 2 and columns[0] == "Diameter":
            rows.extend((str(diameter), float(length)) for diameter, length in frame.itertuples(index=False))
    return rows


def _codes_shown(app_test) -> list[str]:
    texts = warning_texts(app_test)
    return [code for code in WARNING_CODES if any(code in text for text in texts)]


def test_ui_unknown_units_not_labelled_metres(tmp_path, monkeypatch, validation):
    """UI: with unknown units no table column claims metres and the unit warning is shown."""
    app_test = render_app(to_bytes(unknown_units_drawing()), tmp_path, monkeypatch)
    metre_columns = sorted({str(column) for frame in dataframes(app_test) for column in frame.columns if "(m)" in str(column) or "(м)" in str(column)})
    validation.equal(
        "UI-W-01",
        "UI unit labels for unknown units",
        expected=([], [], True),
        actual=(exceptions(app_test), metre_columns, "UNKNOWN_UNITS" in _codes_shown(app_test)),
        basis="$INSUNITS=0, LINE 5000 drawing units on П_Трубы",
        kind="WARNING",
    )


def test_ui_no_pipe_geometry(tmp_path, monkeypatch, validation):
    """UI: without pipe geometry no UNKNOWN 0.0 row is shown and the warning is visible."""
    app_test = render_app(to_bytes(no_pipe_drawing()), tmp_path, monkeypatch)
    validation.equal(
        "UI-W-02",
        "UI: no fake UNKNOWN row, warning shown",
        expected=([], [], ["NO_PIPE_GEOMETRY"]),
        actual=(exceptions(app_test), _diameter_summary_rows(app_test), _codes_shown(app_test)),
        basis="LINE 1000 mm on layer 0 only, $INSUNITS=4",
        kind="WARNING",
    )


def test_ui_unsupported_entities(tmp_path, monkeypatch, validation):
    """UI: the unsupported-entity warning and its layer/type table are shown."""
    doc, expected = unsupported_drawing()
    app_test = render_app(to_bytes(doc), tmp_path, monkeypatch)
    texts = [text for text in warning_texts(app_test) if "UNSUPPORTED_PIPE_ENTITIES" in text]
    table = []
    for frame in dataframes(app_test):
        if {"Layer", "Entity Type", "Count"} <= set(frame.columns):
            table.extend((str(row["Layer"]), str(row["Entity Type"]), int(row["Count"])) for _, row in frame.iterrows())
    validation.equal(
        "UI-W-03",
        "UI: unsupported entities visible",
        expected=([], True, sorted((layer, entity_type, 1) for layer, entity_type in expected)),
        actual=(exceptions(app_test), bool(texts) and "SPLINE" in texts[0] and "ELLIPSE" in texts[0] and PIPE_LAYER in texts[0], sorted(table)),
        basis="П_Трубы: LINE + SPLINE + ELLIPSE + CIRCLE + TEXT; П_Трубы_ Опуск: SPLINE",
        kind="WARNING",
    )


def test_ui_xref_warning(tmp_path, monkeypatch, validation):
    """UI: the XREF warning names the reference."""
    app_test = render_app(to_bytes(xref_drawing()), tmp_path, monkeypatch)
    texts = [text for text in warning_texts(app_test) if "XREF_NOT_PROCESSED" in text]
    validation.equal(
        "UI-W-04",
        "UI: XREF warning visible",
        expected=([], True),
        actual=(exceptions(app_test), bool(texts) and XREF_NAME in texts[0]),
        basis=f"LINE 1000 mm + XREF {XREF_NAME} inserted once",
        kind="WARNING",
    )


def test_ui_clean_drawing_has_no_takeoff_warnings(tmp_path, monkeypatch, validation):
    """UI: a clean drawing shows none of the Stage 2A warnings and still shows its diameter row."""
    app_test = render_app(to_bytes(clean_drawing()), tmp_path, monkeypatch)
    validation.equal(
        "UI-W-05",
        "UI: no false warnings",
        expected=([], [], [("DN16", 2.0)]),
        actual=(exceptions(app_test), _codes_shown(app_test), _diameter_summary_rows(app_test)),
        basis="LINE 2000 mm + 'ø16' marker, $INSUNITS=4",
        kind="WARNING",
    )
