"""Confirmed defects and open engineering rules, as strict xfail tests.

Each test records the mathematically or engineering-expected value and the value the
program produces today. They fail (xfail) until the calculation rule is changed with
engineering approval; a silent behaviour change turns them into XPASS(strict) failures.
"""

from __future__ import annotations

import math

import pytest

import app
from synthetic_dxf import (
    EQUIPMENT_LAYER,
    EQUIPMENT_TAG_LAYER,
    INSUNITS_M,
    INSUNITS_MM,
    INSUNITS_UNKNOWN,
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
    new_doc,
    reload,
)

pytestmark = pytest.mark.known_issue


def _takeoff(doc, factor=MM_TO_M):
    return app.calculate_dxf_quantities(reload(doc), "m", factor)


def _diameter(report, handle):
    rows = [row["Diameter"] for row in report["pipe_detail_rows"] if row["Handle"] == handle]
    return rows[0] if len(rows) == 1 else rows


# --- B.8 vertical pipes and 3D coordinates -----------------------------------------------------


@pytest.mark.xfail(reason="KI-3D: lengths are measured in XY only; Z is ignored", strict=True)
def test_vertical_line_length(validation):
    """A vertical LINE (riser) has true length |dz|."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0, 0), (0, 0, 3000))
    validation.close(
        "KI-3D-01", "3D LINE length (vertical riser)", expected=3.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="LINE (0,0,0)-(0,0,3000) mm on П_Трубы", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-3D: lengths are measured in XY only; Z is ignored", strict=True)
def test_inclined_line_length(validation):
    """An inclined LINE has length sqrt(dx^2 + dz^2)."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0, 0), (3000, 0, 4000))
    validation.close(
        "KI-3D-02", "3D LINE length (inclined)", expected=5.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="LINE (0,0,0)-(3000,0,4000) mm", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-3D: 3D POLYLINE vertices are projected to XY", strict=True)
def test_polyline3d_length(validation):
    """A 3D POLYLINE with a vertical leg includes the vertical length."""
    doc = new_doc(INSUNITS_MM)
    add_polyline3d(doc, [(0, 0, 0), (0, 0, 3000), (1000, 0, 3000)])
    validation.close(
        "KI-3D-03", "3D POLYLINE length", expected=4.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="POLYLINE 3D: 3000 vertical + 1000 horizontal mm", kind="KNOWN-ISSUE",
    )


# --- B.5 duplicates and overlaps ---------------------------------------------------------------


@pytest.mark.xfail(reason="KI-DUP: LWPOLYLINE duplicate signature ignores bulge", strict=True)
def test_polylines_differing_only_in_bulge_are_both_counted(validation):
    """Two LWPOLYLINEs with equal vertices but different bulges are different pipes."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (2000, 0, 0)])
    add_lwpolyline(doc, [(0, 0, 1.0), (2000, 0, 0)])
    validation.close(
        "KI-DUP-01", "duplicate signature must include bulge", expected=(2000.0 + 1000.0 * math.pi) * MM_TO_M,
        actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="straight 2000 mm + semicircle (bulge=1) on same vertices", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DUP: partial collinear overlaps are not detected (needs engineering confirmation)", strict=True)
def test_partial_overlap_counted_once(validation):
    """Two collinear overlapping LINEs on one layer cover 6000 mm, not 8000 mm."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (4000, 0))
    add_line(doc, (2000, 0), (6000, 0))
    validation.close(
        "KI-DUP-02", "partial overlap = union length", expected=6.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="LINE 0-4000 and 2000-6000 mm on П_Трубы", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DUP: duplicates are only searched within one layer", strict=True)
def test_cross_layer_duplicate_counted_once(validation):
    """The same LINE on two pipe layers is one physical pipe."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000), layer=PIPE_LAYER)
    add_line(doc, (0, 0), (3000, 4000), layer=RISER_LAYER)
    validation.close(
        "KI-DUP-03", "cross-layer duplicate", expected=5.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="identical 5000 mm LINE on П_Трубы and П_Трубы_ Опуск", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DUP: LINE and identical LWPOLYLINE have different signatures", strict=True)
def test_line_and_identical_polyline_counted_once(validation):
    """A LINE and an LWPOLYLINE over the same segment are one pipe."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_lwpolyline(doc, [(0, 0, 0), (3000, 4000, 0)])
    validation.close(
        "KI-DUP-04", "cross-type duplicate", expected=5.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="LINE + LWPOLYLINE (0,0)-(3000,4000) mm", kind="KNOWN-ISSUE",
    )


# --- B.7 diameter labels -----------------------------------------------------------------------


@pytest.mark.xfail(reason="KI-DIA: 3000 / 5000 thresholds are in drawing units, not millimetres", strict=True)
def test_marker_threshold_in_metre_drawing(validation):
    """In a metre drawing a marker 100 m away must not label the pipe (V0 intends 3000 mm)."""
    doc = new_doc(INSUNITS_M)
    line = add_line(doc, (0, 0), (5, 0))
    add_text(doc, "ø20", (2.5, 100))
    report = _takeoff(doc, factor=1.0)
    validation.equal(
        "KI-DIA-01", "marker threshold must scale with units", expected="UNKNOWN", actual=_diameter(report, line.dxf.handle),
        basis="INSUNITS=6 (m); LINE 5 m; 'ø20' 100 m from midpoint", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DIA: AutoCAD %%c diameter code is not decoded in TEXT", strict=True)
def test_autocad_diameter_code_recognised(validation):
    """'%%c16' is AutoCAD's encoding of 'Ø16'."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "%%c16", (1000, 1000))
    validation.equal(
        "KI-DIA-02", "%%c16 recognised", expected="DN16", actual=_diameter(_takeoff(doc), line.dxf.handle),
        basis="TEXT '%%c16' 1000 mm from pipe midpoint", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DIA: Russian nominal bore notation 'Ду' is not recognised", strict=True)
def test_russian_nominal_bore_recognised(validation):
    """'Ду15' (условный проход) means DN15."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "Ду15", (1000, 1000))
    validation.equal(
        "KI-DIA-03", "Ду15 recognised", expected="DN15", actual=_diameter(_takeoff(doc), line.dxf.handle),
        basis="TEXT 'Ду15' 1000 mm from pipe midpoint", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DIA: ARC reference point uses OCS coordinates", strict=True)
def test_mirrored_arc_uses_world_coordinates(validation):
    """An ARC with extrusion (0,0,-1) and OCS centre (5000,0) lies at WCS (-5000,0)."""
    doc = new_doc(INSUNITS_MM)
    arc = add_arc(doc, (5000, 0), 1000.0, 0.0, 90.0, extrusion=(0, 0, -1))
    add_text(doc, "DN20", (-5000, 500))
    validation.equal(
        "KI-DIA-04", "OCS -> WCS for marker matching", expected="DN20", actual=_diameter(_takeoff(doc), arc.dxf.handle),
        basis="ARC OCS centre (5000,0), extrusion (0,0,-1) => WCS (-5000,0); 'DN20' 500 mm from WCS centre", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DIA: ARC reference point is its centre, not a point on the pipe", strict=True)
def test_marker_on_large_arc(validation):
    """A marker placed on the arc itself labels the arc."""
    doc = new_doc(INSUNITS_MM)
    arc = add_arc(doc, (0, 0), 4000.0, 0.0, 90.0)
    on_arc = (4000.0 * math.cos(math.radians(45.0)), 4000.0 * math.sin(math.radians(45.0)))
    add_text(doc, "ø16", on_arc)
    validation.equal(
        "KI-DIA-05", "marker on arc", expected="DN16", actual=_diameter(_takeoff(doc), arc.dxf.handle),
        basis="ARC r=4000 0->90; 'ø16' at the arc midpoint (4000 mm from centre)", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DIA: only the midpoint of a LINE is compared with markers", strict=True)
def test_marker_next_to_long_line(validation):
    """A marker 300 mm beside a long pipe labels it, wherever along the pipe it sits."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, (0, 0), (20000, 0))
    add_text(doc, "ø16", (500, 300))
    validation.equal(
        "KI-DIA-06", "marker near a long pipe", expected="DN16", actual=_diameter(_takeoff(doc), line.dxf.handle),
        basis="LINE 20000 mm; 'ø16' 300 mm from the pipe, ~9500 mm from midpoint", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-DIA: 'ø' (outside diameter) is reported as 'DN' (nominal size); engineering decision needed", strict=True)
def test_outside_diameter_not_reported_as_dn(validation):
    """'ø16' denotes an outside diameter and must not be reported as nominal size DN16."""
    validation.equal(
        "KI-DIA-07", "Ø vs DN semantics", expected="Ø16", actual=app._normalize_dxf_diameter_label("ø16"),
        basis="marker text 'ø16'", kind="KNOWN-ISSUE",
    )


# --- B.9 blocks, xrefs, unsupported entities --------------------------------------------------


@pytest.mark.xfail(reason="KI-BLK: geometry inside block references is not measured", strict=True)
def test_pipe_inside_block_is_measured(validation):
    """A pipe LINE inside an inserted block contributes its length."""
    doc = new_doc(INSUNITS_MM)
    ensure_layer(doc, PIPE_LAYER)
    define_block(doc, "PIPE_RUN", lines=[((0, 0), (3000, 4000))], line_layer=PIPE_LAYER)
    add_insert(doc, "PIPE_RUN", (10000, 0), layer=PIPE_LAYER)
    validation.close(
        "KI-BLK-01", "pipe geometry in blocks", expected=5.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="block with LINE 5000 mm on П_Трубы, inserted once at scale 1", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-BLK: MINSERT arrays are counted as one item", strict=True)
def test_minsert_counts_every_instance(validation):
    """An INSERT array of 2 rows x 3 columns places 6 items."""
    doc = new_doc(INSUNITS_MM)
    insert = add_insert(doc, "Радиатор 500", (0, 0), layer=EQUIPMENT_LAYER)
    insert.dxf.row_count = 2
    insert.dxf.column_count = 3
    insert.dxf.row_spacing = 1000
    insert.dxf.column_spacing = 1000
    validation.equal(
        "KI-BLK-02", "MINSERT count", expected=6, actual=_takeoff(doc)["summary"]["equipment_count"],
        basis="INSERT 'Радиатор 500' with 2 rows x 3 columns", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-BLK: equipment tag layer is counted as equipment (engineering confirmation needed)", strict=True)
def test_equipment_tag_not_counted_as_equipment(validation):
    """A tag block on 'Марки оборудования' labels equipment; it is not a second item."""
    doc = new_doc(INSUNITS_MM)
    add_insert(doc, "Радиатор 500", (0, 0), layer=EQUIPMENT_LAYER)
    add_insert(doc, "Марка", (0, 500), layer=EQUIPMENT_TAG_LAYER)
    validation.equal(
        "KI-BLK-03", "equipment tag double count", expected=1, actual=_takeoff(doc)["summary"]["equipment_count"],
        basis="radiator INSERT + tag INSERT", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-BLK: blocks on the valve layer without a valve keyword are dropped silently", strict=True)
def test_unrecognised_valve_layer_block_reported(validation):
    """Every INSERT on the valve layer is counted or listed for review."""
    doc = new_doc(INSUNITS_MM)
    add_insert(doc, "Фильтр сетчатый", (0, 0), layer=VALVE_LAYER)
    validation.equal(
        "KI-BLK-04", "valve-layer block visibility", expected=1, actual=_takeoff(doc)["summary"]["valves_count"],
        basis="INSERT 'Фильтр сетчатый' on 'Арматура трубопроводов'", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-XREF: external references are ignored without a warning", strict=True)
def test_xref_produces_warning(validation):
    """An attached external reference is reported to the user."""
    doc = new_doc(INSUNITS_MM)
    doc.add_xref_def("pipes_xref.dxf", "PIPES_XREF")
    doc.modelspace().add_blockref("PIPES_XREF", (0, 0))
    report = _takeoff(doc)
    mentioned = "xref" in repr(report).lower()
    validation.equal(
        "KI-XREF-01", "xref warning", expected=True, actual=mentioned,
        basis="XREF 'PIPES_XREF' -> pipes_xref.dxf inserted in model space", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-UNS: unsupported entities on pipe layers are neither measured nor reported", strict=True)
def test_unsupported_pipe_entities_reported(validation):
    """SPLINE and ELLIPSE on a pipe layer appear in the report (measured or flagged)."""
    doc = new_doc(INSUNITS_MM)
    ensure_layer(doc, PIPE_LAYER)
    spline = doc.modelspace().add_spline(fit_points=[(0, 0), (1000, 500), (2000, 0)], dxfattribs={"layer": PIPE_LAYER})
    ellipse = doc.modelspace().add_ellipse(center=(5000, 0), major_axis=(1000, 0), ratio=0.5, dxfattribs={"layer": PIPE_LAYER})
    report = _takeoff(doc)
    reported = {row["Handle"] for row in report["pipe_detail_rows"]} | {row["Handle"] for row in report["unknown_review_rows"]}
    validation.equal(
        "KI-UNS-01", "unsupported entity visibility", expected=2,
        actual=len({spline.dxf.handle, ellipse.dxf.handle} & reported),
        basis="SPLINE + ELLIPSE on П_Трубы", kind="KNOWN-ISSUE",
    )


# --- B.10 layer filters / B.4 closed polylines ------------------------------------------------


@pytest.mark.xfail(reason="KI-LAYER: centreline exclusion matches one exact layer name", strict=True)
def test_centerline_name_variant_excluded(validation):
    """'П_Трубы_Осевая линия' (no space) is also a centreline layer."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0), layer="П_Трубы_Осевая линия")
    validation.close(
        "KI-LAYER-01", "centreline name variant", expected=0.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="LINE 1000 mm on 'П_Трубы_Осевая линия'", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-POL: app.py states closed polylines are excluded but counts them (engineering decision needed)", strict=True)
def test_closed_polyline_matches_documented_rule(validation):
    """The report note says closed polylines are excluded; the total should agree."""
    doc = new_doc(INSUNITS_MM)
    add_lwpolyline(doc, [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)], closed=True)
    validation.close(
        "KI-POL-01", "closed polyline rule consistency", expected=0.0, actual=_takeoff(doc)["summary"]["total_pipe_length"],
        basis="closed 1000x1000 LWPOLYLINE on П_Трубы", kind="KNOWN-ISSUE",
    )


# --- B.12 user warnings ------------------------------------------------------------------------


@pytest.mark.xfail(reason="KI-WARN: drawing-unit lengths are labelled 'Length (m)'", strict=True)
def test_unknown_units_not_labelled_metres(validation):
    """Without known units the length column must not claim metres."""
    doc = new_doc(INSUNITS_UNKNOWN)
    add_line(doc, (0, 0), (3000, 4000))
    report = _takeoff(doc, factor=None)
    length_key = [key for key in report["pipe_rows"][0] if key.startswith("Length")]
    validation.equal(
        "KI-WARN-01", "unit label for unknown units", expected=["Length (drawing units)"], actual=length_key,
        basis="$INSUNITS=0, LINE 5000 units", kind="KNOWN-ISSUE",
    )


@pytest.mark.xfail(reason="KI-WARN: an empty drawing returns a placeholder row instead of a warning", strict=True)
def test_empty_drawing_has_no_placeholder(validation):
    """A drawing without pipe geometry yields no diameter rows (and should warn)."""
    report = _takeoff(new_doc(INSUNITS_MM))
    validation.equal(
        "KI-WARN-02", "empty drawing", expected=[], actual=report["pipe_rows"],
        basis="R2018 DXF with no entities", kind="KNOWN-ISSUE",
    )
