"""Every quantity difference from ``main`` must be an intended V1 change.

``MEP_BASELINE_DIR`` must contain ``app.py`` and ``excel_export.py`` from ``main``
(CI extracts them). Fixtures in UNCHANGED must match main exactly once the new
V1 fields are ignored and the intended label rename (outside diameter written as
'Ø16' instead of 'DN16', V1-DIA-01) is normalised. Fixtures in INTENDED may only
differ in the listed report paths, and their before/after values are asserted.
"""

from __future__ import annotations

import importlib.util
import io
import math
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

import app
from stage2a_fixtures import empty_drawing, no_pipe_drawing, unknown_units_drawing, unsupported_drawing, xref_drawing
from synthetic_dxf import (
    CENTERLINE_LAYER,
    EQUIPMENT_LAYER,
    FITTING_LAYER,
    INSUNITS_INCH,
    INSUNITS_M,
    INSUNITS_MM,
    PIPE_LAYER,
    RISER_LAYER,
    VALVE_LAYER,
    add_arc,
    add_circle,
    add_insert,
    add_line,
    add_lwpolyline,
    add_text,
    ensure_layer,
    new_doc,
    reload,
)

BASELINE_DIR = Path(os.environ["MEP_BASELINE_DIR"]).resolve() if os.environ.get("MEP_BASELINE_DIR") else None

pytestmark = pytest.mark.skipif(
    BASELINE_DIR is None,
    reason="NOT RUN: MEP_BASELINE_DIR (app.py and excel_export.py from main) is not set; CI sets it",
)

V1_REPORT_KEYS = {
    "warnings",
    "unsupported_pipe_entities",
    "xrefs",
    "unrecognized_inserts",
    "pipe_geometry_in_blocks",
    "pipe_layer_findings",
    "pipe_layer_rows",
}
V1_IGNORED_PATHS = {"debug.notes"}
LABEL_KEYS = {"Diameter", "Nearest Marker Label"}
PLACEHOLDER_REMOVAL_DIFF = ["debug.unknown_dn_count", "pipe_by_diameter_rows", "pipe_rows"]
DIAMETER_CHANGE_PATHS = {
    "category_diameter_rows",
    "debug.identified_dn_count",
    "debug.unknown_dn_count",
    "pipe_by_diameter_rows",
    "pipe_detail_rows",
    "pipe_rows",
    "unknown_review_rows",
}


BASELINE_DEPENDENCIES = ("geometry", "dxf_reader", "excel_export")


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, BASELINE_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def baseline_modules():
    """main's app.py bound to main's geometry, dxf_reader and excel_export (not this branch's)."""

    loaded = {name: _load(f"baseline_{name}", f"{name}.py") for name in BASELINE_DEPENDENCIES}
    saved = {name: sys.modules.get(name) for name in BASELINE_DEPENDENCIES}
    try:
        sys.modules.update(loaded)
        loaded["app"] = _load("baseline_app", "app.py")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return loaded


@pytest.fixture(scope="module")
def baseline_app(baseline_modules):
    return baseline_modules["app"]


@pytest.fixture(scope="module")
def baseline_excel(baseline_modules):
    return baseline_modules["excel_export"]


def test_baseline_uses_main_modules(baseline_modules, validation):
    """The baseline app is bound to main's geometry, not to this branch's."""
    import geometry

    validation.equal(
        "EQ-BASE-01",
        "baseline isolation",
        expected=(True, False),
        actual=(
            baseline_modules["app"].measure_entity is baseline_modules["geometry"].measure_entity,
            baseline_modules["app"].measure_entity is geometry.measure_entity,
        ),
        basis="baseline app.measure_entity identity",
        kind="EQUIVALENCE",
    )


def _normalise(key, value):
    if key in LABEL_KEYS and isinstance(value, str) and value.startswith("Ø"):
        return "DN" + value[1:]
    return value


def _project_rows(rows, keys):
    """Rows restricted to main's columns, labels normalised, order-insensitive (V1 sorts diameters naturally)."""

    projected = [{key: _normalise(key, row.get(key)) for key in sorted(keys)} for row in rows]
    return sorted(projected, key=repr)


def _differences(new: dict, old: dict) -> list[str]:
    paths = []
    for key in sorted(set(new) | set(old)):
        if key in V1_REPORT_KEYS:
            continue
        new_value, old_value = new.get(key), old.get(key)
        if key in {"summary", "debug"}:
            for sub_key in sorted(old_value or {}):
                if f"{key}.{sub_key}" in V1_IGNORED_PATHS:
                    continue
                if new_value.get(sub_key) != old_value.get(sub_key):
                    paths.append(f"{key}.{sub_key}")
        elif isinstance(new_value, list) and isinstance(old_value, list) and all(isinstance(row, dict) for row in new_value + old_value):
            keys = set().union(*(row.keys() for row in old_value)) if old_value else set()
            if _project_rows(new_value, keys) != _project_rows(old_value, keys) or (not old_value and new_value):
                paths.append(key)
        elif new_value != old_value:
            paths.append(key)
    return paths


def _mixed_mm():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_line(doc, (0, 0), (3000, 4000))
    add_text(doc, "ø16", (1500, 2500))
    add_arc(doc, (20000, 0), 1000.0, 0.0, 90.0)
    add_text(doc, "DN20", (20000, 1000))
    add_line(doc, (40000, 0), (42000, 0))
    add_line(doc, (0, 10000), (7000, 10000), layer=CENTERLINE_LAYER)
    add_lwpolyline(doc, [(60000, 0, 0), (61000, 0, 0), (61000, 1000, 0), (60000, 1000, 0)], closed=True)
    add_circle(doc, (80000, 0), 50.0, layer=RISER_LAYER)
    add_arc(doc, (80000, 0), 50.0, 0.0, 180.0, layer=RISER_LAYER)
    add_lwpolyline(doc, [(90000, 0, 1.0), (92000, 0, 0)])
    for index, (block, layer) in enumerate((("Радиатор 500", EQUIPMENT_LAYER), ("Отвод 90", FITTING_LAYER), ("Кран шаровой", VALVE_LAYER))):
        add_insert(doc, block, (index * 1000, 50000), layer=layer)
    return doc


def _inches_with_bulge():
    doc = new_doc(INSUNITS_INCH)
    add_lwpolyline(doc, [(0, 0, 0), (100, 0, 0.5), (200, 50, 0)])
    return doc


UNCHANGED = {
    "mixed_mm": (_mixed_mm, 0.001, []),
    "unknown_units": (unknown_units_drawing, None, []),
    "inches_bulge": (_inches_with_bulge, 0.0254, []),
    "unsupported": (lambda: unsupported_drawing()[0], 0.001, []),
    "xref": (xref_drawing, 0.001, []),
    "empty": (empty_drawing, 0.001, PLACEHOLDER_REMOVAL_DIFF),
    "no_pipe": (no_pipe_drawing, 0.001, PLACEHOLDER_REMOVAL_DIFF),
}


@pytest.mark.parametrize("remove_duplicates", [True, False], ids=["dedup_on", "dedup_off"])
@pytest.mark.parametrize("name", sorted(UNCHANGED))
def test_unchanged_fixtures_match_main(baseline_app, validation, name, remove_duplicates):
    """Fixtures without an intended V1 change produce main's quantities and classifications."""
    builder, factor, expected = UNCHANGED[name]
    doc = reload(builder())
    new = app.calculate_dxf_quantities(doc, "m", factor, remove_duplicates)
    old = baseline_app.calculate_dxf_quantities(doc, "m", factor, remove_duplicates)
    validation.equal(
        f"EQ-{name}-{'dedup' if remove_duplicates else 'nodedup'}",
        "unchanged vs main (V1 fields ignored, Ø/DN rename normalised)",
        expected=expected,
        actual=_differences(new, old),
        basis=f"fixture '{name}', meters_per_unit={factor}, remove_duplicates={remove_duplicates}; differing report paths",
        kind="EQUIVALENCE",
    )


def _bulge_pair():
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (2000, 0, 0)])
    add_lwpolyline(doc, [(0, 0, 1.0), (2000, 0, 0)])
    return doc


def _minsert():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    insert = add_insert(doc, "Радиатор 500", (0, 5000), layer=EQUIPMENT_LAYER)
    insert.dxf.row_count = 2
    insert.dxf.column_count = 3
    insert.dxf.row_spacing = 1000
    insert.dxf.column_spacing = 1000
    return doc


def _ocs_marker():
    doc = new_doc(INSUNITS_MM)
    add_arc(doc, (5000, 0), 1000.0, 0.0, 90.0, extrusion=(0, 0, -1))
    add_text(doc, "DN20", (-5000, 500))
    return doc


def _new_label_notations():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "%%c16", (1000, 1000))
    add_line(doc, (0, 50000), (2000, 50000))
    add_text(doc, "Ду15", (1000, 51000))
    return doc


def _metres_far_marker():
    doc = new_doc(INSUNITS_M)
    add_line(doc, (0, 0), (5, 0))
    add_text(doc, "ø20", (2.5, 100))
    return doc


def _mesh():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    ensure_layer(doc, PIPE_LAYER)
    mesh = doc.modelspace().add_polyface(dxfattribs={"layer": PIPE_LAYER})
    mesh.append_face([(0, 5000, 0), (1000, 5000, 0), (1000, 6000, 0)])
    return doc


def _diameters(report):
    return sorted(row["Diameter"] for row in report["pipe_detail_rows"])


INTENDED = {
    "bulge_pair": (
        _bulge_pair,
        0.001,
        "V1-DUP-01 polyline identity includes bulges",
        lambda new, old: (round(old["summary"]["total_pipe_length"], 6), round(new["summary"]["total_pipe_length"], 6), old["summary"]["duplicate_entity_count"], new["summary"]["duplicate_entity_count"]),
        (2.0, round(2.0 + math.pi, 6), 1, 0),
        None,
    ),
    "minsert": (
        _minsert,
        0.001,
        "V1-BLK-02 MINSERT instances counted",
        lambda new, old: (old["summary"]["equipment_count"], new["summary"]["equipment_count"]),
        (1, 6),
        ["equipment_rows", "summary.equipment_count"],
    ),
    "ocs_marker": (
        _ocs_marker,
        0.001,
        "V1-DIA-05 OCS converted to WCS for matching",
        lambda new, old: (_diameters(old), _diameters(new), old["summary"]["total_pipe_length"] == new["summary"]["total_pipe_length"]),
        (["UNKNOWN"], ["DN20"], True),
        DIAMETER_CHANGE_PATHS,
    ),
    "new_label_notations": (
        _new_label_notations,
        0.001,
        "V1-DIA-02 %%c and Ду notations read",
        lambda new, old: (_diameters(old), _diameters(new), old["summary"]["total_pipe_length"] == new["summary"]["total_pipe_length"]),
        (["UNKNOWN", "UNKNOWN"], ["DN15", "Ø16"], True),
        DIAMETER_CHANGE_PATHS,
    ),
    "metres_far_marker": (
        _metres_far_marker,
        1.0,
        "V1-DIA-04 marker distance is 3 m in any unit",
        lambda new, old: (_diameters(old), _diameters(new), old["summary"]["total_pipe_length"] == new["summary"]["total_pipe_length"]),
        (["DN20"], ["UNKNOWN"], True),
        DIAMETER_CHANGE_PATHS,
    ),
    "mesh": (
        _mesh,
        0.001,
        "V1-ENT-02 mesh polylines are not measured",
        lambda new, old: (old["summary"]["total_pipe_length"] > 1.0, round(new["summary"]["total_pipe_length"], 6), old["summary"]["pipe_entity_count"], new["summary"]["pipe_entity_count"]),
        (True, 1.0, 2, 1),
        None,
    ),
}
FORBIDDEN_FOR_GEOMETRY_CHANGES = {
    "equipment_rows",
    "fittings_rows",
    "valves_rows",
    "summary.equipment_count",
    "summary.fittings_count",
    "summary.valves_count",
}


@pytest.mark.parametrize("name", sorted(INTENDED))
def test_intended_changes_are_exactly_as_documented(baseline_app, validation, name):
    """Each intended V1 change alters only its documented paths, with the documented before/after values."""
    builder, factor, rule, facts, expected_facts, allowed = INTENDED[name]
    doc = reload(builder())
    new = app.calculate_dxf_quantities(doc, "m", factor)
    old = baseline_app.calculate_dxf_quantities(doc, "m", factor)
    differences = _differences(new, old)
    if allowed is None:
        scope_ok = not (set(differences) & FORBIDDEN_FOR_GEOMETRY_CHANGES)
    else:
        scope_ok = set(differences) <= set(allowed)
    validation.equal(
        f"EQ-INTENDED-{name}",
        rule,
        expected=(expected_facts, True),
        actual=(facts(new, old), scope_ok),
        basis=f"fixture '{name}'; differing paths: {differences}",
        kind="EQUIVALENCE",
    )


def _read(excel_bytes: bytes) -> dict:
    return pd.read_excel(io.BytesIO(excel_bytes), sheet_name=None)


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in ("Диаметр", "Diameter", "Nearest Marker Label"):
        if column in frame.columns:
            frame[column] = [_normalise("Diameter", value) for value in frame[column]]
    frame = frame.astype(str)
    return frame.sort_values(list(frame.columns)).reset_index(drop=True) if len(frame.columns) else frame


def _common_column_differences(new: dict, old: dict) -> tuple[list[str], list[str], list[str]]:
    changed = []
    for name in sorted(set(new) & set(old)):
        columns = [column for column in old[name].columns if column in new[name].columns]
        missing = [column for column in old[name].columns if column not in new[name].columns]
        if missing or not _normalise_frame(new[name][columns]).equals(_normalise_frame(old[name][columns])):
            changed.append(name)
    return changed, sorted(set(new) - set(old)), sorted(set(old) - set(new))


def _main_excel_call(excel_module, report, layer, display_unit):
    """The Excel call exactly as written in main's app.py."""
    return excel_module.build_takeoff_excel(
        file_name="synthetic.dxf",
        summary_rows=[
            {
                "Total Pipe Length (m)": round(report["summary"]["total_pipe_length"], 6),
                "Pipe Entities": report["summary"]["pipe_entity_count"],
                "Equipment Count": report["summary"]["equipment_count"],
                "Fittings Count": report["summary"]["fittings_count"],
                "Valves Count": report["summary"]["valves_count"],
                "Unit": display_unit,
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


V1_EXCEL_SHEETS = ["БЛОКИ С ТРУБАМИ", "НЕ ИЗМЕРЕНО", "НЕ РАСПОЗНАНО", "ПРЕДУПРЕЖДЕНИЯ", "ТРУБНЫЕ СЛОИ"]


def test_app_excel_matches_main_for_known_units(baseline_app, baseline_excel, validation):
    """The app's workbook keeps every column of main's workbook with identical values; V1 only adds columns and sheets."""
    doc = reload(_mixed_mm())
    new_report = app.calculate_dxf_quantities(doc, "m", 0.001)
    new_layer = app.calculate_layer(doc, PIPE_LAYER, "m", 0.001)
    old_report = baseline_app.calculate_dxf_quantities(doc, "m", 0.001)
    old_layer = baseline_app.calculate_layer(doc, PIPE_LAYER, "m", 0.001)
    new_sheets = _read(app.build_dxf_takeoff_excel(file_name="synthetic.dxf", report=new_report, layer_calculation=new_layer, selected_layer=PIPE_LAYER, display_unit="m"))
    old_sheets = _read(_main_excel_call(baseline_excel, old_report, old_layer, "m"))
    validation.equal(
        "EQ-XLS-01",
        "Excel: main's columns unchanged; V1 sheets added",
        expected=([], V1_EXCEL_SHEETS, []),
        actual=_common_column_differences(new_sheets, old_sheets),
        basis="fixture 'mixed_mm', $INSUNITS=4; (sheets with changed common columns, added sheets, removed sheets)",
        kind="EQUIVALENCE",
    )


def test_excel_export_defaults_identical_to_main(baseline_app, baseline_excel, validation):
    """build_takeoff_excel with main's arguments produces main's workbook unchanged."""
    doc = reload(_mixed_mm())
    report = baseline_app.calculate_dxf_quantities(doc, "m", 0.001)
    layer = baseline_app.calculate_layer(doc, PIPE_LAYER, "m", 0.001)
    import excel_export

    validation.equal(
        "EQ-XLS-02",
        "excel_export defaults identical to main",
        expected=([], [], []),
        actual=_common_column_differences(_read(_main_excel_call(excel_export, report, layer, "m")), _read(_main_excel_call(baseline_excel, report, layer, "m"))),
        basis="fixture 'mixed_mm', main's call signature",
        kind="EQUIVALENCE",
    )
