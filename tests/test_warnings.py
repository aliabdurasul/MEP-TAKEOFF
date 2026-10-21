"""Stage 2A regression tests: unit labels, empty results, unsupported entities and XREFs.

Rules under test: quantities are never changed or estimated; anything the takeoff
does not measure is reported with its layer, type and count; lengths without a
known unit are never labelled as metres. Expected values follow from the
synthetic drawings in stage2a_fixtures.py.
"""

from __future__ import annotations

import io

import pandas as pd

import app
from stage2a_fixtures import (
    XREF_FILE,
    XREF_NAME,
    clean_drawing,
    empty_drawing,
    known_units_drawing,
    no_pipe_drawing,
    ordinary_block_drawing,
    unknown_units_drawing,
    unsupported_drawing,
    xref_drawing,
)
from synthetic_dxf import MM_TO_M, PIPE_LAYER, RISER_LAYER, reload


def _report(doc, factor=MM_TO_M):
    return app.calculate_dxf_quantities(reload(doc), "m", factor)


def _codes(report) -> list[str]:
    return sorted(str(warning.get("Code")) for warning in report.get("warnings") or [])


def _warning(report, code):
    matches = [warning for warning in report.get("warnings") or [] if warning.get("Code") == code]
    return matches[0] if matches else None


def _excel_sheets(doc, factor=MM_TO_M, display_unit="m"):
    reloaded = reload(doc)
    report = app.calculate_dxf_quantities(reloaded, "m", factor)
    layer = app.calculate_layer(reloaded, PIPE_LAYER, display_unit, factor)
    excel = app.build_dxf_takeoff_excel(
        file_name="synthetic.dxf",
        report=report,
        layer_calculation=layer,
        selected_layer=PIPE_LAYER,
        display_unit=display_unit,
    )
    return pd.read_excel(io.BytesIO(excel), sheet_name=None)


# --- KI-WARN-01: lengths in unknown units are not labelled as metres --------------------------


def test_unknown_units_declared_in_report(validation):
    """With unknown units the report declares 'drawing units', warns, and keeps the raw value."""
    report = _report(unknown_units_drawing(), factor=None)
    validation.equal(
        "W-UNIT-01",
        "unknown units: unit declared, warning raised, value unchanged",
        expected=("drawing units", ["UNKNOWN_UNITS"], 5000.0),
        actual=(report["summary"].get("length_unit"), _codes(report), report["summary"]["total_pipe_length"]),
        basis="$INSUNITS=0, LINE (0,0)-(3000,4000) = 5000 drawing units on П_Трубы",
        kind="WARNING",
    )


def test_known_units_unchanged(validation):
    """With known units the report declares metres and raises no unit warning."""
    report = _report(known_units_drawing())
    validation.equal(
        "W-UNIT-02",
        "known units: metres, no warning",
        expected=("m", [], 5.0),
        actual=(report["summary"].get("length_unit"), _codes(report), report["summary"]["total_pipe_length"]),
        basis="$INSUNITS=4, LINE 5000 mm on П_Трубы",
        kind="WARNING",
    )


def _metre_labelled_columns(sheets) -> list[str]:
    return sorted(
        f"{sheet}:{column}"
        for sheet, frame in sheets.items()
        for column in frame.columns
        if "(m)" in str(column) or "(м)" in str(column)
    )


def test_excel_unknown_units_not_labelled_metres(validation):
    """Excel: with unknown units no column header claims metres; the value stays 5000 drawing units."""
    sheets = _excel_sheets(unknown_units_drawing(), factor=None, display_unit="Единицы чертежа")
    by_diameter = sheets["ПО ДИАМЕТРУ"]
    validation.equal(
        "XLS-W-01",
        "Excel headers for unknown units",
        expected=([], ["Диаметр", "Длина (ед. чертежа)", "Процент"], [5000.0]),
        actual=(_metre_labelled_columns(sheets), list(by_diameter.columns), by_diameter.iloc[:, 1].tolist()),
        basis="$INSUNITS=0, LINE 5000 drawing units",
        kind="WARNING",
    )


def test_excel_known_units_headers_unchanged(validation):
    """Excel: with known units the metre headers are exactly as before."""
    sheets = _excel_sheets(known_units_drawing())
    validation.equal(
        "XLS-W-02",
        "Excel headers for known units preserved",
        expected=(["Диаметр", "Длина (м)", "Процент"], True, True, True),
        actual=(
            list(sheets["ПО ДИАМЕТРУ"].columns),
            "Длина (м)" in sheets["ТРУБЫ"].columns,
            "Total Pipe Length (m)" in sheets["СВОДКА"].columns,
            "Length (m)" in sheets["UNKNOWN_REVIEW"].columns,
        ),
        basis="$INSUNITS=4, LINE 5000 mm",
        kind="WARNING",
    )


# --- KI-WARN-02: no placeholder row when there is no pipe geometry ----------------------------


def test_empty_drawing_has_no_placeholder(validation):
    """An empty drawing yields no diameter rows, total 0 and a NO_PIPE_GEOMETRY warning."""
    report = _report(empty_drawing())
    validation.equal(
        "W-EMPTY-01",
        "empty drawing: no fake UNKNOWN row",
        expected=([], [], 0.0, ["NO_PIPE_GEOMETRY"]),
        actual=(report["pipe_rows"], report["pipe_by_diameter_rows"], report["summary"]["total_pipe_length"], _codes(report)),
        basis="R2018 DXF with no entities, $INSUNITS=4",
        kind="WARNING",
    )


def test_drawing_without_pipe_layers_has_no_placeholder(validation):
    """Geometry only on non-pipe layers yields no diameter rows and a NO_PIPE_GEOMETRY warning."""
    report = _report(no_pipe_drawing())
    validation.equal(
        "W-EMPTY-02",
        "no pipe geometry: no fake UNKNOWN row",
        expected=([], [], 0.0, ["NO_PIPE_GEOMETRY"]),
        actual=(report["pipe_rows"], report["pipe_by_diameter_rows"], report["summary"]["total_pipe_length"], _codes(report)),
        basis="LINE 1000 mm on layer 0 only",
        kind="WARNING",
    )


def test_real_unknown_diameter_row_kept(validation):
    """A measured pipe without a diameter marker still produces its UNKNOWN row."""
    report = _report(known_units_drawing())
    validation.equal(
        "W-EMPTY-03",
        "genuine UNKNOWN diameter row preserved",
        expected=[{"Diameter": "UNKNOWN", "Length (m)": 5.0}],
        actual=report["pipe_rows"],
        basis="LINE 5000 mm on П_Трубы, no marker",
        kind="WARNING",
    )


def test_excel_empty_drawing_has_no_diameter_rows(validation):
    """Excel: an empty drawing has no rows in 'ПО ДИАМЕТРУ'."""
    sheets = _excel_sheets(empty_drawing())
    validation.equal(
        "XLS-W-03",
        "Excel empty drawing",
        expected=0,
        actual=len(sheets["ПО ДИАМЕТРУ"]),
        basis="R2018 DXF with no entities",
        kind="WARNING",
    )


# --- KI-UNS-01: non-measured entities on pipe layers are reported ----------------------------


def _unsupported_rows(report):
    return [
        (row.get("Layer"), row.get("Entity Type"), row.get("Count"))
        for row in report.get("unsupported_pipe_entities") or []
    ]


def test_unsupported_entities_reported_by_layer_and_type(validation):
    """Every non-measured entity on an included pipe layer is listed by layer and type."""
    doc, expected = unsupported_drawing()
    report = _report(doc)
    validation.equal(
        "W-UNS-01",
        "unsupported entities listed (layer, type, count)",
        expected=sorted((layer, entity_type, 1) for layer, entity_type in expected),
        actual=_unsupported_rows(report),
        basis="П_Трубы: LINE + SPLINE + ELLIPSE + CIRCLE + TEXT; П_Трубы_ Опуск: SPLINE; SPLINE on 0 and centreline (not reported)",
        kind="WARNING",
    )


def test_unsupported_entities_not_added_to_quantities(validation):
    """Unsupported entities are reported, never measured: total stays the LINE length."""
    doc, _expected = unsupported_drawing()
    report = _report(doc)
    warning = _warning(report, "UNSUPPORTED_PIPE_ENTITIES")
    validation.equal(
        "W-UNS-02",
        "no estimated length; warning count",
        expected=(1.0, 1, 5, 5),
        actual=(
            report["summary"]["total_pipe_length"],
            report["summary"]["pipe_entity_count"],
            report["summary"].get("unsupported_pipe_entity_count"),
            None if warning is None else warning.get("Count"),
        ),
        basis="LINE 1000 mm + 5 non-measured entities on pipe layers",
        kind="WARNING",
    )


def test_unsupported_entity_handles_listed(validation):
    """The report lists the handles of the non-measured entities."""
    doc, expected = unsupported_drawing()
    report = _report(doc)
    listed = set()
    for row in report.get("unsupported_pipe_entities") or []:
        listed.update(handle.strip() for handle in str(row.get("Handles", "")).split(",") if handle.strip())
    validation.equal(
        "W-UNS-03",
        "handles traceable",
        expected=sorted(expected.values()),
        actual=sorted(listed),
        basis="5 non-measured entities on П_Трубы and П_Трубы_ Опуск",
        kind="WARNING",
    )


def test_pipe_layer_entity_accounting(validation):
    """Measured + reported entities equal all entities on included pipe layers."""
    doc, expected = unsupported_drawing()
    report = _report(doc)
    accounted = report["summary"]["pipe_entity_count"] + sum(row[2] for row in _unsupported_rows(report))
    validation.equal(
        "W-UNS-04",
        "every pipe-layer entity accounted for",
        expected=1 + len(expected),
        actual=accounted,
        basis="6 entities on included pipe layers (1 LINE + 5 others)",
        kind="WARNING",
    )


def test_unsupported_warning_message(validation):
    """The warning names the entity types and the layers."""
    doc, _expected = unsupported_drawing()
    message = str((_warning(_report(doc), "UNSUPPORTED_PIPE_ENTITIES") or {}).get("Message", ""))
    validation.equal(
        "W-UNS-05",
        "warning text names types and layers",
        expected=(True, True, True, True),
        actual=("SPLINE: 2" in message, "ELLIPSE: 1" in message, PIPE_LAYER in message, RISER_LAYER in message),
        basis="SPLINE x2, ELLIPSE, CIRCLE, TEXT on pipe layers",
        kind="WARNING",
    )


# --- KI-XREF-01: external references are reported, not processed ------------------------------


def test_inserted_xref_reported(validation):
    """An inserted XREF is reported by name, path and insert count; quantities are unchanged."""
    report = _report(xref_drawing(inserted=True))
    validation.equal(
        "W-XREF-01",
        "XREF reported, not processed",
        expected=([{"Name": XREF_NAME, "Path": XREF_FILE, "Model Space Inserts": 1, "Overlay": False}], ["XREF_NOT_PROCESSED"], 1.0),
        actual=(report.get("xrefs"), _codes(report), report["summary"]["total_pipe_length"]),
        basis=f"LINE 1000 mm + XREF {XREF_NAME} -> {XREF_FILE} inserted once",
        kind="WARNING",
    )


def test_defined_but_not_inserted_xref_reported(validation):
    """An XREF definition without inserts is still reported (0 inserts)."""
    report = _report(xref_drawing(inserted=False))
    xrefs = report.get("xrefs") or []
    validation.equal(
        "W-XREF-02",
        "XREF definition reported",
        expected=([0], ["XREF_NOT_PROCESSED"]),
        actual=([row.get("Model Space Inserts") for row in xrefs], _codes(report)),
        basis=f"XREF {XREF_NAME} defined, not inserted",
        kind="WARNING",
    )


def test_xref_warning_message(validation):
    """The XREF warning names the reference and its file."""
    message = str((_warning(_report(xref_drawing()), "XREF_NOT_PROCESSED") or {}).get("Message", ""))
    validation.equal(
        "W-XREF-03",
        "XREF warning text",
        expected=(True, True),
        actual=(XREF_NAME in message, XREF_FILE in message),
        basis=f"XREF {XREF_NAME} -> {XREF_FILE}",
        kind="WARNING",
    )


def test_ordinary_block_is_not_an_xref(validation):
    """An ordinary block reference produces no XREF warning."""
    report = _report(ordinary_block_drawing())
    validation.equal(
        "W-XREF-04",
        "no false XREF warning",
        expected=([], []),
        actual=(report.get("xrefs"), _codes(report)),
        basis="LINE on П_Трубы + INSERT 'Радиатор 500' on layer 0",
        kind="WARNING",
    )


def test_clean_drawing_has_no_warnings(validation):
    """A drawing with known units, measured pipe and marker has no warnings."""
    report = _report(clean_drawing())
    validation.equal(
        "W-CLEAN-01",
        "no false warnings",
        expected=([], [], []),
        actual=(report.get("warnings"), report.get("unsupported_pipe_entities"), report.get("xrefs")),
        basis="LINE 2000 mm + 'ø16' marker, $INSUNITS=4",
        kind="WARNING",
    )


def test_excel_warning_sheets(validation):
    """Excel lists warnings and non-measured entities on their own sheets."""
    doc, expected = unsupported_drawing()
    doc.add_xref_def(XREF_FILE, XREF_NAME)
    sheets = _excel_sheets(doc)
    warnings_sheet = sheets.get("ПРЕДУПРЕЖДЕНИЯ")
    unmeasured = sheets.get("НЕ ИЗМЕРЕНО")
    validation.equal(
        "XLS-W-04",
        "Excel warning sheets",
        expected=(["UNSUPPORTED_PIPE_ENTITIES", "XREF_NOT_PROCESSED"], sorted((layer, entity_type, 1) for layer, entity_type in expected)),
        actual=(
            None if warnings_sheet is None else sorted(warnings_sheet["Code"].tolist()),
            None
            if unmeasured is None
            else sorted((str(layer), str(entity_type), int(count)) for layer, entity_type, count in zip(unmeasured["Layer"], unmeasured["Entity Type"], unmeasured["Count"])),
        ),
        basis="unsupported_drawing + XREF definition",
        kind="WARNING",
    )
