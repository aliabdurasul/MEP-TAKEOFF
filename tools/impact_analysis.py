"""Read-only impact analysis of the known takeoff issues on one DXF drawing.

Run only in an authorised local environment; the drawing is never uploaded:

    python tools/impact_analysis.py data/input/<drawing>.dxf
    python tools/impact_analysis.py data/input/<drawing>.dxf --output data/output/impact.md

The drawing is opened read-only and the current V0 takeoff runs unchanged. Each
section measures how many entities and how much length a known-issue group
touches. Nothing here changes a quantity rule. Output goes to stdout unless
--output is given; existing output files are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ezdxf import path as ezdxf_path  # noqa: E402
from ezdxf.math import Vec3  # noqa: E402

import app  # noqa: E402
from geometry import (  # noqa: E402
    _lwpolyline_points,
    _polyline_points,
    deduplicate_entities,
    entity_geometry_signature,
    measure_entity,
)
from mep_takeoff.diagnostics import (  # noqa: E402
    OVERLAP_ANGLE_TOLERANCE,
    OVERLAP_OFFSET_TOLERANCE,
    collinear_overlaps,
    insert_instance_count,
    pipe_geometry_in_blocks,
)

LENGTH_TOLERANCE = 1e-6
FLATTEN_DISTANCE = 0.5
EQUIPMENT_TAG_LAYER = "Марки оборудования"
DIAMETER_LIKE_RE = re.compile(r"%%[cC]|[ДдDd][уУuU]\s*\d|⌀|\b[dD]\s*\d")
TOP_TEXTS = 20


@dataclass
class _Context:
    doc: Any
    factor: float | None
    report: dict
    entities: list
    kept: dict[str, list]
    removed: dict[str, list]

    def kept_entities(self):
        for layer in sorted(self.kept):
            yield from self.kept[layer]


def _amount(factor: float | None, count: int, length_du: float) -> dict[str, Any]:
    return {
        "count": int(count),
        "length_du": round(length_du, 6),
        "length_m": None if factor is None else round(length_du * factor, 6),
    }


def _length(entity) -> float:
    return measure_entity(entity)[0]


def _selection(entities, factor, remove_duplicates):
    """Reproduce the takeoff's pipe selection: included pipe layers, measured types, per-layer duplicate removal."""

    by_layer: dict[str, list] = defaultdict(list)
    for entity in entities:
        layer = app._dxf_layer_name(entity)
        if not app._is_dxf_pipe_layer(layer):
            continue
        raw_length, measurable, ignored = measure_entity(entity)
        if not measurable or ignored:
            continue
        converted = app.convert_length(raw_length, factor)
        if not math.isfinite(converted) or converted < 0:
            continue
        by_layer[layer].append(entity)

    kept, removed = {}, {}
    for layer, items in by_layer.items():
        if remove_duplicates:
            kept[layer], removed[layer] = deduplicate_entities(items)
        else:
            kept[layer], removed[layer] = items, []
    return kept, removed


def _polyline_xyb(entity):
    return _lwpolyline_points(entity) if entity.dxftype() == "LWPOLYLINE" else _polyline_points(entity)


def _is_closed(entity) -> bool:
    return bool(entity.closed) if entity.dxftype() == "LWPOLYLINE" else bool(entity.is_closed)


def _is_mesh(entity) -> bool:
    return entity.dxftype() == "POLYLINE" and (entity.is_poly_face_mesh or entity.is_polygon_mesh)


# --- KI-3D --------------------------------------------------------------------------------------


def _three_d(ctx: _Context) -> dict[str, Any]:
    line_count, line_missing = 0, 0.0
    poly_count, poly_missing = 0, 0.0
    mesh_count, mesh_length = 0, 0.0
    circle_count, circle_length = 0, 0.0
    for entity in ctx.kept_entities():
        kind = entity.dxftype()
        if kind == "LINE":
            start, end = Vec3(entity.dxf.start), Vec3(entity.dxf.end)
            if abs(end.z - start.z) > LENGTH_TOLERANCE:
                line_count += 1
                line_missing += start.distance(end) - math.hypot(end.x - start.x, end.y - start.y)
        elif kind == "POLYLINE":
            if _is_mesh(entity):
                mesh_count += 1
                mesh_length += _length(entity)
            elif entity.is_3d_polyline:
                points = [Vec3(vertex.dxf.location) for vertex in entity.vertices]
                if entity.is_closed and len(points) > 1:
                    points.append(points[0])
                length_3d = sum(a.distance(b) for a, b in zip(points, points[1:]))
                missing = length_3d - _length(entity)
                if missing > LENGTH_TOLERANCE:
                    poly_count += 1
                    poly_missing += missing
        elif kind == "ARC":
            sweep = (float(entity.dxf.end_angle) - float(entity.dxf.start_angle)) % 360.0
            if math.isclose(sweep, 0.0, abs_tol=1e-9) or math.isclose(sweep, 360.0, abs_tol=1e-9):
                circle_count += 1
                circle_length += _length(entity)
    return {
        "lines_with_z_difference_missing_length": _amount(ctx.factor, line_count, line_missing),
        "3d_polylines_missing_length": _amount(ctx.factor, poly_count, poly_missing),
        "mesh_polylines_measured_as_pipe": _amount(ctx.factor, mesh_count, mesh_length),
        "full_circle_arcs_counted_as_pipe": _amount(ctx.factor, circle_count, circle_length),
        "note": "Vertical runs drawn only as riser/drop symbols have no measurable length in plan geometry.",
    }


# --- KI-DUP -------------------------------------------------------------------------------------


def _segment_bulges(entity) -> list[float]:
    points = _polyline_xyb(entity)
    bulges = [round(point[2], 9) for point in points[:-1]]
    if _is_closed(entity) and len(points) > 1:
        bulges.append(round(points[-1][2], 9))
    return bulges


def _same_bulges(first, second) -> bool:
    forward, other = _segment_bulges(first), _segment_bulges(second)
    if forward == other:
        return True
    if _is_closed(second) and other:
        reversed_other = [-value for value in reversed(other[:-1])] + [-other[-1]]
    else:
        reversed_other = [-value for value in reversed(other)]
    return forward == reversed_other


def _duplicates(ctx: _Context) -> dict[str, Any]:
    bulge_count, bulge_length = 0, 0.0
    for layer, kept in ctx.kept.items():
        first_by_signature = {}
        for entity in kept:
            signature = entity_geometry_signature(entity)
            if signature is not None:
                first_by_signature.setdefault(signature, entity)
        for duplicate in ctx.removed.get(layer, []):
            if duplicate.dxftype() not in {"LWPOLYLINE", "POLYLINE"}:
                continue
            original = first_by_signature.get(entity_geometry_signature(duplicate))
            if original is not None and not _same_bulges(original, duplicate):
                bulge_count += 1
                bulge_length += _length(duplicate)

    overlaps = collinear_overlaps(ctx.kept)

    by_signature: dict[tuple, list] = defaultdict(list)
    for entity in ctx.kept_entities():
        signature = entity_geometry_signature(entity)
        if signature is not None:
            by_signature[signature].append(entity)
    exact_count, exact_length = 0, 0.0
    for entities in by_signature.values():
        for extra in entities[1:]:
            exact_count += 1
            exact_length += _length(extra)

    summary = ctx.report["summary"]
    return {
        "app_removed_exact_duplicates_same_layer": {
            "count": int(summary["duplicate_entity_count"]),
            "length_m_or_du": round(float(summary["duplicate_raw_length"]), 6),
        },
        "removed_polylines_with_different_bulges": _amount(ctx.factor, bulge_count, bulge_length),
        "collinear_overlap_same_layer": _amount(ctx.factor, overlaps.same_layer_segments, overlaps.same_layer_length),
        "same_layer_overlap_groups_mixing_line_and_polyline": overlaps.mixed_type_groups,
        "collinear_overlap_across_layers": _amount(ctx.factor, overlaps.across_layers_groups, overlaps.across_layers_length),
        "exact_duplicates_across_layers": _amount(ctx.factor, exact_count, exact_length),
        "tolerances": {"angle_rad": OVERLAP_ANGLE_TOLERANCE, "offset_du": OVERLAP_OFFSET_TOLERANCE},
    }


# --- KI-DIA -------------------------------------------------------------------------------------


def _wcs_points(entity) -> list[tuple[float, float]]:
    try:
        return [(float(v.x), float(v.y)) for v in ezdxf_path.make_path(entity).flattening(FLATTEN_DISTANCE)]
    except Exception:
        return []


def _point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
    return math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))


def _distance_to_points(point, points) -> float:
    if not points:
        return math.inf
    if len(points) == 1:
        return math.hypot(point[0] - points[0][0], point[1] - points[0][1])
    return min(_point_segment_distance(point, a, b) for a, b in zip(points, points[1:]))


def _diameters(ctx: _Context) -> dict[str, Any]:
    symbols: Counter = Counter()
    unparsed_like: Counter = Counter()
    unparsed_other: Counter = Counter()
    outside: Counter = Counter()
    for entity in ctx.entities:
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        text = app._dxf_text_value(entity)
        label = app._normalize_dxf_diameter_label(text)
        layer = app._dxf_layer_name(entity)
        if layer == app.DXF_DIAMETER_LAYER:
            if label:
                symbols["OD (Ø/ø)" if label.startswith("Ø") else "DN"] += 1
            elif DIAMETER_LIKE_RE.search(text):
                unparsed_like[text[:40]] += 1
            else:
                unparsed_other[text[:40]] += 1
        elif label:
            outside[layer] += 1

    markers = app._dxf_diameter_markers(ctx.entities)
    base_threshold = app._marker_settings(ctx.factor)[0]
    unknown_handles = {row["Handle"] for row in ctx.report["pipe_detail_rows"] if row["Diameter"] == "UNKNOWN"}
    unknown_count, unknown_length = 0, 0.0
    candidate_count, candidate_length, ambiguous = 0, 0.0, 0
    for handle in sorted(unknown_handles):
        entity = ctx.doc.entitydb.get(handle)
        if entity is None:
            continue
        length = _length(entity)
        unknown_count += 1
        unknown_length += length
        points = _wcs_points(entity)
        labels = {
            marker["label"]
            for marker in markers
            if _distance_to_points(marker["point"], points) <= max(base_threshold, float(marker.get("height") or 0.0) * 8.0)
        }
        if labels:
            candidate_count += 1
            candidate_length += length
            if len(labels) > 1:
                ambiguous += 1

    ocs_handles = [
        entity.dxf.handle
        for entity in ctx.kept_entities()
        if entity.dxftype() in {"ARC", "LWPOLYLINE", "POLYLINE"}
        and not Vec3(entity.dxf.get("extrusion", (0, 0, 1))).isclose(Vec3(0, 0, 1))
    ]
    return {
        "marker_symbols": dict(symbols),
        "unparsed_diameter_like_texts": dict(unparsed_like.most_common(TOP_TEXTS)),
        "unparsed_other_texts_count": int(sum(unparsed_other.values())),
        "unparsed_other_examples": dict(unparsed_other.most_common(10)),
        "diameter_labels_outside_marker_layer": dict(outside),
        "unknown_diameter": _amount(ctx.factor, unknown_count, unknown_length),
        "unknown_with_marker_near_geometry": _amount(ctx.factor, candidate_count, candidate_length),
        "ambiguous_candidates": ambiguous,
        "mirrored_or_tilted_ocs_entities": {
            "count": len(ocs_handles),
            "unknown": sum(1 for handle in ocs_handles if handle in unknown_handles),
        },
        "marker_threshold_m": None if ctx.factor is None else round(base_threshold * ctx.factor, 6),
    }


# --- KI-BLK -------------------------------------------------------------------------------------


def _blocks(ctx: _Context) -> dict[str, Any]:
    minsert_instances: Counter = Counter()
    valve_dropped: Counter = Counter()
    anonymous: Counter = Counter()
    not_counted: Counter = Counter()
    tag_inserts = 0
    for insert in ctx.doc.modelspace().query("INSERT"):
        layer = app._dxf_layer_name(insert)
        name = str(insert.dxf.name)
        classification = app._classify_dxf_insert(insert)
        label = "not counted" if classification is None else "/".join(classification)
        mcount = insert_instance_count(insert)
        if mcount > 1:
            minsert_instances[label] += mcount
        if layer == EQUIPMENT_TAG_LAYER:
            tag_inserts += 1
        if layer in app.DXF_VALVE_LAYERS and classification is None:
            valve_dropped[name] += 1
        if classification is None:
            not_counted[layer] += 1
        if name.startswith("*"):
            anonymous[f"{layer} -> {label}"] += 1

    blocks = pipe_geometry_in_blocks(ctx.doc, is_pipe_layer=app._is_dxf_pipe_layer, layer_of=app._dxf_layer_name, measure=measure_entity)
    hidden_count, hidden_length = blocks["entity_count"], blocks["length_du"]
    hidden_unsupported, failures = blocks["unsupported"], blocks["failures"]
    inserts_with_pipe = sum(row["Inserts"] for row in blocks["rows"])

    return {
        "pipe_geometry_inside_blocks_not_measured": _amount(ctx.factor, hidden_count, hidden_length),
        "inserts_containing_pipe_geometry": inserts_with_pipe,
        "unsupported_entities_inside_blocks_on_pipe_layers": hidden_unsupported,
        "block_expansion_failures": failures,
        "minsert_instances": dict(minsert_instances),
        "equipment_tag_layer_inserts_counted_as_equipment": tag_inserts,
        "valve_layer_inserts_dropped": dict(valve_dropped),
        "inserts_not_counted_by_layer": dict(not_counted),
        "anonymous_block_inserts": dict(anonymous),
    }


# --- KI-LAYER -----------------------------------------------------------------------------------


def _layers(ctx: _Context) -> dict[str, Any]:
    prefix = app.DXF_PIPE_LAYER_PREFIX
    table = {str(layer.dxf.name): layer for layer in ctx.doc.layers}
    measured: dict[str, list] = defaultdict(lambda: [0, 0.0])
    names = set(table)
    for entity in ctx.entities:
        layer = app._dxf_layer_name(entity)
        names.add(layer)
        raw_length, measurable, ignored = measure_entity(entity)
        if measurable and not ignored:
            measured[layer][0] += 1
            measured[layer][1] += raw_length

    flagged = []
    pipe_like_layers = []
    for name in sorted(names):
        folded = name.casefold()
        if not (folded.startswith(prefix.casefold()) or ("|" in name and prefix.casefold() in folded)):
            continue
        included = app._is_dxf_pipe_layer(name)
        entry = table.get(name)
        frozen_or_off = bool(entry is not None and (entry.is_frozen() or entry.is_off()))
        count, length = measured.get(name, [0, 0.0])
        pipe_like_layers.append({"layer": name, "included": included, **_amount(ctx.factor, count, length)})
        issues = []
        if included and "осев" in folded:
            issues.append("centreline-like name but included")
        if included and frozen_or_off:
            issues.append("frozen or off but included")
        if not included and not name.startswith(prefix) and folded.startswith(prefix.casefold()):
            issues.append("prefix case variant not included")
        if not included and "|" in name:
            issues.append("xref-dependent layer not included")
        for issue in issues:
            flagged.append({"layer": name, "issue": issue, **_amount(ctx.factor, count, length)})
    return {"pipe_like_layers": pipe_like_layers, "flagged": flagged}


# --- KI-POL -------------------------------------------------------------------------------------


def _closed_polylines(ctx: _Context) -> dict[str, Any]:
    count, length = 0, 0.0
    by_layer: Counter = Counter()
    for entity in ctx.kept_entities():
        if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"} and not _is_mesh(entity) and _is_closed(entity):
            count += 1
            length += _length(entity)
            by_layer[app._dxf_layer_name(entity)] += 1
    return {"closed_polylines_counted_as_pipe": _amount(ctx.factor, count, length), "by_layer": dict(by_layer)}


# --- entry points -------------------------------------------------------------------------------


def analyse(doc, meters_per_unit: float | None = None, *, remove_duplicates: bool = True, use_header_units: bool = True) -> dict[str, Any]:
    factor = app.read_insunits(doc)["meters_per_unit"] if (meters_per_unit is None and use_header_units) else meters_per_unit
    report = app.calculate_dxf_quantities(doc, "m", factor, remove_duplicates)
    entities = list(doc.modelspace())
    kept, removed = _selection(entities, factor, remove_duplicates)
    ctx = _Context(doc=doc, factor=factor, report=report, entities=entities, kept=kept, removed=removed)
    selected = sum(len(items) for items in kept.values())
    unknown_length = sum(float(row["Length (m)"]) for row in report["pipe_rows"] if row["Diameter"] == "UNKNOWN")
    return {
        "drawing": {
            "meters_per_unit": factor,
            "length_unit": report["summary"].get("length_unit"),
            "app_total_pipe_length": round(report["summary"]["total_pipe_length"], 6),
            "app_pipe_entity_count": report["summary"]["pipe_entity_count"],
            "analysis_selection_count": selected,
            "selection_matches_app": selected == report["summary"]["pipe_entity_count"],
            "app_unknown_diameter_length": round(unknown_length, 6),
        },
        "KI-3D": _three_d(ctx),
        "KI-DUP": _duplicates(ctx),
        "KI-DIA": _diameters(ctx),
        "KI-BLK": _blocks(ctx),
        "KI-LAYER": _layers(ctx),
        "KI-POL": _closed_polylines(ctx),
    }


def _format(value: Any) -> str:
    if isinstance(value, dict) and {"count", "length_du", "length_m"} <= set(value):
        metres = "n/a (units unknown)" if value["length_m"] is None else f"{value['length_m']} m"
        return f"count {value['count']}, length {metres} ({value['length_du']} drawing units)"
    return json.dumps(value, ensure_ascii=False)


def to_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Known-issue impact analysis",
        "",
        "Read-only. The current V0 takeoff ran unchanged; no quantity rule was modified.",
        "",
    ]
    for section, content in result.items():
        lines.append(f"## {section}")
        lines.append("")
        for key, value in content.items():
            if isinstance(value, list):
                lines.append(f"- {key}:")
                lines.extend(f"  - {_format(item)}" for item in value)
            else:
                lines.append(f"- {key}: {_format(value)}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only impact analysis of known takeoff issues on a DXF drawing.")
    parser.add_argument("dxf", type=Path, help="DXF drawing (opened read-only)")
    parser.add_argument("--output", type=Path, help="Markdown report path; a .json file is written next to it. Existing files are never overwritten.")
    parser.add_argument("--no-dedup", action="store_true", help="Analyse with duplicate removal switched off")
    args = parser.parse_args(argv)

    if args.output is not None:
        targets = [args.output, args.output.with_suffix(".json")]
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            print(f"Refusing to overwrite existing file(s): {', '.join(existing)}", file=sys.stderr)
            return 2

    doc = app.open_dxf(args.dxf)
    result = analyse(doc, remove_duplicates=not args.no_dedup)
    markdown = to_markdown(result)

    if args.output is None:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.stdout.write(markdown)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as handle:
        handle.write(markdown)
    with open(args.output.with_suffix(".json"), "x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(f"Wrote {args.output} and {args.output.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
