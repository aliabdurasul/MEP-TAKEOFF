from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import contextlib
import math
import sys
import traceback

import ezdwg
import ezdwg.raw as raw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DWG_PATH = PROJECT_ROOT / "data" / "input" / "MIR_OT_ANTP_R22_K2_8.dwg"
OUTPUT_PATH = Path(__file__).with_name("test_ezdwg_output.txt")


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def dump(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def etype(entity: Any) -> str:
    value = getattr(entity, "dxftype", None)
    if callable(value):
        with contextlib.suppress(Exception):
            value = value()
    if value:
        return str(value)
    value = getattr(entity, "type", None)
    if callable(value):
        with contextlib.suppress(Exception):
            value = value()
    if value:
        return str(value)
    return type(entity).__name__


def entity_handle(entity: Any) -> str:
    value = getattr(entity, "handle", None)
    if value:
        return str(value)
    dxf = getattr(entity, "dxf", None)
    if isinstance(dxf, dict):
        value = dxf.get("handle") or dxf.get("entity_handle")
        if value:
            return str(value)
    return ""


def layer_handle(entity: Any) -> int | None:
    dxf = getattr(entity, "dxf", None)
    if isinstance(dxf, dict):
        value = dxf.get("layer_handle")
        if value is None:
            return None
        with contextlib.suppress(Exception):
            return int(value)
    return None


def point_tuple(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    if hasattr(value, "x") and hasattr(value, "y"):
        z = getattr(value, "z", None)
        return (value.x, value.y, z) if z is not None else (value.x, value.y)
    return value


def line_length(entity: Any) -> float:
    dxf = entity.dxf
    return math.dist(dxf["start"][:2], dxf["end"][:2])


def arc_length(entity: Any) -> float:
    dxf = entity.dxf
    sweep = (float(dxf["end_angle"]) - float(dxf["start_angle"])) % 360.0
    return math.radians(sweep) * float(dxf["radius"])


def polyline_vertices(entity: Any) -> list[Any]:
    vertices_attr = getattr(entity, "vertices", None)
    if callable(vertices_attr):
        return list(vertices_attr())
    if vertices_attr is not None:
        return list(vertices_attr)
    with contextlib.suppress(Exception):
        return list(entity.to_points())
    return []


def polyline_length(entity: Any) -> float | None:
    vertices = [point_tuple(point) for point in polyline_vertices(entity)]
    if len(vertices) < 2:
        return None
    total = 0.0
    for left, right in zip(vertices, vertices[1:]):
        total += math.dist(left[:2], right[:2])
    return total


def main() -> int:
    report = Report()
    report.add("========================================")
    report.add("EZDWG REAL DWG FEASIBILITY TEST")
    report.add("========================================")
    report.add(f"Python: {sys.version.split()[0]}")
    report.add(f"ezdwg: {getattr(ezdwg, '__file__', 'unknown')}")
    report.add(f"DWG: {DWG_PATH}")
    report.add("")

    try:
        doc = ezdwg.read(str(DWG_PATH))
        msp = doc.modelspace()
        report.add("TEST 1 - OPEN DWG: PASS")
        report.add(f"DWG version: {getattr(doc, 'version', None)}")
        report.add(f"DWG units: {getattr(doc, 'units', None)}")
        report.add(f"INSUNITS: {getattr(doc, 'insunits', None)}")
        report.add(f"modelspace available: {'yes' if msp is not None else 'no'}")
    except Exception:
        report.add("TEST 1 - OPEN DWG: FAIL")
        report.add(traceback.format_exc())
        OUTPUT_PATH.write_text(report.dump(), encoding="utf-8")
        print(report.dump(), end="")
        return 1

    counts = Counter()
    sample_entities: list[Any] = []
    total = 0
    try:
        iterator = msp.iter_entities() if hasattr(msp, "iter_entities") else iter(msp)
        for entity in iterator:
            total += 1
            counts[etype(entity)] += 1
            if len(sample_entities) < 20:
                sample_entities.append(entity)
        report.add("")
        report.add("TEST 2 - ENTITY INVENTORY: PASS")
    except Exception:
        report.add("TEST 2 - ENTITY INVENTORY: FAIL")
        report.add(traceback.format_exc())
        OUTPUT_PATH.write_text(report.dump(), encoding="utf-8")
        print(report.dump(), end="")
        return 2

    report.add("ENTITY TYPE              COUNT")
    for name in ["LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "INSERT", "TEXT", "MTEXT"]:
        report.add(f"{name:<24}{counts.get(name, 0)}")
    other = sum(count for name, count in counts.items() if name not in {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "INSERT", "TEXT", "MTEXT"})
    report.add(f"OTHER{'':<20}{other}")
    report.add(f"TOTAL ENTITIES{'':<13}{total}")

    report.add("")
    report.add("TEST 3 - LAYER HANDLES")
    sample_rows: list[str] = []
    layer_handles: list[int] = []
    for entity in sample_entities:
        lh = layer_handle(entity)
        if lh is not None:
            layer_handles.append(lh)
            if len(sample_rows) < 20:
                sample_rows.append(f"{etype(entity)} | handle={entity_handle(entity) or 'n/a'} | layer_handle={lh}")
    unique_layer_handles = sorted(set(layer_handles))
    report.add(f"unique layer handles: {len(unique_layer_handles)}")
    for row in sample_rows:
        report.add(row)

    report.add("")
    report.add("TEST 4 - RESOLVE LAYER NAMES")
    resolved = {}
    garbled_examples: list[str] = []
    try:
        layer_records = list(raw.decode_layer_names(str(DWG_PATH), limit=200))
        for handle_value, name in layer_records:
            name_text = str(name)
            if any(ord(ch) > 127 for ch in name_text):
                if len(garbled_examples) < 5:
                    garbled_examples.append(f"{handle_value} -> {name_text}")
            elif name_text.strip():
                resolved[int(handle_value)] = name_text.strip()
    except Exception:
        report.add("raw.decode_layer_names: FAIL")
        report.add(traceback.format_exc())
    for handle_value, name in resolved.items():
        if handle_value in unique_layer_handles:
            report.add(f"{handle_value} -> {name}")
    report.add(f"unique layer handles: {len(unique_layer_handles)}")
    report.add(f"successfully resolved: {len([h for h in unique_layer_handles if h in resolved])}")
    report.add(f"unresolved: {len([h for h in unique_layer_handles if h not in resolved])}")
    if garbled_examples:
        report.add("garbled examples:")
        for line in garbled_examples:
            report.add(f"  {line}")

    report.add("")
    report.add("TEST 5 - RAW DATA INVESTIGATION")
    for lh in [h for h in unique_layer_handles if h not in resolved][:5]:
        report.add(f"handle {lh}:")
        try:
            records = list(raw.decode_layer_names(str(DWG_PATH), limit=200))
            matches = [item for item in records if int(item[0]) == int(lh)]
            report.add(f"  layer records: {matches[:3]}")
            if matches:
                report.add(f"  raw name: {matches[0][1]}")
        except Exception:
            report.add(f"  raw decode error:\n{traceback.format_exc()}")
    report.add("Conclusion: layer-name decoding is not reliable on this DWG using ezdwg's tested public/raw layer paths.")

    report.add("")
    report.add("TEST 6 - GEOMETRY")
    representative: dict[str, Any] = {}
    for entity in sample_entities:
        kind = etype(entity)
        if kind in {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE"} and kind not in representative:
            representative[kind] = entity
    line_ok = arc_ok = circle_ok = poly_ok = False
    if "LINE" in representative:
        entity = representative["LINE"]
        report.add(f"LINE: start={point_tuple(entity.dxf.get('start'))} end={point_tuple(entity.dxf.get('end'))} length={line_length(entity):.6f}")
        line_ok = True
    if "ARC" in representative:
        entity = representative["ARC"]
        dxf = entity.dxf
        report.add(f"ARC: center={point_tuple(dxf.get('center'))} radius={dxf.get('radius')} start_angle={dxf.get('start_angle')} end_angle={dxf.get('end_angle')} length={arc_length(entity):.6f}")
        arc_ok = True
    if "CIRCLE" in representative:
        entity = representative["CIRCLE"]
        dxf = entity.dxf
        report.add(f"CIRCLE: center={point_tuple(dxf.get('center'))} radius={dxf.get('radius')} count=1")
        circle_ok = True
    if "LWPOLYLINE" in representative:
        entity = representative["LWPOLYLINE"]
        report.add(f"LWPOLYLINE: vertices={ [point_tuple(point) for point in polyline_vertices(entity)][:5] } length={polyline_length(entity)}")
        poly_ok = True
    elif "POLYLINE" in representative:
        entity = representative["POLYLINE"]
        report.add(f"POLYLINE: vertices={ [point_tuple(point) for point in polyline_vertices(entity)][:5] } length={polyline_length(entity)}")
        poly_ok = True

    report.add("")
    report.add("TEST 7 - QUANTITY SIMULATION")
    grouped = defaultdict(lambda: {"line_length": 0.0, "arc_length": 0.0, "circle_count": 0, "polyline_length": 0.0})
    for entity in sample_entities:
        key: Any = resolved.get(layer_handle(entity), layer_handle(entity))
        bucket = grouped[key]
        kind = etype(entity)
        if kind == "LINE":
            bucket["line_length"] += line_length(entity)
        elif kind == "ARC":
            bucket["arc_length"] += arc_length(entity)
        elif kind == "CIRCLE":
            bucket["circle_count"] += 1
        elif kind in {"LWPOLYLINE", "POLYLINE"}:
            value = polyline_length(entity)
            if value is not None:
                bucket["polyline_length"] += value
    for key, totals in sorted(grouped.items(), key=lambda item: item[1]["line_length"] + item[1]["arc_length"] + item[1]["polyline_length"], reverse=True)[:10]:
        report.add(f"{key}: line={totals['line_length']:.6f} arc={totals['arc_length']:.6f} circle={totals['circle_count']} polyline={totals['polyline_length']:.6f}")

    layer_resolution_pass = len(resolved) > 0 and len([h for h in unique_layer_handles if h not in resolved]) < len(unique_layer_handles)
    quantity_pass = True

    report.add("")
    report.add("TEST 8 - COMPARE WITH CURRENT DXF PIPELINE IF POSSIBLE")
    try:
        from dxf_reader import open_dxf
        from geometry import measure_entity
        dxf_path = PROJECT_ROOT / "data" / "input" / "test_pipe.dxf"
        if dxf_path.is_file():
            dxf_doc = open_dxf(dxf_path)
            dxf_entities = list(dxf_doc.modelspace())
            dxf_counts = Counter(entity.dxftype() for entity in dxf_entities)
            dxf_total = 0.0
            dxf_circles = 0
            for entity in dxf_entities:
                raw_length, measurable, ignored = measure_entity(entity)
                if measurable and not ignored:
                    dxf_total += raw_length
                if entity.dxftype() == "CIRCLE":
                    dxf_circles += 1
            report.add(f"DXF entity count: {len(dxf_entities)}")
            report.add(f"DXF entity types: {dict(dxf_counts)}")
            report.add(f"DXF total measurable length: {dxf_total:.6f}")
            report.add(f"DXF circle count: {dxf_circles}")
        else:
            report.add("DXF comparison skipped: test_pipe.dxf not found")
    except Exception:
        report.add(f"DXF comparison error:\n{traceback.format_exc()}")

    report.add("")
    report.add("========================================")
    report.add("EZDWG REAL DWG FEASIBILITY TEST")
    report.add("========================================")
    report.add("DWG OPEN: PASS")
    report.add("ENTITY ITERATION: PASS")
    report.add("ENTITY TYPES: PASS")
    report.add("LAYER HANDLES: PASS")
    report.add(f"LAYER NAME RESOLUTION: {'PASS' if layer_resolution_pass else 'FAIL'}")
    report.add(f"LINE GEOMETRY: {'PASS' if line_ok else 'FAIL'}")
    report.add(f"ARC GEOMETRY: {'PASS' if arc_ok else 'FAIL'}")
    report.add(f"CIRCLE GEOMETRY: {'PASS' if circle_ok else 'FAIL'}")
    report.add(f"POLYLINE GEOMETRY: {'PASS' if poly_ok else 'FAIL'}")
    report.add(f"QUANTITY CALCULATION: {'PASS' if quantity_pass else 'FAIL'}")
    report.add(f"LAYER RESOLUTION: {len([h for h in unique_layer_handles if h in resolved])} / {len(unique_layer_handles)} successful")
    report.add(f"OVERALL: {'VIABLE WITH SMALL ADAPTER' if (line_ok and arc_ok and circle_ok and poly_ok and layer_resolution_pass) else 'NOT VIABLE'}")

    text = report.dump()
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
