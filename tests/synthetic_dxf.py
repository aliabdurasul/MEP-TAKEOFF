"""Builders for small synthetic DXF drawings with hand-derivable quantities.

Layer names restate the V0 project rule independently of ``app.py`` so that a
silent change to the application's constants is detected by the tests.
"""

from __future__ import annotations

import io
from collections.abc import Iterable

import ezdxf

PIPE_LAYER = "П_Трубы"
RISER_LAYER = "П_Трубы_ Опуск"
CENTERLINE_LAYER = "П_Трубы_ Осевая линия"
MARKER_LAYER = "П_Марки труб"
EQUIPMENT_LAYER = "Оборудование"
EQUIPMENT_TAG_LAYER = "Марки оборудования"
FITTING_LAYER = "Соединительные детали трубопроводов"
VALVE_LAYER = "Арматура трубопроводов"

INSUNITS_UNKNOWN = 0
INSUNITS_INCH = 1
INSUNITS_FOOT = 2
INSUNITS_MM = 4
INSUNITS_CM = 5
INSUNITS_M = 6

MM_TO_M = 0.001


def new_doc(insunits: int = INSUNITS_MM):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    return doc


def ensure_layer(doc, name: str) -> str:
    if not doc.layers.has_entry(name):
        doc.layers.add(name)
    return name


def add_line(doc, start, end, layer: str = PIPE_LAYER):
    ensure_layer(doc, layer)
    return doc.modelspace().add_line(start, end, dxfattribs={"layer": layer})


def add_arc(doc, center, radius, start_angle, end_angle, layer: str = PIPE_LAYER, extrusion=None):
    ensure_layer(doc, layer)
    attribs = {"layer": layer}
    if extrusion is not None:
        attribs["extrusion"] = extrusion
    return doc.modelspace().add_arc(
        center=center, radius=radius, start_angle=start_angle, end_angle=end_angle, dxfattribs=attribs
    )


def add_circle(doc, center, radius, layer: str = PIPE_LAYER):
    ensure_layer(doc, layer)
    return doc.modelspace().add_circle(center, radius, dxfattribs={"layer": layer})


def add_lwpolyline(doc, points_xyb: Iterable, closed: bool = False, layer: str = PIPE_LAYER):
    ensure_layer(doc, layer)
    return doc.modelspace().add_lwpolyline(list(points_xyb), format="xyb", close=closed, dxfattribs={"layer": layer})


def add_polyline2d(doc, points, bulges=None, closed: bool = False, layer: str = PIPE_LAYER):
    ensure_layer(doc, layer)
    polyline = doc.modelspace().add_polyline2d(list(points), close=closed, dxfattribs={"layer": layer})
    for vertex, bulge in zip(polyline.vertices, bulges or []):
        vertex.dxf.bulge = bulge
    return polyline


def add_polyline3d(doc, points, layer: str = PIPE_LAYER):
    ensure_layer(doc, layer)
    return doc.modelspace().add_polyline3d(list(points), dxfattribs={"layer": layer})


def add_text(doc, text: str, insert, height: float = 2.5, layer: str = MARKER_LAYER):
    ensure_layer(doc, layer)
    return doc.modelspace().add_text(text, height=height, dxfattribs={"layer": layer, "insert": insert})


def add_mtext(doc, text: str, insert, char_height: float = 2.5, layer: str = MARKER_LAYER):
    ensure_layer(doc, layer)
    return doc.modelspace().add_mtext(text, dxfattribs={"layer": layer, "insert": insert, "char_height": char_height})


def define_block(doc, name: str, lines: Iterable = (), line_layer: str = "0"):
    if name not in doc.blocks:
        block = doc.blocks.new(name=name)
        for start, end in lines:
            ensure_layer(doc, line_layer)
            block.add_line(start, end, dxfattribs={"layer": line_layer})
    return name


def add_insert(doc, block_name: str, insert=(0, 0), layer: str = "0"):
    define_block(doc, block_name)
    ensure_layer(doc, layer)
    return doc.modelspace().add_blockref(block_name, insert, dxfattribs={"layer": layer})


def to_text(doc) -> str:
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


def to_bytes(doc) -> bytes:
    return to_text(doc).encode("utf-8")


def reload(doc):
    """Write the drawing to DXF text and read it back, as an uploaded file would be."""

    return ezdxf.read(io.StringIO(to_text(doc)))


def entity_by_handle(doc, handle: str):
    return doc.entitydb[handle]
