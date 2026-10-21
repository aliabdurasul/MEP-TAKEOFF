"""The read-only impact analysis measures each known-issue group correctly.

Expected values are hand-derived from the synthetic drawings; the analysis must not
change any takeoff result or write any file unless asked to.
"""

from __future__ import annotations

import hashlib
import math

import app
from synthetic_dxf import (
    CENTERLINE_LAYER,
    EQUIPMENT_LAYER,
    EQUIPMENT_TAG_LAYER,
    FITTING_LAYER,
    INSUNITS_M,
    INSUNITS_MM,
    PIPE_LAYER,
    RISER_LAYER,
    VALVE_LAYER,
    add_arc,
    add_insert,
    add_line,
    add_lwpolyline,
    add_polyline2d,
    add_polyline3d,
    add_text,
    define_block,
    new_doc,
    reload,
    to_bytes,
)
from tools.impact_analysis import analyse, main


def _amount(count, length_du, factor=0.001):
    return {"count": count, "length_du": round(length_du, 6), "length_m": round(length_du * factor, 6)}


def _analyse(doc):
    return analyse(reload(doc))


# --- KI-3D --------------------------------------------------------------------------------------


def test_missing_vertical_length_of_lines(validation):
    """Missing length = 3D length - plan length, for LINEs with a Z difference."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0, 0), (0, 0, 3000))
    add_line(doc, (10000, 0, 0), (13000, 0, 4000))
    add_line(doc, (20000, 0), (21000, 0))
    validation.equal(
        "IMP-3D-01",
        "LINE vertical/inclined missing length",
        expected=_amount(2, 3000.0 + (5000.0 - 3000.0)),
        actual=_analyse(doc)["KI-3D"]["lines_with_z_difference_missing_length"],
        basis="vertical 3000 mm (missing 3000) + inclined 3000x4000 (missing 2000) + flat 1000",
        kind="IMPACT",
    )


def test_missing_vertical_length_of_3d_polylines(validation):
    """Missing length of a 3D POLYLINE with a vertical leg."""
    doc = new_doc(INSUNITS_MM)
    add_polyline3d(doc, [(0, 0, 0), (0, 0, 3000), (1000, 0, 3000)])
    validation.equal(
        "IMP-3D-02",
        "3D POLYLINE missing length",
        expected=_amount(1, 3000.0),
        actual=_analyse(doc)["KI-3D"]["3d_polylines_missing_length"],
        basis="POLYLINE 3D: 3000 vertical + 1000 horizontal mm; plan length 1000",
        kind="IMPACT",
    )


def test_full_circle_arcs_counted(validation):
    """ARCs with equal start and end angle are counted as full-circle pipe length."""
    doc = new_doc(INSUNITS_MM)
    add_arc(doc, (0, 0), 2.0, 90.0, 90.0, layer=RISER_LAYER)
    validation.equal(
        "IMP-3D-03",
        "full-circle ARC (riser symbol) counted as pipe",
        expected=_amount(1, 4.0 * math.pi),
        actual=_analyse(doc)["KI-3D"]["full_circle_arcs_counted_as_pipe"],
        basis="ARC r=2 mm, start=end=90 deg on П_Трубы_ Опуск: 2*pi*r",
        kind="IMPACT",
    )


# --- KI-DUP -------------------------------------------------------------------------------------


def test_bulge_blind_duplicate_removal_measured(validation):
    """After V1-DUP-01 no polyline whose arcs differ from a kept copy is removed (lost length 0)."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (2000, 0, 0)])
    add_lwpolyline(doc, [(0, 0, 1.0), (2000, 0, 0)])
    add_lwpolyline(doc, [(0, 5000, 1.0), (2000, 5000, 0)], layer=RISER_LAYER)
    add_lwpolyline(doc, [(2000, 5000, -1.0), (0, 5000, 0)], layer=RISER_LAYER)
    validation.equal(
        "IMP-DUP-01",
        "lost length from bulge-blind duplicate removal",
        expected=_amount(0, 0.0),
        actual=_analyse(doc)["KI-DUP"]["removed_polylines_with_different_bulges"],
        basis="П_Трубы: straight + semicircle on same vertices (both kept in V1); Опуск: semicircle + exact reverse (removed, same bulges)",
        kind="IMPACT",
    )


def _overlap_drawing():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (4000, 0))
    add_line(doc, (2000, 0), (6000, 0))
    add_line(doc, (0, 10000), (5000, 10000))
    add_lwpolyline(doc, [(0, 10000, 0), (5000, 10000, 0)])
    add_line(doc, (0, 20000), (3000, 20000))
    add_line(doc, (0, 20000), (3000, 20000), layer=RISER_LAYER)
    return doc


def test_collinear_overlaps_measured(validation):
    """Same-layer and cross-layer collinear overlaps and exact cross-layer duplicates."""
    result = _analyse(_overlap_drawing())["KI-DUP"]
    validation.equal(
        "IMP-DUP-02",
        "overlap lengths",
        expected=(_amount(4, 2000.0 + 5000.0), 1, _amount(1, 3000.0), _amount(1, 3000.0)),
        actual=(
            result["collinear_overlap_same_layer"],
            result["same_layer_overlap_groups_mixing_line_and_polyline"],
            result["collinear_overlap_across_layers"],
            result["exact_duplicates_across_layers"],
        ),
        basis="П_Трубы: 0-4000 & 2000-6000 (2000), LINE+LWPOLYLINE 5000 (5000); 3000 LINE on П_Трубы and Опуск (3000)",
        kind="IMPACT",
    )


# --- KI-DIA -------------------------------------------------------------------------------------


def test_marker_text_inventory(validation):
    """Marker texts are classified as Ø/ø, DN, unparsed diameter-like or other."""
    doc = new_doc(INSUNITS_MM)
    for index, text in enumerate(("ø16", "ø16", "DN20", "%%c25", "Ду15", "note")):
        add_text(doc, text, (index * 1000, 0))
    add_text(doc, "ø32", (0, 5000), layer="0")
    result = _analyse(doc)["KI-DIA"]
    validation.equal(
        "IMP-DIA-01",
        "marker inventory",
        expected=({"OD (Ø/ø)": 3, "DN": 2}, {}, 1, {"0": 1}),
        actual=(
            result["marker_symbols"],
            result["unparsed_diameter_like_texts"],
            result["unparsed_other_texts_count"],
            result["diameter_labels_outside_marker_layer"],
        ),
        basis="П_Марки труб: ø16 x2, DN20, %%c25, Ду15, note; layer 0: ø32",
        kind="IMPACT",
    )


def test_unknown_pipes_with_marker_near_geometry(validation):
    """UNKNOWN pipes with a marker within threshold of the geometry (not the midpoint) are counted."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (20000, 0))
    add_text(doc, "ø16", (500, 300))
    add_line(doc, (0, 50000), (20000, 50000))
    add_text(doc, "ø16", (500, 50300))
    add_text(doc, "DN20", (19500, 49700))
    add_line(doc, (0, 100000), (1000, 100000))
    result = _analyse(doc)["KI-DIA"]
    validation.equal(
        "IMP-DIA-02",
        "recoverable UNKNOWN length",
        expected=(_amount(3, 41000.0), _amount(2, 40000.0), 1),
        actual=(result["unknown_diameter"], result["unknown_with_marker_near_geometry"], result["ambiguous_candidates"]),
        basis="2x 20000 mm pipes with markers 300 mm beside them (one with two labels) + 1000 mm pipe without markers",
        kind="IMPACT",
    )


def test_mirrored_ocs_entities_counted(validation):
    """Measured ARCs with extrusion (0,0,-1) are counted."""
    doc = new_doc(INSUNITS_MM)
    add_arc(doc, (5000, 0), 1000.0, 0.0, 90.0, extrusion=(0, 0, -1))
    add_arc(doc, (9000, 0), 1000.0, 0.0, 90.0)
    validation.equal(
        "IMP-DIA-03",
        "mirrored OCS entities",
        expected={"count": 1, "unknown": 1},
        actual=_analyse(doc)["KI-DIA"]["mirrored_or_tilted_ocs_entities"],
        basis="one ARC with extrusion (0,0,-1), one normal ARC, no markers",
        kind="IMPACT",
    )


def test_marker_threshold_in_metres(validation):
    """The fixed 3000-unit marker threshold expressed in metres depends on drawing units."""
    mm_doc = new_doc(INSUNITS_MM)
    add_line(mm_doc, (0, 0), (1000, 0))
    m_doc = new_doc(INSUNITS_M)
    add_line(m_doc, (0, 0), (1, 0))
    validation.equal(
        "IMP-DIA-04",
        "threshold 3000 drawing units in metres",
        expected=(3.0, 3.0),
        actual=(_analyse(mm_doc)["KI-DIA"]["marker_threshold_m"], _analyse(m_doc)["KI-DIA"]["marker_threshold_m"]),
        basis="$INSUNITS=4 and $INSUNITS=6",
        kind="IMPACT",
    )


# --- KI-BLK -------------------------------------------------------------------------------------


def test_pipe_geometry_inside_blocks_measured(validation):
    """Pipe-layer geometry inside inserted blocks, including scaling and layer-0 inheritance."""
    doc = new_doc(INSUNITS_MM)
    define_block(doc, "RUN", lines=[((0, 0), (3000, 4000))], line_layer=PIPE_LAYER)
    add_insert(doc, "RUN", (100000, 0), layer="0")
    scaled = add_insert(doc, "RUN", (200000, 0), layer="0")
    scaled.dxf.xscale = 2
    scaled.dxf.yscale = 2
    scaled.dxf.zscale = 2
    define_block(doc, "B0", lines=[((0, 0), (1000, 0))], line_layer="0")
    add_insert(doc, "B0", (300000, 0), layer=PIPE_LAYER)
    result = _analyse(doc)["KI-BLK"]
    validation.equal(
        "IMP-BLK-01",
        "hidden pipe length in blocks",
        expected=(_amount(3, 5000.0 + 10000.0 + 1000.0), 3),
        actual=(result["pipe_geometry_inside_blocks_not_measured"], result["inserts_containing_pipe_geometry"]),
        basis="RUN (5000 mm LINE on П_Трубы) x1 and x2 scale; B0 (1000 mm LINE on layer 0) inserted on П_Трубы",
        kind="IMPACT",
    )


def test_block_counting_gaps(validation):
    """MINSERT instances, equipment tags, dropped valve-layer blocks and anonymous blocks."""
    doc = new_doc(INSUNITS_MM)
    minsert = add_insert(doc, "Радиатор 500", (0, 0), layer=EQUIPMENT_LAYER)
    minsert.dxf.row_count = 2
    minsert.dxf.column_count = 3
    minsert.dxf.row_spacing = 1000
    minsert.dxf.column_spacing = 1000
    add_insert(doc, "Марка", (0, 5000), layer=EQUIPMENT_TAG_LAYER)
    add_insert(doc, "Фильтр сетчатый", (0, 10000), layer=VALVE_LAYER)
    anonymous = doc.blocks.new_anonymous_block()
    doc.modelspace().add_blockref(anonymous.name, (0, 15000), dxfattribs={"layer": FITTING_LAYER})
    result = _analyse(doc)["KI-BLK"]
    validation.equal(
        "IMP-BLK-02",
        "block counting gaps",
        expected=({"EQUIPMENT/Radiator": 6}, 1, {"Фильтр сетчатый": 1}, {VALVE_LAYER: 1}, 1),
        actual=(
            result["minsert_instances"],
            result["equipment_tag_layer_inserts_counted_as_equipment"],
            result["valve_layer_inserts_dropped"],
            result["inserts_not_counted_by_layer"],
            sum(result["anonymous_block_inserts"].values()),
        ),
        basis="MINSERT 2x3 radiator; tag block; 'Фильтр сетчатый' on valve layer; anonymous block on fitting layer",
        kind="IMPACT",
    )


# --- KI-LAYER / KI-POL --------------------------------------------------------------------------


def test_layer_issues_flagged(validation):
    """Centreline-like, frozen and case-variant pipe layers are flagged with their measured length."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    add_line(doc, (0, 1000), (2000, 1000), layer="П_Трубы_Осевая линия")
    add_line(doc, (0, 2000), (3000, 2000), layer="п_трубы")
    add_line(doc, (0, 3000), (4000, 3000), layer=CENTERLINE_LAYER)
    doc.layers.add("П_Трубы_Frozen").freeze()
    add_line(doc, (0, 4000), (500, 4000), layer="П_Трубы_Frozen")
    flagged = sorted((row["layer"], row["issue"], row["count"], row["length_m"]) for row in _analyse(doc)["KI-LAYER"]["flagged"])
    validation.equal(
        "IMP-LAYER-01",
        "flagged pipe-like layers",
        expected=sorted(
            [
                ("П_Трубы_Frozen", "frozen or off but included", 1, 0.5),
                ("П_Трубы_Осевая линия", "centreline-like name but included", 1, 2.0),
                ("п_трубы", "prefix case variant not included", 1, 3.0),
            ]
        ),
        actual=flagged,
        basis="LINEs on П_Трубы (ok), 'П_Трубы_Осевая линия', 'п_трубы', exact centreline (ok), frozen 'П_Трубы_Frozen'",
        kind="IMPACT",
    )


def test_closed_polylines_counted(validation):
    """Closed polylines counted as pipe length."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)], closed=True)
    add_polyline2d(doc, [(5000, 0), (7000, 0), (7000, 2000), (5000, 2000)], closed=True, layer=RISER_LAYER)
    add_line(doc, (0, 10000), (1000, 10000))
    validation.equal(
        "IMP-POL-01",
        "closed polylines counted",
        expected=_amount(2, 4000.0 + 8000.0),
        actual=_analyse(doc)["KI-POL"]["closed_polylines_counted_as_pipe"],
        basis="closed LWPOLYLINE 1000 square + closed POLYLINE 2000 square + open LINE",
        kind="IMPACT",
    )


# --- read-only guarantees -----------------------------------------------------------------------


def test_analysis_matches_and_does_not_change_takeoff(validation):
    """The analysis selection equals the takeoff's and the takeoff result is identical before and after."""
    doc = reload(_overlap_drawing())
    before = app.calculate_dxf_quantities(doc, "m", 0.001)
    result = analyse(doc)
    after = app.calculate_dxf_quantities(doc, "m", 0.001)
    validation.equal(
        "IMP-BASE-01",
        "selection matches takeoff; takeoff unchanged",
        expected=(True, before["summary"]["total_pipe_length"], before["pipe_detail_rows"]),
        actual=(result["drawing"]["selection_matches_app"], after["summary"]["total_pipe_length"], after["pipe_detail_rows"]),
        basis="overlap drawing, $INSUNITS=4",
        kind="IMPACT",
    )


def test_cli_is_read_only(tmp_path, capsys, validation):
    """The CLI prints the report and leaves the drawing and its folder unchanged."""
    drawing = tmp_path / "drawing.dxf"
    drawing.write_bytes(to_bytes(_overlap_drawing()))
    digest = hashlib.sha256(drawing.read_bytes()).hexdigest()
    exit_code = main([str(drawing)])
    printed = capsys.readouterr().out
    validation.equal(
        "IMP-RO-01",
        "CLI read-only",
        expected=(0, digest, ["drawing.dxf"], True),
        actual=(exit_code, hashlib.sha256(drawing.read_bytes()).hexdigest(), sorted(p.name for p in tmp_path.iterdir()), "## KI-DUP" in printed),
        basis="CLI on a synthetic DXF without --output",
        kind="IMPACT",
    )


def test_cli_never_overwrites_output(tmp_path, validation):
    """--output refuses to overwrite an existing report."""
    drawing = tmp_path / "drawing.dxf"
    drawing.write_bytes(to_bytes(_overlap_drawing()))
    report = tmp_path / "impact.md"
    report.write_text("existing", encoding="utf-8")
    exit_code = main([str(drawing), "--output", str(report)])
    validation.equal(
        "IMP-RO-02",
        "no overwrite",
        expected=(2, "existing", False),
        actual=(exit_code, report.read_text(encoding="utf-8"), report.with_suffix(".json").exists()),
        basis="existing impact.md",
        kind="IMPACT",
    )
