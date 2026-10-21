"""Characterisation of the current V0 takeoff rules.

PASS here means "the program still behaves as the V0 rule describes", not that the
rule is correct. Expected values are derived from the stated rule and hand
geometry, not from program output. Known defects are in test_known_issues.py.
"""

from __future__ import annotations

import ast
import io
import math
from pathlib import Path

import pandas as pd
import pytest

import app
from synthetic_dxf import (
    CENTERLINE_LAYER,
    EQUIPMENT_LAYER,
    FITTING_LAYER,
    INSUNITS_MM,
    INSUNITS_UNKNOWN,
    MM_TO_M,
    PIPE_LAYER,
    RISER_LAYER,
    VALVE_LAYER,
    add_arc,
    add_circle,
    add_insert,
    add_line,
    add_lwpolyline,
    add_mtext,
    add_text,
    new_doc,
    reload,
)

ROOT = Path(__file__).resolve().parents[1]


def _takeoff(doc, factor=MM_TO_M, remove_duplicates=True):
    return app.calculate_dxf_quantities(reload(doc), "m", factor, remove_duplicates)


def _diameter_of(report, handle):
    rows = [row for row in report["pipe_detail_rows"] if row["Handle"] == handle]
    assert len(rows) == 1, f"handle {handle} not measured exactly once"
    return rows[0]


# --- B.5 duplicates ---------------------------------------------------------------------------


def test_exact_duplicate_line_removed(validation):
    """Two identical LINEs on one pipe layer count once; the removed length is reported."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_line(doc, (0, 0), (3000, 4000))
    summary = _takeoff(doc)["summary"]
    validation.equal(
        "BEH-DUP-01",
        "exact duplicate removed (same layer)",
        expected=(5.0, 1, 5.0, 10.0),
        actual=(
            round(summary["total_pipe_length"], 9),
            summary["duplicate_entity_count"],
            round(summary["duplicate_raw_length"], 9),
            round(summary["raw_pipe_length"], 9),
        ),
        basis="2x LINE 5000 mm on П_Трубы; (final m, duplicates, duplicate m, raw m)",
    )


def test_reversed_duplicate_line_removed(validation):
    """A LINE drawn in the opposite direction over an existing LINE is treated as a duplicate."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_line(doc, (3000, 4000), (0, 0))
    summary = _takeoff(doc)["summary"]
    validation.equal(
        "BEH-DUP-02",
        "reversed duplicate removed",
        expected=(5.0, 1),
        actual=(round(summary["total_pipe_length"], 9), summary["duplicate_entity_count"]),
        basis="LINE A->B and B->A, 5000 mm, П_Трубы",
    )


def test_reversed_duplicate_lwpolyline_removed(validation):
    """A reversed copy of an LWPOLYLINE is treated as a duplicate."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (1000, 0, 0), (2000, 0, 0)])
    add_lwpolyline(doc, [(2000, 0, 0), (1000, 0, 0), (0, 0, 0)])
    summary = _takeoff(doc)["summary"]
    validation.equal(
        "BEH-DUP-03",
        "reversed LWPOLYLINE duplicate removed",
        expected=(2.0, 1),
        actual=(round(summary["total_pipe_length"], 9), summary["duplicate_entity_count"]),
        basis="2000 mm LWPOLYLINE and its reverse, П_Трубы",
    )


def test_duplicates_kept_when_removal_disabled(validation):
    """With duplicate removal switched off both copies are counted."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_line(doc, (0, 0), (3000, 4000))
    summary = _takeoff(doc, remove_duplicates=False)["summary"]
    validation.equal(
        "BEH-DUP-04",
        "duplicate removal off",
        expected=(10.0, 0),
        actual=(round(summary["total_pipe_length"], 9), summary["duplicate_entity_count"]),
        basis="2x LINE 5000 mm, remove_duplicate_geometry=False",
    )


def test_layer_view_duplicate_lengths_units(validation):
    """Selected-layer view reports duplicate length both in drawing units and in metres."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_line(doc, (0, 0), (3000, 4000))
    layer = app.calculate_layer(reload(doc), PIPE_LAYER, "m", MM_TO_M)
    validation.equal(
        "BEH-DUP-05",
        "calculate_layer duplicate_raw_length is in drawing units",
        expected=(1, 5000.0, 5.0, 5.0),
        actual=(
            layer["duplicate_entities"],
            round(layer["duplicate_raw_length"], 9),
            round(layer["duplicate_converted_length"], 9),
            round(layer["final_total_length"], 9),
        ),
        basis="2x LINE 5000 mm on П_Трубы, INSUNITS=4",
    )


# --- B.7 diameter labels ----------------------------------------------------------------------

LABEL_CASES = [
    ("BEH-DIA-01", "ø16", "DN16"),
    ("BEH-DIA-02", "Ø 20", "DN20"),
    ("BEH-DIA-03", "DN 25", "DN25"),
    ("BEH-DIA-04", "dn32", "DN32"),
    ("BEH-DIA-05", "ø16x2,0", "DN16"),
    ("BEH-DIA-06", "ø15,5", "DN15.5"),
    ("BEH-DIA-07", "\\U+00F816", "DN16"),
    ("BEH-DIA-08", "%%c16", None),
    ("BEH-DIA-09", "Ду15", None),
    ("BEH-DIA-10", "d20", None),
    ("BEH-DIA-11", "16x2.0", None),
    ("BEH-DIA-12", '1/2"', None),
]


@pytest.mark.parametrize(("case_id", "text", "expected"), LABEL_CASES)
def test_diameter_label_parsing(validation, case_id, text, expected):
    """V0 recognises only DN / Ø / ø followed by a number and always labels it 'DN<n>'."""
    validation.equal(
        case_id,
        "diameter label regex (V0)",
        expected=expected,
        actual=app._normalize_dxf_diameter_label(text),
        basis=f"marker text {text!r}",
    )


def _pipe_with_marker(text="ø16", marker_at=(1000, 1000), height=2.5, marker_layer=None, mtext=False):
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (2000, 0))
    kwargs = {} if marker_layer is None else {"layer": marker_layer}
    if mtext:
        add_mtext(doc, text, marker_at, char_height=height, **kwargs)
    else:
        add_text(doc, text, marker_at, height=height, **kwargs)
    return doc, line.dxf.handle


@pytest.mark.parametrize(
    ("case_id", "marker_at", "height", "expected"),
    [
        ("BEH-DIA-20", (1000, 1000), 2.5, ("DN16", 3000.0)),
        ("BEH-DIA-21", (1000, 2999), 2.5, ("DN16", 3000.0)),
        ("BEH-DIA-22", (1000, 3001), 2.5, ("UNKNOWN", 3000.0)),
        ("BEH-DIA-23", (1000, 3500), 500.0, ("DN16", 4000.0)),
    ],
)
def test_marker_distance_threshold(validation, case_id, marker_at, height, expected):
    """A marker is used when its distance to the pipe midpoint is <= max(3000, 8 x text height) drawing units."""
    doc, handle = _pipe_with_marker(marker_at=marker_at, height=height)
    row = _diameter_of(_takeoff(doc), handle)
    distance = math.hypot(marker_at[0] - 1000, marker_at[1])
    validation.equal(
        case_id,
        "marker proximity threshold",
        expected=expected,
        actual=(row["Diameter"], row["Marker Threshold"]),
        basis=f"LINE (0,0)-(2000,0) midpoint (1000,0); 'ø16' at {marker_at}, distance {distance:g}, height {height:g}; mm",
    )


def test_nearest_marker_wins(validation):
    """With two markers in range, the nearer one is used."""
    doc, handle = _pipe_with_marker(text="ø16", marker_at=(1000, 1000))
    add_text(doc, "DN20", (1000, 500))
    row = _diameter_of(_takeoff(doc), handle)
    validation.equal("BEH-DIA-24", "nearest marker wins", expected="DN20", actual=row["Diameter"], basis="ø16 at 1000 mm, DN20 at 500 mm")


def test_marker_on_other_layer_ignored(validation):
    """Markers are read only from the 'П_Марки труб' layer."""
    doc, handle = _pipe_with_marker(marker_layer="0")
    row = _diameter_of(_takeoff(doc), handle)
    validation.equal("BEH-DIA-25", "marker layer filter", expected="UNKNOWN", actual=row["Diameter"], basis="'ø16' on layer 0, 1000 mm away")


def test_mtext_marker(validation):
    """MTEXT markers are recognised like TEXT markers."""
    doc, handle = _pipe_with_marker(text="Ø25", mtext=True)
    row = _diameter_of(_takeoff(doc), handle)
    validation.equal("BEH-DIA-26", "MTEXT marker", expected="DN25", actual=row["Diameter"], basis="MTEXT 'Ø25' 1000 mm from midpoint")


# --- B.10 layer filters -----------------------------------------------------------------------


def test_layer_filters_and_centerline_exclusion(validation):
    """Pipe layers are those starting with 'П_Трубы' except the exact centreline layer name."""
    doc = new_doc(INSUNITS_MM)
    for index, layer in enumerate((PIPE_LAYER, RISER_LAYER, "П_ТрубыСтарые", CENTERLINE_LAYER, "Трубы", "п_трубы")):
        add_line(doc, (0, index * 10000), (1000, index * 10000), layer=layer)
    report = _takeoff(doc)
    summary = report["summary"]
    validation.equal(
        "BEH-LAYER-01",
        "prefix filter + exact centreline exclusion",
        expected=(3.0, 4.0, 1, 1.0, 0.0),
        actual=(
            round(summary["total_pipe_length"], 9),
            round(summary["raw_prefixed_pipe_length"], 9),
            summary["excluded_pipe_geometry_count"],
            round(summary["excluded_pipe_geometry_length"], 9),
            round(report["debug"]["reconciliation_difference"], 9),
        ),
        basis="1000 mm LINE on each of 6 layers; included: П_Трубы, П_Трубы_ Опуск, П_ТрубыСтарые",
    )


def test_closed_polyline_counted_as_pipe(validation):
    """Ambiguity: a closed polyline on a pipe layer is counted, though the debug filter excludes it."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)], closed=True)
    report = _takeoff(doc)
    validation.equal(
        "BEH-POL-01",
        "closed polyline policy (inconsistent)",
        expected=(4.0, 1, 0),
        actual=(
            round(report["summary"]["total_pipe_length"], 9),
            report["debug"]["pipe_layer_raw_entities"],
            report["debug"]["after_auxiliary_filter"],
        ),
        basis="closed 1000x1000 LWPOLYLINE on П_Трубы",
    )


def test_riser_symbol_counted_as_pipe(validation):
    """Ambiguity: an ARC in a riser/drop symbol is counted as pipe length; CIRCLEs are ignored."""
    doc = new_doc(INSUNITS_MM)
    add_circle(doc, (0, 0), 50.0, layer=RISER_LAYER)
    add_arc(doc, (0, 0), 50.0, 0.0, 180.0, layer=RISER_LAYER)
    report = _takeoff(doc)
    validation.close(
        "BEH-RISER-01",
        "riser symbol geometry counted",
        expected=50.0 * math.pi * MM_TO_M,
        actual=report["summary"]["total_pipe_length"],
        basis="CIRCLE r=50 + ARC r=50 0->180 on П_Трубы_ Опуск; mm",
        kind="BEHAVIOR",
    )


def test_circle_on_pipe_layer_ignored(validation):
    """CIRCLE entities do not contribute to pipe length."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    add_circle(doc, (5000, 0), 100.0)
    validation.close(
        "BEH-CIRCLE-01",
        "CIRCLE ignored",
        expected=1.0,
        actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="LINE 1000 mm + CIRCLE r=100 on П_Трубы",
        kind="BEHAVIOR",
    )


# --- B.9 blocks -------------------------------------------------------------------------------


def test_insert_classification(validation):
    """INSERTs are classified by layer and block-name keywords."""
    doc = new_doc(INSUNITS_MM)
    placements = [
        ("Радиатор 500", EQUIPMENT_LAYER),
        ("Насос циркуляционный", "0"),
        ("Отвод 90", FITTING_LAYER),
        ("Тройник", FITTING_LAYER),
        ("Переход 20x15", FITTING_LAYER),
        ("XYZ-123", FITTING_LAYER),
        ("Кран шаровой", VALVE_LAYER),
    ]
    for index, (block, layer) in enumerate(placements):
        add_insert(doc, block, (index * 1000, 50000), layer=layer)
    report = _takeoff(doc)

    def as_dict(rows):
        return {row["Type"]: row["Quantity"] for row in rows}

    validation.equal(
        "BEH-BLK-01",
        "INSERT classification",
        expected=({"Pump": 1, "Radiator": 1}, {"Elbow": 1, "Fitting": 1, "Reducer": 1, "Tee": 1}, {"Valve": 1}),
        actual=(as_dict(report["equipment_rows"]), as_dict(report["fittings_rows"]), as_dict(report["valves_rows"])),
        basis="7 INSERTs with Russian block names on equipment/fitting/valve layers",
    )


# --- B.11 Excel export -------------------------------------------------------------------------

EXCEL_DN16 = 5000.0 * MM_TO_M
EXCEL_DN20 = 1000.0 * math.pi / 2.0 * MM_TO_M
EXCEL_UNKNOWN = 2000.0 * MM_TO_M
EXCEL_FINAL = EXCEL_DN16 + EXCEL_DN20 + EXCEL_UNKNOWN
EXCEL_DUPLICATE = 5000.0 * MM_TO_M
EXCEL_CENTERLINE = 7000.0 * MM_TO_M
EXCEL_BASIS = (
    "П_Трубы: LINE 5000 mm (ø16 marker) + exact duplicate, ARC r=1000 90deg (DN20 marker), "
    "LINE 2000 mm (no marker); centreline LINE 7000 mm; INSUNITS=4"
)


@pytest.fixture(scope="module")
def excel_sheets():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_line(doc, (0, 0), (3000, 4000))
    add_text(doc, "ø16", (1500, 2500))
    add_arc(doc, (20000, 0), 1000.0, 0.0, 90.0)
    add_text(doc, "DN20", (20000, 1000))
    add_line(doc, (40000, 0), (42000, 0))
    add_line(doc, (0, 10000), (7000, 10000), layer=CENTERLINE_LAYER)
    doc = reload(doc)

    report = app.calculate_dxf_quantities(doc, "m", MM_TO_M)
    layer = app.calculate_layer(doc, PIPE_LAYER, "m", MM_TO_M)
    excel_bytes = app.build_takeoff_excel(
        file_name="synthetic.dxf",
        summary_rows=[
            {
                "Total Pipe Length (m)": round(report["summary"]["total_pipe_length"], 6),
                "Pipe Entities": report["summary"]["pipe_entity_count"],
                "Equipment Count": report["summary"]["equipment_count"],
                "Fittings Count": report["summary"]["fittings_count"],
                "Valves Count": report["summary"]["valves_count"],
                "Unit": "m",
                "Duplicates Removed": sum(report["debug"].get("duplicate_entities_by_layer", {}).values()),
                "Duplicate Length": round(report["summary"].get("duplicate_raw_length", 0.0), 6),
                "Raw Length": round(report["summary"].get("raw_prefixed_pipe_length", 0.0), 6),
                "Excluded Entities": report["summary"].get("excluded_pipe_geometry_count", 0),
                "Excluded Length": round(report["summary"].get("excluded_pipe_geometry_length", 0.0), 6),
                "Final Length": round(report["summary"]["total_pipe_length"], 6),
            }
        ],
        pipe_by_diameter_rows=report["pipe_by_diameter_rows"],
        pipes_rows=report["pipe_rows"],
        pipes_detail_rows=report["pipe_detail_rows"],
        equipment_rows=report["equipment_rows"],
        fittings_rows=report["fittings_rows"],
        valves_rows=report["valves_rows"],
        layers_rows=report["layers_rows"],
        details=layer["detail_rows"],
        layer_name=PIPE_LAYER,
        details_duplicate_count=layer["duplicate_entities"],
        details_duplicate_raw_length=layer["duplicate_raw_length"],
        details_duplicate_converted_length=layer["duplicate_converted_length"],
        object_type_rows=layer["object_type_rows"],
        unknown_review_rows=report["unknown_review_rows"],
    )
    return pd.read_excel(io.BytesIO(excel_bytes), sheet_name=None)


@pytest.mark.parametrize(
    ("case_id", "diameter", "expected"),
    [("XLS-01", "DN16", EXCEL_DN16), ("XLS-02", "DN20", EXCEL_DN20), ("XLS-03", "UNKNOWN", EXCEL_UNKNOWN)],
)
def test_excel_length_by_diameter(excel_sheets, validation, case_id, diameter, expected):
    """'ПО ДИАМЕТРУ' sheet holds the analytic length per diameter (rounded to 6 decimals)."""
    sheet = excel_sheets["ПО ДИАМЕТРУ"]
    values = sheet.loc[sheet["Диаметр"] == diameter, "Длина (м)"].tolist()
    validation.close(
        case_id,
        f"Excel length for {diameter}",
        expected=expected,
        actual=values[0] if len(values) == 1 else values,
        basis=EXCEL_BASIS,
        abs_tol=1e-6,
    )


def test_excel_diameter_total_and_percent(excel_sheets, validation):
    """Diameter rows sum to the final length and DN16 percentage equals its analytic share."""
    sheet = excel_sheets["ПО ДИАМЕТРУ"]
    dn16_percent = sheet.loc[sheet["Диаметр"] == "DN16", "Процент"].iloc[0]
    validation.close("XLS-04", "Excel diameter rows sum", expected=EXCEL_FINAL, actual=float(sheet["Длина (м)"].sum()), basis=EXCEL_BASIS, abs_tol=1e-6)
    validation.close(
        "XLS-05",
        "Excel DN16 percentage",
        expected=EXCEL_DN16 / EXCEL_FINAL * 100.0,
        actual=float(dn16_percent),
        basis=EXCEL_BASIS + "; percentage rounded to 2 decimals",
        abs_tol=0.005 + 1e-9,
    )


@pytest.mark.parametrize(
    ("case_id", "column", "expected"),
    [
        ("XLS-06", "Final Length", EXCEL_FINAL),
        ("XLS-07", "Duplicate Length", EXCEL_DUPLICATE),
        ("XLS-08", "Duplicates Removed", 1),
        ("XLS-09", "Raw Length", EXCEL_FINAL + EXCEL_DUPLICATE + EXCEL_CENTERLINE),
        ("XLS-10", "Excluded Length", EXCEL_CENTERLINE),
        ("XLS-11", "Excluded Entities", 1),
    ],
)
def test_excel_summary_sheet(excel_sheets, validation, case_id, column, expected):
    """'СВОДКА' totals: final, duplicate, raw (incl. centreline and duplicates) and excluded lengths."""
    validation.close(
        case_id,
        f"Excel СВОДКА '{column}'",
        expected=expected,
        actual=float(excel_sheets["СВОДКА"][column].iloc[0]),
        basis=EXCEL_BASIS,
        abs_tol=1e-6,
    )


def test_excel_pipe_detail_sheet(excel_sheets, validation):
    """'ТРУБЫ' lists each measured pipe entity once and sums to the final length."""
    sheet = excel_sheets["ТРУБЫ"]
    validation.equal("XLS-12", "Excel ТРУБЫ row count", expected=3, actual=len(sheet), basis=EXCEL_BASIS)
    validation.close("XLS-13", "Excel ТРУБЫ length sum", expected=EXCEL_FINAL, actual=float(sheet["Длина (м)"].sum()), basis=EXCEL_BASIS, abs_tol=1e-6)


def test_excel_details_sheet_duplicate_row(excel_sheets, validation):
    """'ДЕТАЛИ' lists unique entities of the selected layer plus a duplicate summary row."""
    sheet = excel_sheets["ДЕТАЛИ"]
    summary = sheet[sheet["ID объекта"].astype(str) == "SUMMARY"].iloc[0]
    body = sheet[sheet["ID объекта"].astype(str) != "SUMMARY"]
    validation.close("XLS-14", "ДЕТАЛИ duplicate length (m)", expected=EXCEL_DUPLICATE, actual=float(summary["Длина"]), basis=EXCEL_BASIS, abs_tol=1e-6)
    validation.close("XLS-15", "ДЕТАЛИ duplicate raw length (mm)", expected=5000.0, actual=float(summary["Raw Length"]), basis=EXCEL_BASIS, abs_tol=1e-6)
    validation.close("XLS-16", "ДЕТАЛИ unique length sum", expected=EXCEL_FINAL, actual=float(body["Длина"].sum()), basis=EXCEL_BASIS, abs_tol=1e-6)


def test_excel_unknown_review_sheet(excel_sheets, validation):
    """'UNKNOWN_REVIEW' lists the pipe without a diameter marker."""
    sheet = excel_sheets["UNKNOWN_REVIEW"]
    validation.equal(
        "XLS-17",
        "Excel UNKNOWN_REVIEW rows / length",
        expected=(1, EXCEL_UNKNOWN),
        actual=(len(sheet), round(float(sheet["Length (m)"].sum()), 6)),
        basis=EXCEL_BASIS,
    )


# --- B.12 errors and incomplete drawings ------------------------------------------------------


def test_missing_file_raises(tmp_path, validation):
    """Opening a missing DXF raises FileNotFoundError instead of returning an empty result."""
    with pytest.raises(FileNotFoundError) as error:
        app.open_dxf(tmp_path / "missing.dxf")
    validation.equal("BEH-ERR-01", "missing file", expected="FileNotFoundError", actual=type(error.value).__name__, basis="non-existent path")


def test_corrupt_file_raises(tmp_path, validation):
    """Opening a non-DXF file raises an error instead of returning an empty result."""
    path = tmp_path / "corrupt.dxf"
    path.write_bytes(b"this is not a dxf file\n")
    raised = None
    try:
        app.open_dxf(path)
    except Exception as error:  # noqa: BLE001 - any parse error is acceptable here
        raised = type(error).__name__
    validation.equal("BEH-ERR-02", "corrupt file", expected=True, actual=raised is not None, basis=f"23-byte text file (raised {raised})")


def test_empty_drawing_placeholder_row(validation):
    """An empty drawing yields total 0 and a placeholder 'UNKNOWN 0.0' diameter row."""
    report = _takeoff(new_doc(INSUNITS_MM))
    validation.equal(
        "BEH-ERR-03",
        "empty drawing output",
        expected=(0.0, [{"Diameter": "UNKNOWN", "Length (m)": 0.0}]),
        actual=(report["summary"]["total_pipe_length"], report["pipe_rows"]),
        basis="R2018 DXF with no entities",
    )


def test_unknown_units_report_raw_lengths(validation):
    """With unknown units the totals stay in drawing units (no conversion)."""
    doc = new_doc(INSUNITS_UNKNOWN)
    add_line(doc, (0, 0), (3000, 4000))
    report = _takeoff(doc, factor=None)
    validation.equal(
        "BEH-UNIT-01",
        "unknown units -> raw drawing units",
        expected=5000.0,
        actual=report["summary"]["total_pipe_length"],
        basis="LINE 5000 units, $INSUNITS=0",
    )


# --- static checks -----------------------------------------------------------------------------


def test_download_buttons_have_unique_explicit_keys_ast(validation):
    """Every st.download_button call in app.py has a unique literal key (AST check)."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "download_button":
            key = next((kw.value.value for kw in node.keywords if kw.arg == "key" and isinstance(kw.value, ast.Constant)), None)
            keys.append(key)
    validation.equal(
        "BEH-APP-01",
        "download button keys unique",
        expected=(2, True),
        actual=(len(keys), None not in keys and len(set(keys)) == len(keys)),
        basis="app.py AST",
    )
