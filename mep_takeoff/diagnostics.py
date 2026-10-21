"""Report what the DXF takeoff does not measure or cannot resolve.

These functions describe skipped entities, external references, block content,
overlapping geometry, layer-name findings and unit status so the user can review
them. They never add, remove or estimate quantities.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from geometry import _lwpolyline_points, _polyline_points, entity_geometry_signature, is_mesh_polyline

BLOCK_FLAG_XREF = 4
BLOCK_FLAG_XREF_OVERLAY = 8
MAX_LISTED_HANDLES = 20
MAX_BLOCK_DEPTH = 4
OVERLAP_ANGLE_TOLERANCE = 1e-7
OVERLAP_OFFSET_TOLERANCE = 1e-3
LENGTH_TOLERANCE = 1e-6
DOUBLE_LINE_ANGLE_TOLERANCE = 1e-4
DOUBLE_LINE_MIN_OVERLAP = 0.5
DOUBLE_LINE_MIN_ASPECT = 2.0
PIPE_LIKE_NAME_HINTS = ("pipe", "труб")

LENGTH_UNIT_METRES = "m"
LENGTH_UNIT_DRAWING = "drawing units"


def length_unit(meters_per_unit: float | None) -> str:
    return LENGTH_UNIT_METRES if meters_per_unit is not None else LENGTH_UNIT_DRAWING


def length_unit_label_ru(meters_per_unit: float | None) -> str:
    return "м" if meters_per_unit is not None else "ед. чертежа"


def unsupported_pipe_entities(
    entities: Iterable[Any],
    *,
    is_pipe_layer: Callable[[str], bool],
    layer_of: Callable[[Any], str],
    is_measured: Callable[[Any], bool],
) -> list[dict[str, Any]]:
    """Group entities on included pipe layers that the takeoff does not measure."""

    handles_by_group: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entity in entities:
        layer = layer_of(entity)
        if not is_pipe_layer(layer) or is_measured(entity):
            continue
        handles_by_group[(layer, entity.dxftype())].append(str(entity.dxf.handle))

    rows = []
    for (layer, entity_type), handles in sorted(handles_by_group.items()):
        rows.append({"Layer": layer, "Entity Type": entity_type, "Count": len(handles), "Handles": _listed(handles)})
    return rows


def _listed(handles: list[str]) -> str:
    listed = ", ".join(handles[:MAX_LISTED_HANDLES])
    if len(handles) > MAX_LISTED_HANDLES:
        listed += f", … (+{len(handles) - MAX_LISTED_HANDLES})"
    return listed


def external_references(doc: Any) -> list[dict[str, Any]]:
    """List XREF block definitions and how often each is inserted in model space."""

    insert_counts = Counter(str(entity.dxf.name) for entity in doc.modelspace().query("INSERT"))
    rows = []
    for block_layout in doc.blocks:
        flags = int(_block_attribute(block_layout, "flags", 0) or 0)
        if not flags & BLOCK_FLAG_XREF:
            continue
        rows.append(
            {
                "Name": block_layout.name,
                "Path": str(_block_attribute(block_layout, "xref_path", "") or ""),
                "Model Space Inserts": insert_counts.get(block_layout.name, 0),
                "Overlay": bool(flags & BLOCK_FLAG_XREF_OVERLAY),
            }
        )
    return rows


def xref_dependent_layer_count(doc: Any) -> int:
    return sum(1 for layer in doc.layers if "|" in str(layer.dxf.name))


def _block_attribute(block_layout: Any, name: str, default: Any) -> Any:
    try:
        return block_layout.block.dxf.get(name, default)
    except Exception:
        return default


# --- overlapping and duplicated geometry ---------------------------------------------------------


def polyline_xyb(entity: Any) -> list[tuple[float, float, float]]:
    return _lwpolyline_points(entity) if entity.dxftype() == "LWPOLYLINE" else _polyline_points(entity)


def polyline_is_closed(entity: Any) -> bool:
    return bool(entity.closed) if entity.dxftype() == "LWPOLYLINE" else bool(entity.is_closed)


def straight_segments(entity: Any):
    """Straight plan segments of LINE and polyline entities (bulged segments are skipped)."""

    kind = entity.dxftype()
    if kind == "LINE":
        start, end = entity.dxf.start, entity.dxf.end
        yield (float(start.x), float(start.y)), (float(end.x), float(end.y))
        return
    if kind not in {"LWPOLYLINE", "POLYLINE"} or is_mesh_polyline(entity):
        return
    points = polyline_xyb(entity)
    pairs = list(zip(points, points[1:]))
    if polyline_is_closed(entity) and len(points) > 1:
        pairs.append((points[-1], points[0]))
    for start, end in pairs:
        if abs(start[2]) < 1e-12:
            yield (start[0], start[1]), (end[0], end[1])


def _collinear_key(start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    if math.hypot(dx, dy) <= LENGTH_TOLERANCE:
        return None
    angle = math.atan2(dy, dx) % math.pi
    if math.pi - angle < OVERLAP_ANGLE_TOLERANCE:
        angle = 0.0
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    offset = -sin_a * start[0] + cos_a * start[1]
    t1 = cos_a * start[0] + sin_a * start[1]
    t2 = cos_a * end[0] + sin_a * end[1]
    return (round(angle / OVERLAP_ANGLE_TOLERANCE), round(offset / OVERLAP_OFFSET_TOLERANCE)), (min(t1, t2), max(t1, t2))


def interval_overlap(intervals) -> float:
    """Sum of interval lengths minus the length of their union."""

    total = sum(high - low for low, high in intervals)
    union = 0.0
    current = None
    for low, high in sorted(intervals):
        if current is None or low > current[1]:
            if current is not None:
                union += current[1] - current[0]
            current = [low, high]
        else:
            current[1] = max(current[1], high)
    if current is not None:
        union += current[1] - current[0]
    return total - union


def _overlapping_pairs(members):
    ordered = sorted(members, key=lambda member: member[0])
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if second[0] >= first[1] - LENGTH_TOLERANCE:
                break
            if min(first[1], second[1]) - second[0] > LENGTH_TOLERANCE:
                yield first, second


@dataclass(frozen=True)
class OverlapSummary:
    same_layer_length: float
    same_layer_segments: int
    same_layer_handles: frozenset
    mixed_type_groups: int
    across_layers_length: float
    across_layers_groups: int
    across_layers_handles: frozenset


def collinear_overlaps(entities_by_layer: dict[str, list]) -> OverlapSummary:
    """Collinear overlap of straight pipe segments, within a layer and across layers (drawing units)."""

    by_layer_key: dict[tuple, list] = defaultdict(list)
    types_by_layer_key: dict[tuple, set] = defaultdict(set)
    by_key: dict[tuple, list] = defaultdict(list)
    for layer, entities in entities_by_layer.items():
        for entity in entities:
            kind = "LINE" if entity.dxftype() == "LINE" else "POLYLINE"
            handle = str(entity.dxf.handle)
            for start, end in straight_segments(entity):
                keyed = _collinear_key(start, end)
                if keyed is None:
                    continue
                key, (low, high) = keyed
                by_layer_key[(layer, key)].append((low, high, handle, layer))
                types_by_layer_key[(layer, key)].add(kind)
                by_key[key].append((low, high, handle, layer))

    same_length, same_segments, mixed_groups = 0.0, 0, 0
    same_handles: set[str] = set()
    same_by_key: dict[tuple, float] = defaultdict(float)
    for (layer, key), members in by_layer_key.items():
        overlap = interval_overlap([(low, high) for low, high, _handle, _layer in members])
        if overlap > LENGTH_TOLERANCE:
            same_length += overlap
            same_segments += len(members)
            same_by_key[key] += overlap
            if len(types_by_layer_key[(layer, key)]) > 1:
                mixed_groups += 1
            for first, second in _overlapping_pairs(members):
                same_handles.update((first[2], second[2]))

    across_length, across_groups = 0.0, 0
    across_handles: set[str] = set()
    for key, members in by_key.items():
        cross = interval_overlap([(low, high) for low, high, _handle, _layer in members]) - same_by_key.get(key, 0.0)
        if cross > LENGTH_TOLERANCE:
            across_length += cross
            across_groups += 1
            for first, second in _overlapping_pairs(members):
                if first[3] != second[3]:
                    across_handles.update((first[2], second[2]))

    return OverlapSummary(
        same_layer_length=same_length,
        same_layer_segments=same_segments,
        same_layer_handles=frozenset(same_handles),
        mixed_type_groups=mixed_groups,
        across_layers_length=across_length,
        across_layers_groups=across_groups,
        across_layers_handles=frozenset(across_handles),
    )


@dataclass(frozen=True)
class _Segment:
    handle: str
    x0: float
    y0: float
    x1: float
    y1: float
    ux: float
    uy: float
    length: float
    angle: float
    offset: float


def _oriented_segment(handle: str, start, end) -> _Segment | None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= LENGTH_TOLERANCE:
        return None
    ux, uy = dx / length, dy / length
    angle = math.atan2(uy, ux)
    if angle < 0:
        angle += math.pi
        ux, uy = -ux, -uy
    if angle >= math.pi - DOUBLE_LINE_ANGLE_TOLERANCE:
        angle -= math.pi
        ux, uy = -ux, -uy
    return _Segment(handle, start[0], start[1], end[0], end[1], ux, uy, length, angle, -uy * start[0] + ux * start[1])


def _parallel_offset(a: _Segment, b: _Segment, max_offset: float) -> float | None:
    """Distance between two parallel segments that run side by side, or None."""

    if abs(a.ux * b.uy - a.uy * b.ux) > math.sin(DOUBLE_LINE_ANGLE_TOLERANCE):
        return None
    mid_x, mid_y = (b.x0 + b.x1) / 2.0, (b.y0 + b.y1) / 2.0
    distance = abs(-a.uy * (mid_x - a.x0) + a.ux * (mid_y - a.y0))
    if distance <= OVERLAP_OFFSET_TOLERANCE or distance > max_offset:
        return None
    t0 = a.ux * (b.x0 - a.x0) + a.uy * (b.y0 - a.y0)
    t1 = a.ux * (b.x1 - a.x0) + a.uy * (b.y1 - a.y0)
    shorter = min(a.length, b.length)
    overlap = min(a.length, max(t0, t1)) - max(0.0, min(t0, t1))
    if overlap < DOUBLE_LINE_MIN_OVERLAP * shorter or shorter < DOUBLE_LINE_MIN_ASPECT * distance:
        return None
    return distance


@dataclass(frozen=True)
class DoubleLineSummary:
    segment_count: int
    pair_count: int
    length: float
    handles: frozenset
    by_layer: dict
    offsets: tuple


def possible_double_lines(entities_by_layer: dict[str, list], max_offset: float) -> DoubleLineSummary:
    """Straight segments with a parallel neighbour on the same layer, at most ``max_offset`` away.

    Such pairs may be the two walls of a pipe drawn as a double line, but parallel single-line
    pipes look the same. Nothing is removed, merged or corrected (drawing units).
    """

    flagged: dict[tuple, _Segment] = {}
    pair_count = 0
    offsets: Counter = Counter()
    for layer, entities in entities_by_layer.items():
        segments: list[_Segment] = []
        for entity in entities:
            handle = str(entity.dxf.handle)
            for start, end in straight_segments(entity):
                segment = _oriented_segment(handle, start, end)
                if segment is not None:
                    segments.append(segment)
        if len(segments) < 2:
            continue
        reach = max(max(abs(s.x0), abs(s.y0), abs(s.x1), abs(s.y1)) for s in segments)
        window = max_offset + 2.0 * DOUBLE_LINE_ANGLE_TOLERANCE * reach
        buckets: dict[int, list[int]] = defaultdict(list)
        for index, segment in enumerate(segments):
            buckets[round(segment.angle / DOUBLE_LINE_ANGLE_TOLERANCE)].append(index)
        for bucket, members in buckets.items():
            combined = sorted(members + buckets.get(bucket + 1, []), key=lambda index: segments[index].offset)
            own = set(members)
            for position, first in enumerate(combined):
                for second in combined[position + 1:]:
                    if segments[second].offset - segments[first].offset > window:
                        break
                    if first not in own and second not in own:
                        continue
                    distance = _parallel_offset(segments[first], segments[second], max_offset)
                    if distance is None:
                        continue
                    pair_count += 1
                    offsets[round(distance, 1)] += 1
                    for index in (first, second):
                        flagged[(layer, index)] = segments[index]
    by_layer: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for (layer, _index), segment in flagged.items():
        by_layer[layer][0] += 1
        by_layer[layer][1] += segment.length
    return DoubleLineSummary(
        segment_count=len(flagged),
        pair_count=pair_count,
        length=math.fsum(segment.length for segment in flagged.values()),
        handles=frozenset(segment.handle for segment in flagged.values()),
        by_layer={layer: tuple(values) for layer, values in by_layer.items()},
        offsets=tuple(offset for offset, _count in offsets.most_common(5)),
    )


def identical_arcs_across_layers(entities_by_layer: dict[str, list], measure: Callable[[Any], float]) -> tuple[int, float, frozenset]:
    """Identical ARCs on different pipe layers: extra copies and their length (drawing units)."""

    by_signature: dict[tuple, list] = defaultdict(list)
    for layer, entities in entities_by_layer.items():
        for entity in entities:
            if entity.dxftype() == "ARC":
                by_signature[entity_geometry_signature(entity)].append((layer, entity))
    extra_count, extra_length = 0, 0.0
    handles: set[str] = set()
    for members in by_signature.values():
        if len({layer for layer, _entity in members}) < 2:
            continue
        handles.update(str(entity.dxf.handle) for _layer, entity in members)
        for _layer, entity in members[1:]:
            extra_count += 1
            extra_length += measure(entity)
    return extra_count, extra_length, frozenset(handles)


# --- block content ------------------------------------------------------------------------------


def insert_instance_count(insert: Any) -> int:
    try:
        return max(1, int(getattr(insert, "mcount", 1) or 1))
    except Exception:
        return 1


def _pipe_geometry_in_insert(insert, effective_layer: str, depth: int, is_pipe_layer, measure) -> tuple[float, int, int, int]:
    try:
        children = list(insert.virtual_entities())
    except Exception:
        return 0.0, 0, 0, 1
    length, count, unsupported, failures = 0.0, 0, 0, 0
    for child in children:
        layer = str(child.dxf.get("layer", "0") or "0")
        if layer == "0":
            layer = effective_layer
        if child.dxftype() == "INSERT":
            if depth >= MAX_BLOCK_DEPTH:
                failures += 1
                continue
            instances = list(child.multi_insert()) if insert_instance_count(child) > 1 else [child]
            for instance in instances:
                sub = _pipe_geometry_in_insert(instance, layer, depth + 1, is_pipe_layer, measure)
                length, count, unsupported, failures = length + sub[0], count + sub[1], unsupported + sub[2], failures + sub[3]
            continue
        if not is_pipe_layer(layer):
            continue
        raw_length, measurable, ignored = measure(child)
        if measurable and not ignored:
            length += raw_length
            count += 1
        else:
            unsupported += 1
    return length, count, unsupported, failures


def pipe_geometry_in_blocks(doc: Any, *, is_pipe_layer: Callable[[str], bool], layer_of: Callable[[Any], str], measure) -> dict[str, Any]:
    """Pipe-layer geometry inside model-space block references, per placed instance (drawing units).

    Nested blocks are followed through their placed references only, so a nested
    definition is counted once per placement and never in addition to it.
    """

    per_block: dict[str, list] = defaultdict(lambda: [0, 0, 0.0])
    total_length, total_count, unsupported, failures = 0.0, 0, 0, 0
    for insert in doc.modelspace().query("INSERT"):
        layer = layer_of(insert)
        instances = list(insert.multi_insert()) if insert_instance_count(insert) > 1 else [insert]
        found = 0
        for instance in instances:
            length, count, unmeasured, failed = _pipe_geometry_in_insert(instance, layer, 0, is_pipe_layer, measure)
            total_length += length
            total_count += count
            unsupported += unmeasured
            failures += failed
            found += count
            per_block[str(insert.dxf.name)][1] += count
            per_block[str(insert.dxf.name)][2] += length
        if found:
            per_block[str(insert.dxf.name)][0] += 1
    rows = [
        {"Block": name, "Inserts": values[0], "Pipe Entities": values[1], "Length (du)": values[2]}
        for name, values in sorted(per_block.items())
        if values[1]
    ]
    return {"rows": rows, "entity_count": total_count, "length_du": total_length, "unsupported": unsupported, "failures": failures}


# --- layer names ---------------------------------------------------------------------------------


def pipe_layer_findings(doc: Any, entities: Iterable[Any], *, is_pipe_layer, layer_of, measure, prefix: str) -> list[dict[str, Any]]:
    """Pipe-like layers whose inclusion or visibility needs review (drawing units)."""

    table = {str(layer.dxf.name): layer for layer in doc.layers}
    measured: dict[str, list] = defaultdict(lambda: [0, 0.0])
    names = set(table)
    for entity in entities:
        layer = layer_of(entity)
        names.add(layer)
        raw_length, measurable, ignored = measure(entity)
        if measurable and not ignored:
            measured[layer][0] += 1
            measured[layer][1] += raw_length

    findings = []
    for name in sorted(names):
        folded = name.casefold()
        if not (folded.startswith(prefix.casefold()) or ("|" in name and prefix.casefold() in folded)):
            continue
        included = is_pipe_layer(name)
        entry = table.get(name)
        frozen_or_off = bool(entry is not None and (entry.is_frozen() or entry.is_off()))
        count, length = measured.get(name, [0, 0.0])
        issues = []
        if included and "осев" in folded:
            issues.append(("NAME", "centreline-like name but included"))
        if included and frozen_or_off:
            issues.append(("HIDDEN", "frozen or off but included"))
        if not included and not name.startswith(prefix) and folded.startswith(prefix.casefold()):
            issues.append(("NAME", "prefix case variant not included"))
        if not included and "|" in name:
            issues.append(("NAME", "xref-dependent layer not included"))
        for kind, issue in issues:
            findings.append({"Layer": name, "Issue": issue, "Kind": kind, "Included": included, "Entities": count, "Length (du)": length})
    return findings


def is_pipe_like_name(name: str) -> bool:
    folded = name.casefold()
    return any(hint in folded for hint in PIPE_LIKE_NAME_HINTS)


def pipe_like_layers_not_included(
    entities: Iterable[Any],
    layer_names: Iterable[str],
    *,
    is_pipe_layer: Callable[[str], bool],
    layer_of: Callable[[Any], str],
    measure,
    skip: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Layers whose name looks like pipe (PIPE, Труб) that the takeoff does not include but that hold
    measurable geometry. A name match is only a hint for review (drawing units)."""

    skipped = set(skip)
    totals: dict[str, list] = defaultdict(lambda: [0, 0, 0.0])
    for entity in entities:
        layer = layer_of(entity)
        totals[layer][0] += 1
        raw_length, measurable, ignored = measure(entity)
        if measurable and not ignored:
            totals[layer][1] += 1
            totals[layer][2] += raw_length
    rows = []
    for name in sorted(set(layer_names) | set(totals)):
        if name in skipped or is_pipe_layer(name) or not is_pipe_like_name(name):
            continue
        count, measurable, length = totals.get(name, [0, 0, 0.0])
        if measurable:
            rows.append({"Layer": name, "Entities": count, "Measurable Entities": measurable, "Raw Length (du)": length})
    return rows


# --- warnings ------------------------------------------------------------------------------------


def _warning(code: str, count: int | None, message: str, length: float | None = None) -> dict[str, Any]:
    return {"Code": code, "Severity": "warning", "Count": count, "Length": None if length is None else round(length, 6), "Message": message}


def _length_text(length: float, meters_per_unit: float | None) -> str:
    return f"{length:,.3f} {length_unit_label_ru(meters_per_unit)}"


def takeoff_warnings(
    *,
    meters_per_unit: float | None,
    pipe_entity_count: int,
    pipe_layers_label: str,
    unsupported_rows: list[dict[str, Any]],
    xref_rows: list[dict[str, Any]],
    xref_layer_count: int,
    z_variation: tuple[int, float] = (0, 0.0),
    closed_polylines: tuple[int, float] = (0, 0.0),
    full_circle_arcs: tuple[int, float] = (0, 0.0),
    overlap_same_layer: tuple[int, float] = (0, 0.0),
    overlap_across_layers: tuple[int, float] = (0, 0.0),
    diameter_candidates: tuple[int, float] = (0, 0.0),
    diameter_types: Iterable[str] = (),
    blocks_with_pipe: tuple[int, float] = (0, 0.0),
    unrecognized_on_mep_layers: int = 0,
    tag_layer_inserts: int = 0,
    anonymous_inserts: int = 0,
    layer_findings: list[dict[str, Any]] | None = None,
    load_info: dict[str, Any] | None = None,
    pipe_like_layers: list[dict[str, Any]] | None = None,
    double_lines: tuple[int, float, tuple] = (0, 0.0, ()),
    double_line_max_offset: str = "",
) -> list[dict[str, Any]]:
    """Build the user-visible warnings. Lengths are in report units (metres or drawing units)."""

    warnings: list[dict[str, Any]] = []

    if load_info and load_info.get("mode") == "recovered":
        warnings.append(
            _warning(
                "DRAWING_RECOVERED",
                int(load_info.get("fixes", 0)) + int(load_info.get("errors", 0)),
                (
                    "Чертёж повреждён и открыт в режиме восстановления "
                    f"(исправлений: {load_info.get('fixes', 0)}, неустранимых ошибок: {load_info.get('errors', 0)}). "
                    "Часть геометрии могла быть потеряна — результаты требуют проверки по исходному чертежу."
                ),
            )
        )

    if meters_per_unit is None:
        warnings.append(
            _warning(
                "UNKNOWN_UNITS",
                None,
                "Единицы чертежа не определены: все длины указаны в единицах чертежа, а не в метрах. "
                "Перевод в метры не выполнен — выберите единицы вручную.",
            )
        )

    if pipe_entity_count == 0:
        warnings.append(
            _warning(
                "NO_PIPE_GEOMETRY",
                0,
                f"На трубных слоях ({pipe_layers_label}) не найдено измеряемой геометрии "
                "(LINE, LWPOLYLINE, POLYLINE, ARC). Метраж труб не рассчитан.",
            )
        )

    if unsupported_rows:
        total = sum(int(row["Count"]) for row in unsupported_rows)
        by_type: Counter = Counter()
        for row in unsupported_rows:
            by_type[row["Entity Type"]] += int(row["Count"])
        types = ", ".join(f"{entity_type}: {count}" for entity_type, count in sorted(by_type.items()))
        layers = ", ".join(sorted({str(row["Layer"]) for row in unsupported_rows}))
        warnings.append(
            _warning(
                "UNSUPPORTED_PIPE_ENTITIES",
                total,
                f"На трубных слоях {total} объект(ов) не измерены и не включены в метраж: {types}. "
                f"Слои: {layers}. Требуется ручная проверка.",
            )
        )

    if xref_rows:
        references = ", ".join(
            f"{row['Name']} ({row['Path'] or 'путь не указан'}, вставок в модели: {row['Model Space Inserts']})"
            for row in xref_rows
        )
        layer_note = f" Слоёв из XREF: {xref_layer_count}." if xref_layer_count else ""
        warnings.append(
            _warning(
                "XREF_NOT_PROCESSED",
                len(xref_rows),
                f"Чертёж содержит внешние ссылки (XREF): {references}. "
                f"Их содержимое не обрабатывается и не входит в метраж.{layer_note}",
            )
        )

    count, length = z_variation
    if count:
        warnings.append(
            _warning(
                "Z_VARIATION_PLAN_LENGTH_REPORTED",
                count,
                f"{count} объект(ов) имеют разные отметки Z. Метраж указан по проекции на план (XY); "
                f"3D-длина больше на {_length_text(length, meters_per_unit)}. Выбор базы длины — решение инженера.",
                length,
            )
        )

    count, length = closed_polylines
    if count:
        warnings.append(
            _warning(
                "CLOSED_POLYLINES_COUNTED",
                count,
                f"{count} замкнутых полилиний на трубных слоях включены в метраж ({_length_text(length, meters_per_unit)}). "
                "Это могут быть символы или контуры — проверьте.",
                length,
            )
        )

    count, length = full_circle_arcs
    if count:
        warnings.append(
            _warning(
                "FULL_CIRCLE_ARCS_COUNTED",
                count,
                f"{count} дуг(и) с совпадающими углами начала и конца посчитаны как полная окружность "
                f"({_length_text(length, meters_per_unit)}). Часто это символы стояков — проверьте.",
                length,
            )
        )

    count, length = overlap_same_layer
    if count:
        warnings.append(
            _warning(
                "OVERLAP_SAME_LAYER_COUNTED",
                count,
                f"{count} объект(ов) перекрываются на одном слое (включая LINE и полилинию с одинаковой геометрией). "
                f"Перекрытие {_length_text(length, meters_per_unit)} включено в метраж — возможен двойной счёт.",
                length,
            )
        )

    count, length = overlap_across_layers
    if count:
        warnings.append(
            _warning(
                "OVERLAP_ACROSS_LAYERS_COUNTED",
                count,
                f"{count} объект(ов) совпадают или перекрываются на разных трубных слоях. "
                f"Перекрытие {_length_text(length, meters_per_unit)} включено в метраж — возможен двойной счёт.",
                length,
            )
        )

    count, length = diameter_candidates
    if count:
        warnings.append(
            _warning(
                "DIAMETER_CANDIDATES_UNRESOLVED",
                count,
                f"{count} труб(ы) без диаметра имеют маркеры рядом с геометрией, но не у опорной точки "
                f"({_length_text(length, meters_per_unit)}). Диаметр не присвоен; кандидаты показаны в таблице.",
                length,
            )
        )

    types = sorted(set(diameter_types))
    if "OUTSIDE_DIAMETER" in types and "NOMINAL_DN" in types:
        warnings.append(
            _warning(
                "MIXED_DIAMETER_NOTATION",
                None,
                "В чертеже есть и наружные диаметры (Ø), и условные проходы (DN). "
                "Они не пересчитываются друг в друга и суммируются раздельно.",
            )
        )

    count, length = blocks_with_pipe
    if count:
        warnings.append(
            _warning(
                "PIPE_GEOMETRY_IN_BLOCKS_NOT_MEASURED",
                count,
                f"В блоках найдено {count} объект(ов) на трубных слоях ({_length_text(length, meters_per_unit)}). "
                "Они не включены в метраж — является ли это трубой, решает инженер.",
                length,
            )
        )

    if unrecognized_on_mep_layers:
        warnings.append(
            _warning(
                "UNRECOGNIZED_SYMBOLS_ON_MEP_LAYERS",
                unrecognized_on_mep_layers,
                f"{unrecognized_on_mep_layers} блок(ов) на инженерных слоях не распознаны и не посчитаны "
                "(см. таблицу нераспознанных блоков).",
            )
        )

    if tag_layer_inserts:
        warnings.append(
            _warning(
                "EQUIPMENT_TAG_LAYER_COUNTED",
                tag_layer_inserts,
                f"{tag_layer_inserts} блок(ов) на слое марок оборудования посчитаны как оборудование. "
                "Если это марки, а не оборудование, возможен двойной счёт.",
            )
        )

    if anonymous_inserts:
        warnings.append(
            _warning(
                "ANONYMOUS_BLOCKS_CLASSIFIED_BY_LAYER",
                anonymous_inserts,
                f"{anonymous_inserts} анонимных (динамических) блок(ов) классифицированы только по слою.",
            )
        )

    findings = layer_findings or []
    name_findings = [row for row in findings if row["Kind"] == "NAME"]
    if name_findings:
        details = "; ".join(f"{row['Layer']}: {row['Issue']}" for row in name_findings)
        warnings.append(
            _warning(
                "PIPE_LAYER_NAME_REVIEW",
                len(name_findings),
                f"Проверьте трубные слои: {details}.",
                sum(float(row["Length (m)"]) for row in name_findings),
            )
        )
    hidden_findings = [row for row in findings if row["Kind"] == "HIDDEN"]
    if hidden_findings:
        layers = ", ".join(row["Layer"] for row in hidden_findings)
        warnings.append(
            _warning(
                "HIDDEN_PIPE_LAYER_COUNTED",
                len(hidden_findings),
                f"Замороженные или отключённые трубные слои включены в метраж: {layers}.",
                sum(float(row["Length (m)"]) for row in hidden_findings),
            )
        )

    if pipe_like_layers:
        details = "; ".join(
            f"{row['Layer']}: объектов {row['Entities']}, измеряемых {row['Measurable Entities']}, "
            f"сырая длина {row['Raw Length (du)']:,.3f} ед. чертежа"
            for row in pipe_like_layers
        )
        warnings.append(
            _warning(
                "PIPE_LIKE_LAYER_NOT_INCLUDED",
                len(pipe_like_layers),
                f"Слои с названием, похожим на трубы, не входят в метраж: {details}. "
                "Это только совпадение по имени, а не подтверждение, что это трубы. "
                "Чтобы включить слой, выберите его вручную в списке трубных слоёв и проверьте результат.",
            )
        )

    count, length, offsets = double_lines
    if count:
        typical = ", ".join(f"{offset:g}" for offset in offsets)
        warnings.append(
            _warning(
                "DOUBLE_LINE_PIPE",
                count,
                f"{count} отрезк(ов) на трубных слоях ({_length_text(length, meters_per_unit)}) имеют параллельного соседа "
                f"на расстоянии до {double_line_max_offset} (типичные расстояния, ед. чертежа: {typical}). "
                "Возможно, труба начерчена двумя линиями (стенками) — тогда метраж завышен примерно вдвое. "
                "Это вероятность, а не точное определение: параллельные трубы (например, подача и обратка) дают то же. "
                "Линии не удаляются и не объединяются, длина не исправляется — проверьте чертёж.",
                length,
            )
        )

    return warnings
