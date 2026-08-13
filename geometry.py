from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


SUPPORTED_MEASURABLE_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}
SUPPORTED_COUNTED_TYPES = SUPPORTED_MEASURABLE_TYPES | {"CIRCLE"}


@dataclass(frozen=True)
class MeasurementRow:
    object_id: int
    layer: str
    entity_type: str
    raw_length: float
    converted_length: float
    display_unit: str


def distance_2d(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def bulge_arc_length(start: tuple[float, float], end: tuple[float, float], bulge: float) -> float:
    if bulge == 0:
        return distance_2d(start, end)

    chord = distance_2d(start, end)
    if chord == 0:
        return 0.0

    theta = 4.0 * math.atan(abs(bulge))
    if theta == 0:
        return chord

    radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    return radius * theta


def arc_length(radius: float, start_angle_deg: float, end_angle_deg: float) -> float:
    start = math.radians(start_angle_deg)
    end = math.radians(end_angle_deg)
    sweep = end - start
    if sweep <= 0:
        sweep += 2 * math.pi
    return abs(radius * sweep)


def _entity_xy(entity: Any) -> tuple[float, float]:
    location = getattr(entity.dxf, "location", None)
    if location is not None:
        return float(location.x), float(location.y)
    return 0.0, 0.0


def _lwpolyline_points(entity: Any) -> list[tuple[float, float, float]]:
    points = []
    for point in entity.get_points("xyb"):
        if len(point) == 3:
            x, y, bulge = point
        else:
            x, y = point[:2]
            bulge = 0.0
        points.append((float(x), float(y), float(bulge)))
    return points


def _polyline_points(entity: Any) -> list[tuple[float, float, float]]:
    points = []
    vertices = entity.vertices() if callable(getattr(entity, "vertices", None)) else getattr(entity, "vertices", [])
    for vertex in vertices:
        location = vertex.dxf.location
        bulge = float(getattr(vertex.dxf, "bulge", 0.0) or 0.0)
        points.append((float(location.x), float(location.y), bulge))
    return points


def polyline_length(points: Iterable[tuple[float, float, float]], closed: bool) -> float:
    ordered = list(points)
    if len(ordered) < 2:
        return 0.0

    total = 0.0
    for index in range(len(ordered) - 1):
        start = ordered[index]
        end = ordered[index + 1]
        total += bulge_arc_length((start[0], start[1]), (end[0], end[1]), start[2])

    if closed:
        start = ordered[-1]
        end = ordered[0]
        total += bulge_arc_length((start[0], start[1]), (end[0], end[1]), start[2])

    return total


def measure_entity(entity: Any) -> tuple[float, bool, bool]:
    entity_type = entity.dxftype()

    if entity_type == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        return distance_2d((float(start.x), float(start.y)), (float(end.x), float(end.y))), True, False

    if entity_type == "LWPOLYLINE":
        return polyline_length(_lwpolyline_points(entity), bool(entity.closed)), True, False

    if entity_type == "POLYLINE":
        return polyline_length(_polyline_points(entity), bool(entity.is_closed)), True, False

    if entity_type == "ARC":
        return arc_length(float(entity.dxf.radius), float(entity.dxf.start_angle), float(entity.dxf.end_angle)), True, False

    if entity_type == "CIRCLE":
        return 0.0, False, False

    return 0.0, False, True


def convert_length(value: float, meters_per_unit: float | None) -> float:
    if meters_per_unit is None:
        return value
    return value * meters_per_unit


def unit_label_for_factor(meters_per_unit: float | None, known_unit: str | None = None) -> str:
    if meters_per_unit is None:
        return "drawing units"
    if known_unit:
        return "m"
    return "m"


def make_measurement_rows(
    entities: list[Any],
    *,
    layer_name: str,
    meters_per_unit: float | None,
    display_unit_label: str,
) -> list[MeasurementRow]:
    rows: list[MeasurementRow] = []
    object_id = 1
    for entity in entities:
        raw_length, measurable, ignored = measure_entity(entity)
        if not measurable or ignored:
            continue
        converted = convert_length(raw_length, meters_per_unit)
        rows.append(
            MeasurementRow(
                object_id=object_id,
                layer=layer_name,
                entity_type=entity.dxftype(),
                raw_length=raw_length,
                converted_length=converted,
                display_unit=display_unit_label,
            )
        )
        object_id += 1
    return rows


def approximate_entity_segments(entity: Any, arc_segments: int = 48) -> list[list[tuple[float, float]]]:
    entity_type = entity.dxftype()

    if entity_type == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        return [[(float(start.x), float(start.y)), (float(end.x), float(end.y))]]

    if entity_type == "ARC":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        start_angle = math.radians(float(entity.dxf.start_angle))
        end_angle = math.radians(float(entity.dxf.end_angle))
        sweep = end_angle - start_angle
        if sweep <= 0:
            sweep += 2 * math.pi
        points = []
        for index in range(arc_segments + 1):
            angle = start_angle + (sweep * index / arc_segments)
            points.append((float(center.x) + radius * math.cos(angle), float(center.y) + radius * math.sin(angle)))
        return [points]

    if entity_type == "LWPOLYLINE":
        points = _lwpolyline_points(entity)
        return _polyline_preview_segments(points, bool(entity.closed), arc_segments)

    if entity_type == "POLYLINE":
        points = _polyline_points(entity)
        return _polyline_preview_segments(points, bool(entity.is_closed), arc_segments)

    return []


def _polyline_preview_segments(
    points: list[tuple[float, float, float]],
    closed: bool,
    arc_segments: int,
) -> list[list[tuple[float, float]]]:
    if len(points) < 2:
        return []

    segments: list[list[tuple[float, float]]] = []
    for index in range(len(points) - 1):
        start = points[index]
        end = points[index + 1]
        if start[2] == 0:
            segments.append([(start[0], start[1]), (end[0], end[1])])
        else:
            segments.append(_bulge_preview_points((start[0], start[1]), (end[0], end[1]), start[2], arc_segments))

    if closed:
        start = points[-1]
        end = points[0]
        if start[2] == 0:
            segments.append([(start[0], start[1]), (end[0], end[1])])
        else:
            segments.append(_bulge_preview_points((start[0], start[1]), (end[0], end[1]), start[2], arc_segments))

    return segments


def _bulge_preview_points(
    start: tuple[float, float],
    end: tuple[float, float],
    bulge: float,
    arc_segments: int,
) -> list[tuple[float, float]]:
    if bulge == 0:
        return [start, end]

    chord = distance_2d(start, end)
    if chord == 0:
        return [start, end]

    theta = 4.0 * math.atan(abs(bulge))
    radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    midpoint_x = (start[0] + end[0]) / 2.0
    midpoint_y = (start[1] + end[1]) / 2.0
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    chord_angle = math.atan2(dy, dx)
    sagitta = radius - math.sqrt(max(radius * radius - (chord / 2.0) ** 2, 0.0))
    if bulge < 0:
        sagitta = -sagitta

    normal_angle = chord_angle + math.pi / 2.0
    center_x = midpoint_x + sagitta * math.cos(normal_angle)
    center_y = midpoint_y + sagitta * math.sin(normal_angle)

    start_angle = math.atan2(start[1] - center_y, start[0] - center_x)
    sweep = theta if bulge > 0 else -theta
    points = []
    for index in range(arc_segments + 1):
        angle = start_angle + sweep * index / arc_segments
        points.append((center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)))
    return points