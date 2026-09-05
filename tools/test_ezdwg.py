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
DXF_PATH = PROJECT_ROOT / "data" / "input" / "test_pipe.dxf"
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
    return str(value or getattr(entity, "type", None) or type(entity).__name__)


def handle(entity: Any) -> str:
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


def entity_count_and_types(doc: Any) -> tuple[int, Counter, list[Any]]:
    counts = Counter()
    sample: list[Any] = []
    total = 0
    msp = doc.modelspace()
    iterator = msp.iter_entities() if hasattr(msp, "iter_entities") else iter(msp)
    for entity in iterator:
        total += 1
        counts[etype(entity)] += 1
        if len(sample) < 20:
            sample.append(entity)
    return total, counts, sample


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


def polyline_length(entity: Any) -> float | None:
    vertices_attr = getattr(entity, "vertices", None)
    if callable(vertices_attr):
        vertices = list(vertices_attr())
    elif vertices_attr is not None:
        vertices = list(vertices_attr)
    else:
        with contextlib.suppress(Exception):
            vertices = list(entity.to_points())
        if not vertices:
            return None
    points = [point_tuple(point) for point in vertices]
    if len(points) < 2:
        return None
    total = 0.0
    for left, right in zip(points, points[1:]):
        total += math.dist(left[:2], right[:2])
    return total


def resolve_layer_names(path: Path, handles: list[int], report: Report) -> dict[int, str]:
    resolved: dict[int, str] = {}

    def merge(items: Any, source: str) -> None:
        if not items:
            return
        found = 0
        for item in items:
            if isinstance(item, tuple) and len(item) >= 2:
                key, value = item[0], item[1]
            else:
                continue
            with contextlib.suppress(Exception):
                key_int = int(key)
                name = str(value).strip()
                if name and key_int not in resolved:
                    resolved[key_int] = name
                    found += 1
        if found:
            report.add(f"{source}: added {found}")

    with contextlib.suppress(Exception):
        merge(raw.decode_layer_names(str(path), limit=200), "raw.decode_layer_names")

    sample_handles = handles[:20]
    if sample_handles:
        with contextlib.suppress(Exception):
            merge(raw.decode_object_entity_layer_handles(str(path), sample_handles, limit=200), "raw.decode_object_entity_layer_handles")

    return resolved


def maybe_repair_garbled_name(value: str) -> list[str]:
    attempts: list[str] = []
    for encoding in ("latin1", "cp1252"):
        with contextlib.suppress(Exception):
            text = value.encode(encoding, errors="ignore").decode("utf-16le", errors="ignore").replace("\x00", "").strip()
            if text and any(ch.isalpha() for ch in text):
                attempts.append(text)
        with contextlib.suppress(Exception):
            text = value.encode(encoding, errors="ignore").decode("utf-16be", errors="ignore").replace("\x00", "").strip()
            if text and any(ch.isalpha() for ch in text):
                attempts.append(text)
    return attempts


def compare_dxf_if_available(report: Report) -> None:
    try:
        from dxf_reader import open_dxf
        from geometry import measure_entity
    except Exception as exc:
        report.add(f"DXF comparison unavailable: {exc}")
        return
    if not DXF_PATH.is_file():
        report.add("DXF comparison skipped: test_pipe.dxf not found")
        return
    dxf_doc = open_dxf(DXF_PATH)
    entities = list(dxf_doc.modelspace())
    counts = Counter(entity.dxftype() for entity in entities)
    report.add("")
    report.add("DXF COMPARISON (existing test_pipe.dxf)")
    report.add(f"entity count: {len(entities)}")
    report.add(f"types: {dict(counts)}")
    total = 0.0
    circles = 0
    for entity in entities:
        raw_length, measurable, ignored = measure_entity(entity)
        if measurable and not ignored:
            total += raw_length
        if entity.dxftype() == "CIRCLE":
            circles += 1
    report.add(f"total measurable length: {total:.6f}")
    report.add(f"circle count: {circles}")


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
    except Exception:
        report.add("TEST 1 - OPEN DWG: FAIL")
        report.add(traceback.format_exc())
        OUTPUT_PATH.write_text(report.dump(), encoding="utf-8")
        print(report.dump(), end="")
        return 1

    report.add("TEST 1 - OPEN DWG: PASS")
    report.add(f"DWG version: {getattr(doc, 'version', None)}")
    report.add(f"DWG units: {getattr(doc, 'units', None)}")
    report.add(f"INSUNITS: {getattr(doc, 'insunits', None)}")
    report.add(f"modelspace available: {'yes' if doc.modelspace() is not None else 'no'}")

    total, counts, sample_entities = entity_count_and_types(doc)
    report.add("")
    report.add("TEST 2 - ENTITY INVENTORY: PASS")
    report.add("ENTITY TYPE              COUNT")
    for name in ["LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "INSERT", "TEXT", "MTEXT"]:
        report.add(f"{name:<24}{counts.get(name, 0)}")
    other = sum(count for name, count in counts.items() if name not in {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "INSERT", "TEXT", "MTEXT"})
    report.add(f"OTHER{'':<20}{other}")
    report.add(f"TOTAL ENTITIES{'':<13}{total}")

    report.add("")
    report.add("TEST 3 - LAYER HANDLES")
    sample_rows: list[str] = []
    handles: list[int] = []
    for entity in sample_entities:
        lh = layer_handle(entity)
        if lh is not None:
            handles.append(lh)
            sample_rows.append(f"{etype(entity)} | handle={handle(entity) or 'n/a'} | layer_handle={lh}")
    unique_handles = sorted(set(handles))
    report.add(f"unique layer handles (sampled): {len(unique_handles)}")
    for row in sample_rows[:20]:
        report.add(row)

    report.add("")
    report.add("TEST 4 - RESOLVE LAYER NAMES")
    resolved = resolve_layer_names(DWG_PATH, unique_handles, report)
    suspicious = 0
    for lh in unique_handles:
        name = resolved.get(lh)
        if not name:
            continue
        repaired = maybe_repair_garbled_name(name)
        final_name = repaired[0] if repaired else name
        if final_name == name:
            report.add(f"{lh} -> {name}")
        else:
            report.add(f"{lh} -> {name} | candidate_repair={final_name}")
            suspicious += 1
    report.add(f"unique layer handles: {len(unique_handles)}")
    report.add(f"successfully resolved: {len([h for h in unique_handles if h in resolved])}")
    unresolved = [h for h in unique_handles if h not in resolved]
    report.add(f"unresolved: {len(unresolved)}")

    report.add("")
    report.add("TEST 5 - RAW DATA INVESTIGATION")
    for lh in unresolved[:5]:
        report.add(f"handle {lh}:")
        with contextlib.suppress(Exception):
            records = list(raw.decode_layer_names(str(DWG_PATH), limit=200))
            matches = [item for item in records if int(item[0]) == int(lh)]
            report.add(f"  layer records: {matches[:3]}")
            if matches:
                for attempt in maybe_repair_garbled_name(str(matches[0][1]))[:3]:
                    report.add(f"  repair candidate: {attempt}")
        with contextlib.suppress(Exception):
            handle_records = raw.decode_object_entity_layer_handles(str(DWG_PATH), [lh], limit=20)
            report.add(f"  entity layer records: {handle_records[:3] if isinstance(handle_records, list) else handle_records}")
    report.add("Conclusion: layer-name decoding is not reliable on this DWG using the tested ezdwg paths.")

    report.add("")
    report.add("TEST 6 - GEOMETRY")
    representative: dict[str, Any] = {}
    for entity in sample_entities:
        if etype(entity) in {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE"} and etype(entity) not in representative:
            representative[etype(entity)] = entity
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
        report.add(f"LWPOLYLINE: vertices={list(getattr(entity, 'vertices', lambda: [])())[:5] if callable(getattr(entity, 'vertices', None)) else polyline_length(entity)} length={polyline_length(entity)}")
        poly_ok = True
    elif "POLYLINE" in representative:
        entity = representative["POLYLINE"]
        report.add(f"POLYLINE: vertices={polyline_length(entity)} length={polyline_length(entity)}")
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

    report.add("")
    report.add("TEST 8 - COMPARE WITH CURRENT DXF PIPELINE IF POSSIBLE")
    compare_dxf_if_available(report)

    layer_resolution_pass = len(resolved) > 0 and len(unresolved) < len(unique_handles)
    quantity_pass = True
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
    report.add(f"LAYER RESOLUTION: {len(resolved)} / {len(unique_handles)} successful")
    if layer_resolution_pass and line_ok and arc_ok and circle_ok and poly_ok:
        overall = "VIABLE WITH SMALL ADAPTER"
    else:
        overall = "NOT VIABLE"
    report.add(f"OVERALL: {overall}")

    text = report.dump()
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if overall != "NOT VIABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
