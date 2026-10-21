"""Quantities must be identical to the calculation on ``main``.

``MEP_BASELINE_DIR`` must contain ``app.py`` and ``excel_export.py`` from ``main``
(CI extracts them). The only permitted differences are the Stage 2A additions
(warning fields) and the removal of the placeholder diameter row when no pipe
geometry exists.
"""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path

import pandas as pd
import pytest

import app
from stage2a_fixtures import (
    empty_drawing,
    no_pipe_drawing,
    unknown_units_drawing,
    unsupported_drawing,
    xref_drawing,
)
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
    new_doc,
    reload,
)

BASELINE_DIR = Path(os.environ["MEP_BASELINE_DIR"]).resolve() if os.environ.get("MEP_BASELINE_DIR") else None

pytestmark = pytest.mark.skipif(
    BASELINE_DIR is None,
    reason="NOT RUN: MEP_BASELINE_DIR (app.py and excel_export.py from main) is not set; CI sets it",
)

STAGE_2A_REPORT_KEYS = {"warnings", "unsupported_pipe_entities", "xrefs"}
STAGE_2A_SUMMARY_KEYS = {"length_unit", "unsupported_pipe_entity_count"}
PLACEHOLDER_REMOVAL_DIFF = ["debug.unknown_dn_count", "pipe_by_diameter_rows", "pipe_rows"]
STAGE_2A_EXCEL_SHEETS = {"ПРЕДУПРЕЖДЕНИЯ", "НЕ ИЗМЕРЕНО"}


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, BASELINE_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def baseline_app():
    return _load("baseline_app", "app.py")


@pytest.fixture(scope="module")
def baseline_excel():
    return _load("baseline_excel_export", "excel_export.py")


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


def _metres_with_far_marker():
    doc = new_doc(INSUNITS_M)
    add_line(doc, (0, 0), (5, 0))
    add_text(doc, "ø20", (2.5, 100))
    return doc


def _inches_with_bulge():
    doc = new_doc(INSUNITS_INCH)
    add_lwpolyline(doc, [(0, 0, 0), (100, 0, 0.5), (200, 50, 0)])
    return doc


FIXTURES = {
    "mixed_mm": (_mixed_mm, 0.001),
    "unknown_units": (unknown_units_drawing, None),
    "metres_far_marker": (_metres_with_far_marker, 1.0),
    "inches_bulge": (_inches_with_bulge, 0.0254),
    "unsupported": (lambda: unsupported_drawing()[0], 0.001),
    "xref": (xref_drawing, 0.001),
    "empty": (empty_drawing, 0.001),
    "no_pipe": (no_pipe_drawing, 0.001),
}
EXPECTED_DIFFS = {"empty": PLACEHOLDER_REMOVAL_DIFF, "no_pipe": PLACEHOLDER_REMOVAL_DIFF}


def _differences(new: dict, old: dict) -> list[str]:
    new = {key: value for key, value in new.items() if key not in STAGE_2A_REPORT_KEYS}
    paths = []
    for key in sorted(set(new) | set(old)):
        new_value, old_value = new.get(key), old.get(key)
        if key in {"summary", "debug"} and isinstance(new_value, dict) and isinstance(old_value, dict):
            ignored = STAGE_2A_SUMMARY_KEYS if key == "summary" else set()
            for sub_key in sorted((set(new_value) | set(old_value)) - ignored):
                if new_value.get(sub_key) != old_value.get(sub_key):
                    paths.append(f"{key}.{sub_key}")
        elif new_value != old_value:
            paths.append(key)
    return paths


@pytest.mark.parametrize("remove_duplicates", [True, False], ids=["dedup_on", "dedup_off"])
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_report_identical_to_main(baseline_app, validation, name, remove_duplicates):
    """calculate_dxf_quantities output equals main's, apart from Stage 2A additions."""
    builder, factor = FIXTURES[name]
    doc = reload(builder())
    new = app.calculate_dxf_quantities(doc, "m", factor, remove_duplicates)
    old = baseline_app.calculate_dxf_quantities(doc, "m", factor, remove_duplicates)
    validation.equal(
        f"EQ-{name}-{'dedup' if remove_duplicates else 'nodedup'}",
        "quantities identical to main",
        expected=EXPECTED_DIFFS.get(name, []),
        actual=_differences(new, old),
        basis=f"fixture '{name}', meters_per_unit={factor}, remove_duplicates={remove_duplicates}; differing report paths",
        kind="EQUIVALENCE",
    )


def _read(excel_bytes: bytes) -> dict:
    return pd.read_excel(io.BytesIO(excel_bytes), sheet_name=None)


def _sheet_differences(new: dict, old: dict) -> tuple[list[str], list[str], list[str]]:
    changed = sorted(name for name in set(new) & set(old) if not new[name].equals(old[name]))
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


def test_app_excel_identical_to_main_for_known_units(baseline_app, baseline_excel, validation):
    """The app's Excel workbook equals main's, plus the two new warning sheets."""
    doc = reload(_mixed_mm())
    new_report = app.calculate_dxf_quantities(doc, "m", 0.001)
    new_layer = app.calculate_layer(doc, PIPE_LAYER, "m", 0.001)
    old_report = baseline_app.calculate_dxf_quantities(doc, "m", 0.001)
    old_layer = baseline_app.calculate_layer(doc, PIPE_LAYER, "m", 0.001)
    new_sheets = _read(
        app.build_dxf_takeoff_excel(
            file_name="synthetic.dxf", report=new_report, layer_calculation=new_layer, selected_layer=PIPE_LAYER, display_unit="m"
        )
    )
    old_sheets = _read(_main_excel_call(baseline_excel, old_report, old_layer, "m"))
    validation.equal(
        "EQ-XLS-01",
        "Excel identical to main for known units (only warning sheets added)",
        expected=([], sorted(STAGE_2A_EXCEL_SHEETS), []),
        actual=_sheet_differences(new_sheets, old_sheets),
        basis="fixture 'mixed_mm', $INSUNITS=4; (changed sheets, added sheets, removed sheets)",
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
        actual=_sheet_differences(_read(_main_excel_call(excel_export, report, layer, "m")), _read(_main_excel_call(baseline_excel, report, layer, "m"))),
        basis="fixture 'mixed_mm', main's call signature",
        kind="EQUIVALENCE",
    )
