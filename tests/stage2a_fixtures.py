"""Synthetic drawings for the Stage 2A warning and unit-label checks."""

from __future__ import annotations

from synthetic_dxf import (
    CENTERLINE_LAYER,
    INSUNITS_MM,
    INSUNITS_UNKNOWN,
    PIPE_LAYER,
    RISER_LAYER,
    add_circle,
    add_ellipse,
    add_insert,
    add_line,
    add_spline,
    add_text,
    add_xref,
    new_doc,
)

XREF_NAME = "PIPES_XREF"
XREF_FILE = "pipes_xref.dxf"


def unknown_units_drawing():
    """$INSUNITS=0, one pipe LINE of 5000 drawing units without a diameter marker."""
    doc = new_doc(INSUNITS_UNKNOWN)
    add_line(doc, (0, 0), (3000, 4000))
    return doc


def known_units_drawing():
    """$INSUNITS=4, one pipe LINE of 5000 mm without a diameter marker."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (3000, 4000))
    return doc


def empty_drawing():
    return new_doc(INSUNITS_MM)


def no_pipe_drawing():
    """Geometry exists, but none of it is on a pipe layer."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0), layer="0")
    return doc


def unsupported_drawing():
    """One measurable pipe LINE (1000 mm) plus five non-measured entities on pipe layers.

    Returns the drawing and the handles that must be reported, keyed by (layer, type).
    SPLINEs on layer 0 and on the excluded centreline layer must not be reported.
    """
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    expected = {
        (PIPE_LAYER, "SPLINE"): add_spline(doc, [(0, 1000), (1000, 1500), (2000, 1000)]).dxf.handle,
        (PIPE_LAYER, "ELLIPSE"): add_ellipse(doc, (5000, 0), (1000, 0), 0.5).dxf.handle,
        (PIPE_LAYER, "CIRCLE"): add_circle(doc, (8000, 0), 100.0).dxf.handle,
        (PIPE_LAYER, "TEXT"): add_text(doc, "note", (9000, 0), layer=PIPE_LAYER).dxf.handle,
        (RISER_LAYER, "SPLINE"): add_spline(doc, [(0, 3000), (1000, 3500), (2000, 3000)], layer=RISER_LAYER).dxf.handle,
    }
    add_spline(doc, [(0, 6000), (1000, 6500), (2000, 6000)], layer="0")
    add_spline(doc, [(0, 9000), (1000, 9500), (2000, 9000)], layer=CENTERLINE_LAYER)
    return doc, expected


def xref_drawing(inserted: bool = True):
    """One pipe LINE (1000 mm) and an external reference, optionally inserted once."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    add_xref(doc, XREF_FILE, XREF_NAME, insert_at=(0, 0) if inserted else None)
    return doc


def ordinary_block_drawing():
    """One pipe LINE and an ordinary (non-XREF) block reference."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0))
    add_insert(doc, "Радиатор 500", (0, 5000), layer="0")
    return doc


def clean_drawing():
    """One pipe LINE with a diameter marker: nothing to warn about."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "ø16", (1000, 1000))
    return doc
