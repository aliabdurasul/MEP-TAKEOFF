"""V1 behaviour contract for the former known-issue groups (KI-3D, KI-DUP, KI-DIA, KI-BLK, KI-LAYER, KI-POL).

Each test locks one rule of docs/V1_BEHAVIOR_CONTRACT.md. Where an engineering
decision is still open (ENG-xx in docs/V1_KNOWN_LIMITATIONS.md) the contract keeps
the V0 quantity and requires an explicit warning instead of a silent result.
Expected values are hand-derived from the synthetic drawings.
"""

from __future__ import annotations

import math

import app
from geometry import measure_entity_3d
from synthetic_dxf import (
    EQUIPMENT_LAYER,
    EQUIPMENT_TAG_LAYER,
    FITTING_LAYER,
    INSUNITS_M,
    INSUNITS_MM,
    MM_TO_M,
    PIPE_LAYER,
    RISER_LAYER,
    VALVE_LAYER,
    add_arc,
    add_insert,
    add_line,
    add_lwpolyline,
    add_polyline3d,
    add_text,
    define_block,
    ensure_layer,
    entity_by_handle,
    new_doc,
    reload,
)


def _takeoff(doc, factor=MM_TO_M):
    return app.calculate_dxf_quantities(reload(doc), "m", factor)


def _row(report, handle):
    rows = [row for row in report["pipe_detail_rows"] if row["Handle"] == handle]
    return rows[0] if len(rows) == 1 else None


def _warning(report, code):
    matches = [warning for warning in report.get("warnings") or [] if warning.get("Code") == code]
    return matches[0] if matches else None


def _warning_facts(report, code):
    warning = _warning(report, code)
    if warning is None:
        return None
    length = warning.get("Length")
    return (warning.get("Count"), None if length is None else round(float(length), 6))


def _total(report):
    return round(report["summary"]["total_pipe_length"], 9)


# --- KI-3D: plan length is the reported quantity; 3D length is shown and differences are warned ----


def test_vertical_line_plan_and_3d_length(validation):
    """KI-3D-01: a vertical LINE adds 0 m plan length, 3 m 3D length, and a Z-variation warning."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    vertical = add_line(doc, (5000, 0, 0), (5000, 0, 3000))
    report = _takeoff(doc)
    row = _row(report, vertical.dxf.handle) or {}
    validation.equal(
        "KI-3D-01",
        "V1-3D-01 plan length reported, 3D length shown, Z variation warned (ENG-01)",
        expected=(1.0, 4.0, "plan (XY projection)", (1, 3.0), "Z_VARIATION", "REVIEW"),
        actual=(
            _total(report),
            round(report["summary"].get("total_pipe_length_3d", float("nan")), 9),
            report["summary"].get("length_basis"),
            _warning_facts(report, "Z_VARIATION_PLAN_LENGTH_REPORTED"),
            row.get("Geometry Flags"),
            row.get("Geometry Status"),
        ),
        basis="LINE 1000 mm flat + LINE (0,0,0)-(0,0,3000) mm on П_Трубы",
        kind="CONTRACT",
    )


def test_inclined_line_plan_and_3d_length(validation):
    """KI-3D-02: an inclined LINE reports 3 m plan length and 5 m 3D length."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0, 0), (3000, 0, 4000))
    report = _takeoff(doc)
    validation.equal(
        "KI-3D-02",
        "V1-3D-01 inclined LINE",
        expected=(3.0, 5.0, (1, 2.0)),
        actual=(_total(report), round(report["summary"].get("total_pipe_length_3d", float("nan")), 9), _warning_facts(report, "Z_VARIATION_PLAN_LENGTH_REPORTED")),
        basis="LINE (0,0,0)-(3000,0,4000) mm",
        kind="CONTRACT",
    )


def test_polyline3d_plan_and_3d_length(validation):
    """KI-3D-03: a 3D POLYLINE reports plan length and its true 3D length."""
    doc = new_doc(INSUNITS_MM)
    polyline = add_polyline3d(doc, [(0, 0, 0), (0, 0, 3000), (1000, 0, 3000)])
    reloaded = reload(doc)
    report = app.calculate_dxf_quantities(reloaded, "m", MM_TO_M)
    validation.equal(
        "KI-3D-03",
        "V1-3D-01 3D POLYLINE",
        expected=(1.0, 4.0, 4000.0),
        actual=(_total(report), round(report["summary"].get("total_pipe_length_3d", float("nan")), 9), measure_entity_3d(entity_by_handle(reloaded, polyline.dxf.handle))),
        basis="POLYLINE 3D: 3000 vertical + 1000 horizontal mm",
        kind="CONTRACT",
    )


def test_flat_drawing_has_equal_plan_and_3d_length(validation):
    """KI-3D-04: a flat drawing has identical plan and 3D totals and no Z warning."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_arc(doc, (20000, 0), 1000.0, 0.0, 90.0)
    report = _takeoff(doc)
    validation.equal(
        "KI-3D-04",
        "V1-3D-01 flat geometry unchanged",
        expected=(round(5.0 + math.pi / 2.0, 9), round(5.0 + math.pi / 2.0, 9), None),
        actual=(_total(report), round(report["summary"].get("total_pipe_length_3d", float("nan")), 9), _warning(report, "Z_VARIATION_PLAN_LENGTH_REPORTED")),
        basis="LINE 5000 mm + ARC r=1000 90 deg, all Z=0",
        kind="CONTRACT",
    )


# --- KI-DUP: identity includes bulges; overlaps are counted and warned, never silently removed ----


def test_polylines_differing_only_in_bulge_are_both_counted(validation):
    """KI-DUP-01: equal vertices with different bulges are different pipes (fixed)."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (2000, 0, 0)])
    add_lwpolyline(doc, [(0, 0, 1.0), (2000, 0, 0)])
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-01",
        "V1-DUP-01 polyline identity includes bulges",
        expected=(round((2000.0 + 1000.0 * math.pi) * MM_TO_M, 9), 0),
        actual=(_total(report), report["summary"]["duplicate_entity_count"]),
        basis="straight 2000 mm + semicircle (bulge=1) on the same vertices",
        kind="CONTRACT",
    )


def test_reversed_bulged_polyline_is_still_a_duplicate(validation):
    """KI-DUP-01b: the same arc drawn in reverse (bulge sign flipped) is one pipe."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 1.0), (2000, 0, 0)])
    add_lwpolyline(doc, [(2000, 0, -1.0), (0, 0, 0)])
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-01b",
        "V1-DUP-01 reversed duplicate with bulge removed",
        expected=(round(1000.0 * math.pi * MM_TO_M, 9), 1),
        actual=(_total(report), report["summary"]["duplicate_entity_count"]),
        basis="semicircle (0,0)->(2000,0) bulge 1 and its reverse bulge -1",
        kind="CONTRACT",
    )


def test_reversed_closed_bulged_polyline_is_a_duplicate(validation):
    """KI-DUP-01c: a closed circle-polyline and its reversed copy are one pipe."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 1.0), (2000, 0, 1.0)], closed=True)
    add_lwpolyline(doc, [(2000, 0, -1.0), (0, 0, -1.0)], closed=True)
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-01c",
        "V1-DUP-01 closed reversed duplicate removed",
        expected=(round(2000.0 * math.pi * MM_TO_M, 9), 1),
        actual=(_total(report), report["summary"]["duplicate_entity_count"]),
        basis="closed 2-vertex polyline (full circle r=1000) and its reverse",
        kind="CONTRACT",
    )


def test_partial_overlap_counted_and_warned(validation):
    """KI-DUP-02: partial collinear overlap stays counted and is warned with its length (ENG-03)."""
    doc = new_doc(INSUNITS_MM)
    first = add_line(doc, (0, 0), (4000, 0))
    second = add_line(doc, (2000, 0), (6000, 0))
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-02",
        "V1-DUP-02 overlap counted, warned, rows flagged",
        expected=(8.0, (2, 2.0), "OVERLAP_SAME_LAYER", "OVERLAP_SAME_LAYER"),
        actual=(
            _total(report),
            _warning_facts(report, "OVERLAP_SAME_LAYER_COUNTED"),
            (_row(report, first.dxf.handle) or {}).get("Geometry Flags"),
            (_row(report, second.dxf.handle) or {}).get("Geometry Flags"),
        ),
        basis="LINE 0-4000 and 2000-6000 mm on П_Трубы (2000 mm shared)",
        kind="CONTRACT",
    )


def test_cross_layer_duplicate_counted_and_warned(validation):
    """KI-DUP-03: identical geometry on two pipe layers stays counted and is warned (ENG-04)."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000), layer=PIPE_LAYER)
    add_line(doc, (0, 0), (3000, 4000), layer=RISER_LAYER)
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-03",
        "V1-DUP-03 cross-layer overlap counted and warned",
        expected=(10.0, (2, 5.0)),
        actual=(_total(report), _warning_facts(report, "OVERLAP_ACROSS_LAYERS_COUNTED")),
        basis="identical 5000 mm LINE on П_Трубы and П_Трубы_ Опуск",
        kind="CONTRACT",
    )


def test_line_and_identical_polyline_counted_and_warned(validation):
    """KI-DUP-04: LINE and identical LWPOLYLINE stay counted and are warned as overlap (ENG-03)."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_lwpolyline(doc, [(0, 0, 0), (3000, 4000, 0)])
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-04",
        "V1-DUP-02 cross-type identical geometry warned",
        expected=(10.0, (2, 5.0)),
        actual=(_total(report), _warning_facts(report, "OVERLAP_SAME_LAYER_COUNTED")),
        basis="LINE + LWPOLYLINE (0,0)-(3000,4000) mm on П_Трубы",
        kind="CONTRACT",
    )


def test_identical_arcs_across_layers_warned(validation):
    """KI-DUP-05: identical ARCs on two pipe layers are warned as cross-layer overlap."""
    doc = new_doc(INSUNITS_MM)
    add_arc(doc, (0, 0), 1000.0, 0.0, 90.0, layer=PIPE_LAYER)
    add_arc(doc, (0, 0), 1000.0, 0.0, 90.0, layer=RISER_LAYER)
    report = _takeoff(doc)
    validation.equal(
        "KI-DUP-05",
        "V1-DUP-03 identical arcs across layers",
        expected=(round(math.pi, 9), (2, round(math.pi / 2.0, 6))),
        actual=(_total(report), _warning_facts(report, "OVERLAP_ACROSS_LAYERS_COUNTED")),
        basis="ARC r=1000 0-90 deg on П_Трубы and П_Трубы_ Опуск",
        kind="CONTRACT",
    )


# --- KI-DIA: Ø and DN are distinct; thresholds are physical; unresolved candidates are shown ----


def test_marker_threshold_in_metre_drawing(validation):
    """KI-DIA-01: the 3 m marker distance is physical, so a marker 100 m away does not label a pipe."""
    doc = new_doc(INSUNITS_M)
    far = add_line(doc, (0, 0), (5, 0))
    add_text(doc, "ø20", (2.5, 100), height=0.25)
    near = add_line(doc, (0, 1000), (5, 1000))
    add_text(doc, "ø25", (2.5, 1002), height=0.25)
    report = _takeoff(doc, factor=1.0)
    validation.equal(
        "KI-DIA-01",
        "V1-DIA-04 marker distance 3 m converted to drawing units (ENG-07)",
        expected=("UNKNOWN", "Ø25", 3.0),
        actual=(
            (_row(report, far.dxf.handle) or {}).get("Diameter"),
            (_row(report, near.dxf.handle) or {}).get("Diameter"),
            (_row(report, near.dxf.handle) or {}).get("Marker Threshold"),
        ),
        basis="$INSUNITS=6; marker 100 m from one pipe, 2 m from another, text height 0.25 m",
        kind="CONTRACT",
    )


def test_autocad_diameter_code_recognised(validation):
    """KI-DIA-02: '%%c16' is AutoCAD's 'Ø16' (outside diameter)."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "%%c16", (1000, 1000))
    row = _row(_takeoff(doc), line.dxf.handle) or {}
    validation.equal(
        "KI-DIA-02",
        "V1-DIA-02 %%c decoded as Ø",
        expected=("Ø16", "OUTSIDE_DIAMETER"),
        actual=(row.get("Diameter"), row.get("Diameter Type")),
        basis="TEXT '%%c16' 1000 mm from pipe midpoint",
        kind="CONTRACT",
    )


def test_russian_nominal_bore_recognised(validation):
    """KI-DIA-03: 'Ду15' (условный проход) is nominal size DN15 (ENG-08)."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "Ду15", (1000, 1000))
    row = _row(_takeoff(doc), line.dxf.handle) or {}
    validation.equal(
        "KI-DIA-03",
        "V1-DIA-02 Ду read as DN",
        expected=("DN15", "NOMINAL_DN"),
        actual=(row.get("Diameter"), row.get("Diameter Type")),
        basis="TEXT 'Ду15' 1000 mm from pipe midpoint",
        kind="CONTRACT",
    )


def test_mirrored_arc_uses_world_coordinates(validation):
    """KI-DIA-04: an ARC with extrusion (0,0,-1) is matched at its world position."""
    doc = new_doc(INSUNITS_MM)
    arc = add_arc(doc, (5000, 0), 1000.0, 0.0, 90.0, extrusion=(0, 0, -1))
    add_text(doc, "DN20", (-5000, 500))
    row = _row(_takeoff(doc), arc.dxf.handle) or {}
    validation.equal(
        "KI-DIA-04",
        "V1-DIA-05 OCS converted to WCS for matching",
        expected=("DN20", "NOMINAL_DN"),
        actual=(row.get("Diameter"), row.get("Diameter Type")),
        basis="ARC OCS centre (5000,0), extrusion (0,0,-1) => WCS (-5000,0); 'DN20' 500 mm away",
        kind="CONTRACT",
    )


def test_marker_on_large_arc_is_an_unresolved_candidate(validation):
    """KI-DIA-05: a marker on the arc but far from its centre is shown as a candidate, not assigned (ENG-06)."""
    doc = new_doc(INSUNITS_MM)
    arc = add_arc(doc, (0, 0), 4000.0, 0.0, 90.0)
    on_arc = (4000.0 * math.cos(math.radians(45.0)), 4000.0 * math.sin(math.radians(45.0)))
    add_text(doc, "ø16", on_arc)
    report = _takeoff(doc)
    row = _row(report, arc.dxf.handle) or {}
    validation.equal(
        "KI-DIA-05",
        "V1-DIA-06 candidate shown, diameter stays UNKNOWN",
        expected=("UNKNOWN", "Ø16", (1, round(4000.0 * math.pi / 2.0 * MM_TO_M, 6))),
        actual=(row.get("Diameter"), row.get("Diameter Candidates"), _warning_facts(report, "DIAMETER_CANDIDATES_UNRESOLVED")),
        basis="ARC r=4000 0-90 deg; 'ø16' at the arc midpoint (4000 mm from centre)",
        kind="CONTRACT",
    )


def test_marker_next_to_long_line_is_an_unresolved_candidate(validation):
    """KI-DIA-06: a marker beside a long pipe but far from its midpoint is a candidate."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (20000, 0))
    add_text(doc, "ø16", (500, 300))
    row = _row(_takeoff(doc), line.dxf.handle) or {}
    validation.equal(
        "KI-DIA-06",
        "V1-DIA-06 long pipe candidate",
        expected=("UNKNOWN", "Ø16"),
        actual=(row.get("Diameter"), row.get("Diameter Candidates")),
        basis="LINE 20000 mm; 'ø16' 300 mm beside it, ~9500 mm from midpoint",
        kind="CONTRACT",
    )


def test_ambiguous_candidates_listed(validation):
    """KI-DIA-06b: two different labels near one pipe are both listed; nothing is assigned."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (20000, 0))
    add_text(doc, "ø16", (500, 300))
    add_text(doc, "DN20", (19500, -300))
    row = _row(_takeoff(doc), line.dxf.handle) or {}
    validation.equal(
        "KI-DIA-06b",
        "V1-DIA-06 ambiguous candidates",
        expected=("UNKNOWN", "DN20, Ø16"),
        actual=(row.get("Diameter"), row.get("Diameter Candidates")),
        basis="LINE 20000 mm; 'ø16' near one end, 'DN20' near the other",
        kind="CONTRACT",
    )


def test_outside_diameter_and_nominal_size_distinguished(validation):
    """KI-DIA-07: 'ø' gives Ø (outside diameter), 'DN' gives DN; a drawing using both is warned (ENG-05)."""
    doc = new_doc(INSUNITS_MM)
    od_pipe = add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "ø16", (1000, 1000))
    dn_pipe = add_line(doc, (0, 50000), (2000, 50000))
    add_text(doc, "DN15", (1000, 51000))
    report = _takeoff(doc)
    validation.equal(
        "KI-DIA-07",
        "V1-DIA-01 Ø and DN kept distinct, no conversion",
        expected=(("Ø16", "OUTSIDE_DIAMETER"), ("DN15", "NOMINAL_DN"), True, ["DN15", "Ø16"]),
        actual=(
            ((_row(report, od_pipe.dxf.handle) or {}).get("Diameter"), (_row(report, od_pipe.dxf.handle) or {}).get("Diameter Type")),
            ((_row(report, dn_pipe.dxf.handle) or {}).get("Diameter"), (_row(report, dn_pipe.dxf.handle) or {}).get("Diameter Type")),
            _warning(report, "MIXED_DIAMETER_NOTATION") is not None,
            sorted(row["Diameter"] for row in report["pipe_rows"]),
        ),
        basis="'ø16' and 'DN15' markers on two pipes",
        kind="CONTRACT",
    )


# --- KI-BLK: blocks inspected safely; counts complete; unknown symbols visible -------------------


def test_pipe_inside_block_is_reported_not_measured(validation):
    """KI-BLK-01: pipe geometry inside blocks is reported with its length but not added (ENG-09)."""
    doc = new_doc(INSUNITS_MM)
    ensure_layer(doc, PIPE_LAYER)
    define_block(doc, "PIPE_RUN", lines=[((0, 0), (3000, 4000))], line_layer=PIPE_LAYER)
    add_insert(doc, "PIPE_RUN", (10000, 0), layer=PIPE_LAYER)
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-01",
        "V1-BLK-01 block pipe geometry reported, not measured",
        expected=(0.0, (1, 5.0), [("PIPE_RUN", 1, 1, 5.0)]),
        actual=(
            _total(report),
            _warning_facts(report, "PIPE_GEOMETRY_IN_BLOCKS_NOT_MEASURED"),
            [(row["Block"], row["Inserts"], row["Pipe Entities"], round(row["Length (m)"], 6)) for row in report.get("pipe_geometry_in_blocks") or []],
        ),
        basis="block with LINE 5000 mm on П_Трубы, inserted once",
        kind="CONTRACT",
    )


def test_nested_block_pipe_geometry_counted_once(validation):
    """KI-BLK-01b: nested block geometry is reported once per placed instance."""
    doc = new_doc(INSUNITS_MM)
    ensure_layer(doc, PIPE_LAYER)
    define_block(doc, "INNER", lines=[((0, 0), (1000, 0))], line_layer=PIPE_LAYER)
    outer = doc.blocks.new(name="OUTER")
    outer.add_line((0, 0), (2000, 0), dxfattribs={"layer": PIPE_LAYER})
    outer.add_blockref("INNER", (0, 500))
    add_insert(doc, "OUTER", (10000, 0), layer="0")
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-01b",
        "V1-BLK-01 nested blocks without double counting",
        expected=[("OUTER", 1, 2, 3.0)],
        actual=[(row["Block"], row["Inserts"], row["Pipe Entities"], round(row["Length (m)"], 6)) for row in report.get("pipe_geometry_in_blocks") or []],
        basis="OUTER (LINE 2000 mm + INNER with LINE 1000 mm), only OUTER inserted",
        kind="CONTRACT",
    )


def test_minsert_counts_every_instance(validation):
    """KI-BLK-02: an INSERT array of 2 rows x 3 columns places 6 items (fixed)."""
    doc = new_doc(INSUNITS_MM)
    insert = add_insert(doc, "Радиатор 500", (0, 0), layer=EQUIPMENT_LAYER)
    insert.dxf.row_count = 2
    insert.dxf.column_count = 3
    insert.dxf.row_spacing = 1000
    insert.dxf.column_spacing = 1000
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-02",
        "V1-BLK-02 MINSERT instances counted",
        expected=(6, [{"Type": "Radiator", "Quantity": 6}]),
        actual=(report["summary"]["equipment_count"], report["equipment_rows"]),
        basis="INSERT 'Радиатор 500' with 2 rows x 3 columns",
        kind="CONTRACT",
    )


def test_equipment_tag_layer_counted_and_warned(validation):
    """KI-BLK-03: blocks on the equipment tag layer stay counted and are warned (ENG-10)."""
    doc = new_doc(INSUNITS_MM)
    add_insert(doc, "Радиатор 500", (0, 0), layer=EQUIPMENT_LAYER)
    add_insert(doc, "Марка", (0, 500), layer=EQUIPMENT_TAG_LAYER)
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-03",
        "V1-BLK-03 tag layer counted with warning",
        expected=(2, (1, None)),
        actual=(report["summary"]["equipment_count"], _warning_facts(report, "EQUIPMENT_TAG_LAYER_COUNTED")),
        basis="radiator INSERT + tag INSERT on 'Марки оборудования'",
        kind="CONTRACT",
    )


def test_unrecognised_valve_layer_block_listed(validation):
    """KI-BLK-04: an unrecognised block on the valve layer is listed and warned, not counted as a valve (ENG-11)."""
    doc = new_doc(INSUNITS_MM)
    add_insert(doc, "Фильтр сетчатый", (0, 0), layer=VALVE_LAYER)
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-04",
        "V1-BLK-04 unrecognised MEP symbol visible",
        expected=(0, [(VALVE_LAYER, "Фильтр сетчатый", 1, True)], (1, None)),
        actual=(
            report["summary"]["valves_count"],
            [(row["Layer"], row["Block"], row["Count"], row["MEP Layer"]) for row in report.get("unrecognized_inserts") or []],
            _warning_facts(report, "UNRECOGNIZED_SYMBOLS_ON_MEP_LAYERS"),
        ),
        basis="INSERT 'Фильтр сетчатый' on 'Арматура трубопроводов'",
        kind="CONTRACT",
    )


def test_anonymous_block_classified_by_layer_is_warned(validation):
    """KI-BLK-05: an anonymous (dynamic) block is counted by its layer and warned."""
    doc = new_doc(INSUNITS_MM)
    anonymous = doc.blocks.new_anonymous_block()
    ensure_layer(doc, FITTING_LAYER)
    doc.modelspace().add_blockref(anonymous.name, (0, 0), dxfattribs={"layer": FITTING_LAYER})
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-05",
        "V1-BLK-05 anonymous block warned",
        expected=([{"Type": "Fitting", "Quantity": 1}], (1, None)),
        actual=(report["fittings_rows"], _warning_facts(report, "ANONYMOUS_BLOCKS_CLASSIFIED_BY_LAYER")),
        basis="anonymous block inserted on the fitting layer",
        kind="CONTRACT",
    )


def test_unrecognised_block_on_other_layer_listed_without_warning(validation):
    """KI-BLK-06: an unrecognised block on a non-MEP layer is listed but not warned."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    add_insert(doc, "Штамп", (0, 5000), layer="0")
    report = _takeoff(doc)
    validation.equal(
        "KI-BLK-06",
        "V1-BLK-04 non-MEP unrecognised block listed",
        expected=([("0", "Штамп", 1, False)], None),
        actual=(
            [(row["Layer"], row["Block"], row["Count"], row["MEP Layer"]) for row in report.get("unrecognized_inserts") or []],
            _warning(report, "UNRECOGNIZED_SYMBOLS_ON_MEP_LAYERS"),
        ),
        basis="title-block INSERT 'Штамп' on layer 0",
        kind="CONTRACT",
    )


# --- KI-LAYER: inclusion rule unchanged; suspicious layers warned ---------------------------------


def test_centerline_name_variant_counted_and_warned(validation):
    """KI-LAYER-01: a centreline-like layer that passes the filter stays counted and is warned (ENG-12)."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0), layer="П_Трубы_Осевая линия")
    report = _takeoff(doc)
    validation.equal(
        "KI-LAYER-01",
        "V1-LAYER-02 centreline-like included layer warned",
        expected=(1.0, (1, 1.0)),
        actual=(_total(report), _warning_facts(report, "PIPE_LAYER_NAME_REVIEW")),
        basis="LINE 1000 mm on 'П_Трубы_Осевая линия'",
        kind="CONTRACT",
    )


def test_case_variant_pipe_layer_excluded_and_warned(validation):
    """KI-LAYER-02: a lowercase pipe-layer variant stays excluded and is warned with its length."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    add_line(doc, (0, 1000), (3000, 1000), layer="п_трубы")
    report = _takeoff(doc)
    validation.equal(
        "KI-LAYER-02",
        "V1-LAYER-02 case variant excluded and warned",
        expected=(1.0, (1, 3.0)),
        actual=(_total(report), _warning_facts(report, "PIPE_LAYER_NAME_REVIEW")),
        basis="LINE 1000 mm on П_Трубы + LINE 3000 mm on 'п_трубы'",
        kind="CONTRACT",
    )


def test_frozen_pipe_layer_counted_and_warned(validation):
    """KI-LAYER-03: a frozen pipe layer stays counted and is warned (ENG-14)."""
    doc = new_doc(INSUNITS_MM)
    doc.layers.add("П_Трубы_Frozen").freeze()
    add_line(doc, (0, 0), (500, 0), layer="П_Трубы_Frozen")
    report = _takeoff(doc)
    validation.equal(
        "KI-LAYER-03",
        "V1-LAYER-03 hidden pipe layer warned",
        expected=(0.5, (1, 0.5)),
        actual=(_total(report), _warning_facts(report, "HIDDEN_PIPE_LAYER_COUNTED")),
        basis="LINE 500 mm on frozen layer 'П_Трубы_Frozen'",
        kind="CONTRACT",
    )


# --- KI-POL: closed polylines, full-circle arcs, meshes -------------------------------------------


def test_closed_polyline_counted_flagged_and_warned(validation):
    """KI-POL-01: a closed polyline stays counted, is flagged for review and warned (ENG-13)."""
    doc = new_doc(INSUNITS_MM)
    closed = add_lwpolyline(doc, [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)], closed=True)
    report = _takeoff(doc)
    row = _row(report, closed.dxf.handle) or {}
    notes = " ".join(report["debug"]["notes"])
    validation.equal(
        "KI-POL-01",
        "V1-POL-01 closed polyline review",
        expected=(4.0, (1, 4.0), "CLOSED_POLYLINE", "REVIEW", 4.0, False),
        actual=(
            _total(report),
            _warning_facts(report, "CLOSED_POLYLINES_COUNTED"),
            row.get("Geometry Flags"),
            row.get("Geometry Status"),
            round(report["summary"].get("ambiguous_pipe_length", float("nan")), 9),
            "remain excluded" in notes,
        ),
        basis="closed 1000x1000 LWPOLYLINE on П_Трубы",
        kind="CONTRACT",
    )


def test_full_circle_arc_counted_and_warned(validation):
    """KI-POL-02: an ARC with equal start and end angle is counted as a full circle and warned (ENG-13)."""
    doc = new_doc(INSUNITS_MM)
    add_arc(doc, (0, 0), 2.0, 90.0, 90.0, layer=RISER_LAYER)
    report = _takeoff(doc)
    validation.equal(
        "KI-POL-02",
        "V1-POL-02 full-circle arc review",
        expected=(round(4.0 * math.pi * MM_TO_M, 9), (1, round(4.0 * math.pi * MM_TO_M, 6))),
        actual=(_total(report), _warning_facts(report, "FULL_CIRCLE_ARCS_COUNTED")),
        basis="ARC r=2 mm, start=end=90 deg on П_Трубы_ Опуск",
        kind="CONTRACT",
    )


def test_mesh_polyline_not_measured(validation):
    """KI-POL-03: a polyface mesh on a pipe layer is unsupported, not measured pipe."""
    doc = new_doc(INSUNITS_MM)
    ensure_layer(doc, PIPE_LAYER)
    mesh = doc.modelspace().add_polyface(dxfattribs={"layer": PIPE_LAYER})
    mesh.append_face([(0, 0, 0), (1000, 0, 0), (1000, 1000, 0)])
    report = _takeoff(doc)
    validation.equal(
        "KI-POL-03",
        "V1-ENT-02 mesh polylines are unsupported",
        expected=(0.0, [(PIPE_LAYER, "POLYLINE", 1)], ["NO_PIPE_GEOMETRY", "UNSUPPORTED_PIPE_ENTITIES"]),
        actual=(
            _total(report),
            [(row["Layer"], row["Entity Type"], row["Count"]) for row in report["unsupported_pipe_entities"]],
            sorted(warning["Code"] for warning in report["warnings"]),
        ),
        basis="POLYFACE (one triangle) on П_Трубы",
        kind="CONTRACT",
    )


def test_unknown_diameter_length_summarised(validation):
    """V1-OUT-02: the summary carries the UNKNOWN-diameter length."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "ø16", (1000, 1000))
    add_line(doc, (0, 50000), (3000, 50000))
    report = _takeoff(doc)
    validation.equal(
        "V1-OUT-02",
        "unknown-diameter length in summary",
        expected=3.0,
        actual=round(report["summary"].get("unknown_diameter_length", float("nan")), 9),
        basis="2000 mm pipe with ø16 + 3000 mm pipe without marker",
        kind="CONTRACT",
    )
