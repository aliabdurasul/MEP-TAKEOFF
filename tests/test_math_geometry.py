"""Mathematical correctness of entity lengths against closed-form references.

Expected values come from Euclidean distance, arc length L = r*theta and the
DXF bulge definition (bulge = tan(theta/4)); none are taken from program output.
All drawings use INSUNITS=4 (millimetres); lengths are in drawing units unless noted.
"""

from __future__ import annotations

import math

import pytest

import app
from geometry import measure_entity
from synthetic_dxf import (
    INSUNITS_MM,
    MM_TO_M,
    add_arc,
    add_line,
    add_lwpolyline,
    add_polyline2d,
    entity_by_handle,
    new_doc,
    reload,
)


def _measured_length(doc, entity) -> float:
    reloaded = reload(doc)
    length, _measurable, _ignored = measure_entity(entity_by_handle(reloaded, entity.dxf.handle))
    return length


LINE_CASES = [
    ("GEO-LINE-01", (0, 0), (3000, 4000), 5000.0, "3-4-5 triangle: sqrt(3000^2+4000^2)"),
    ("GEO-LINE-02", (-1000, -1000), (2000, 3000), 5000.0, "negative start, dx=3000 dy=4000"),
    ("GEO-LINE-03", (100, 100), (100, 100), 0.0, "zero-length line"),
    ("GEO-LINE-04", (0, 0), (1000, 1000), 1000.0 * math.sqrt(2.0), "diagonal: 1000*sqrt(2)"),
]


@pytest.mark.parametrize(("case_id", "start", "end", "expected", "basis"), LINE_CASES)
def test_line_length(validation, case_id, start, end, expected, basis):
    """LINE length is the Euclidean distance between its end points."""
    doc = new_doc(INSUNITS_MM)
    line = add_line(doc, start, end)
    validation.close(case_id, "LINE length", expected=expected, actual=_measured_length(doc, line), basis=f"{basis}; mm")


ARC_CASES = [
    ("GEO-ARC-01", (0, 0), 1000.0, 0.0, 90.0, 1000.0 * math.pi / 2.0, "r=1000, 0->90 deg CCW: r*pi/2"),
    ("GEO-ARC-02", (0, 0), 1000.0, 350.0, 10.0, 1000.0 * math.pi / 9.0, "r=1000, 350->10 deg crosses 0: 20 deg sweep"),
    ("GEO-ARC-03", (0, 0), 1000.0, 90.0, 0.0, 1000.0 * 3.0 * math.pi / 2.0, "r=1000, 90->0 deg CCW: 270 deg sweep"),
    ("GEO-ARC-04", (500, 500), 250.0, 0.0, 180.0, 250.0 * math.pi, "r=250, 0->180 deg: half circle"),
]


@pytest.mark.parametrize(("case_id", "center", "radius", "start", "end", "expected", "basis"), ARC_CASES)
def test_arc_length(validation, case_id, center, radius, start, end, expected, basis):
    """ARC length is r * counter-clockwise sweep angle from start to end."""
    doc = new_doc(INSUNITS_MM)
    arc = add_arc(doc, center, radius, start, end)
    validation.close(case_id, "ARC length / angle direction", expected=expected, actual=_measured_length(doc, arc), basis=f"{basis}; mm")


def test_arc_length_with_negative_extrusion(validation):
    """ARC length does not depend on the OCS orientation (extrusion 0,0,-1)."""
    doc = new_doc(INSUNITS_MM)
    arc = add_arc(doc, (5000, 0), 1000.0, 0.0, 90.0, extrusion=(0, 0, -1))
    validation.close(
        "GEO-ARC-05",
        "ARC length with mirrored OCS",
        expected=1000.0 * math.pi / 2.0,
        actual=_measured_length(doc, arc),
        basis="r=1000, 0->90 deg, extrusion (0,0,-1); mm",
    )


QUARTER_BULGE = math.tan(math.radians(90.0) / 4.0)
SIXTY_BULGE = math.tan(math.radians(60.0) / 4.0)

LWPOLYLINE_CASES = [
    ("GEO-PL-01", [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0)], False, 2000.0, "open, two straight 1000 segments"),
    ("GEO-PL-02", [(0, 0, 1.0), (2000, 0, 0)], False, 1000.0 * math.pi, "bulge=1 semicircle on 2000 chord: r=1000, L=pi*r"),
    ("GEO-PL-03", [(0, 0, -1.0), (2000, 0, 0)], False, 1000.0 * math.pi, "bulge=-1 (clockwise) semicircle: same length"),
    (
        "GEO-PL-04",
        [(0, 0, 0), (1000, 0, QUARTER_BULGE), (2000, 1000, 0), (2000, 3000, 0)],
        False,
        3000.0 + 500.0 * math.pi,
        "1000 straight + quarter arc r=1000 (bulge=tan(22.5deg)) + 2000 straight",
    ),
    ("GEO-PL-05", [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)], True, 4000.0, "closed 1000x1000 square incl. closing segment"),
    ("GEO-PL-06", [(0, 0, 1.0), (2000, 0, 1.0)], True, 2000.0 * math.pi, "closed: two bulge=1 semicircles = full circle r=1000"),
    ("GEO-PL-07", [(0, 0, 1.0), (2000, 0, 1.0)], False, 1000.0 * math.pi, "same vertices open: only first semicircle"),
    (
        "GEO-PL-08",
        [(1000, 0, SIXTY_BULGE), (500, 1000 * math.sin(math.radians(60.0)), 0)],
        False,
        1000.0 * math.pi / 3.0,
        "60 deg arc on circle r=1000 (bulge=tan(15deg)): r*pi/3",
    ),
]


@pytest.mark.parametrize(("case_id", "points", "closed", "expected", "basis"), LWPOLYLINE_CASES)
def test_lwpolyline_length(validation, case_id, points, closed, expected, basis):
    """LWPOLYLINE length sums straight and bulge-arc segments, including the closing segment when closed."""
    doc = new_doc(INSUNITS_MM)
    polyline = add_lwpolyline(doc, points, closed=closed)
    validation.close(case_id, "LWPOLYLINE length / bulge / open-closed", expected=expected, actual=_measured_length(doc, polyline), basis=f"{basis}; mm")


def test_polyline2d_bulge_length(validation):
    """Classic 2D POLYLINE with a vertex bulge is measured along the arc."""
    doc = new_doc(INSUNITS_MM)
    polyline = add_polyline2d(doc, [(0, 0), (2000, 0)], bulges=[1.0, 0.0])
    validation.close(
        "GEO-PL-09",
        "POLYLINE (2D) bulge arc",
        expected=1000.0 * math.pi,
        actual=_measured_length(doc, polyline),
        basis="POLYLINE 2D, bulge=1 on 2000 chord; mm",
    )


def test_polyline2d_closed_length(validation):
    """Closed 2D POLYLINE includes the closing segment."""
    doc = new_doc(INSUNITS_MM)
    polyline = add_polyline2d(doc, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)], closed=True)
    validation.close(
        "GEO-PL-10",
        "POLYLINE (2D) closed",
        expected=4000.0,
        actual=_measured_length(doc, polyline),
        basis="closed POLYLINE 2D square 1000; mm",
    )


def test_pipeline_total_in_metres(validation):
    """Full DXF takeoff of LINE + ARC + LWPOLYLINE on the pipe layer equals the analytic sum in metres."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    add_arc(doc, (20000, 0), 1000.0, 0.0, 90.0)
    add_lwpolyline(doc, [(40000, 0, 0), (41000, 0, QUARTER_BULGE), (42000, 1000, 0), (42000, 3000, 0)])
    report = app.calculate_dxf_quantities(reload(doc), "m", MM_TO_M)
    validation.close(
        "GEO-PIPE-01",
        "pipe total = sum of entity lengths, mm -> m",
        expected=(5000.0 + 500.0 * math.pi + 3000.0 + 500.0 * math.pi) * MM_TO_M,
        actual=report["summary"]["total_pipe_length"],
        basis="LINE 5000 + ARC r=1000 90deg + LWPOLYLINE (3000 + quarter arc); total 8+pi m; INSUNITS=4",
    )
