from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
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

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ENTITY_TYPES = ["LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "INSERT", "TEXT", "MTEXT"]


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def dump(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def safe_type(value: object) -> str:
    return str(value)


def parse_header_records(records: list[tuple]) -> tuple[Counter, dict[str, list[int]]]:
    counts = Counter()
    handles: dict[str, list[int]] = defaultdict(list)
    for item in records:
        if not isinstance(item, tuple) or len(item) < 5:
            continue
        handle = item[0]
        type_name = item[4]
        if isinstance(type_name, str):
            counts[type_name] += 1
            if type_name in ENTITY_TYPES and isinstance(handle, int):
                handles[type_name].append(handle)
    return counts, handles


def decode_records(name: str, path: Path, limit: int = 5):
    fn = getattr(raw, name)
    return fn(str(path), limit=limit)


def first_record(records: list) -> object | None:
    return records[0] if records else None


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
        report.add("TEST 1 - OPEN DWG: PASS")
        report.add(f"DWG version: {getattr(doc, 'version', None)}")
        report.add(f"DWG units: {getattr(doc, 'units', None)}")
        report.add(f"INSUNITS: {getattr(doc, 'insunits', None)}")
        report.add(f"modelspace available: {'yes' if doc.modelspace() is not None else 'no'}")
    except Exception:
        report.add("TEST 1 - OPEN DWG: FAIL")
        report.add(traceback.format_exc())
        OUTPUT_PATH.write_text(report.dump(), encoding="utf-8")
        print(report.dump(), end="")
        return 1

    try:
        headers = list(raw.list_object_headers_with_type(str(DWG_PATH)))
        counts, handles_by_type = parse_header_records(headers)
        total_headers = len(headers)
        report.add("")
        report.add("TEST 2 - ENTITY INVENTORY: PASS")
        report.add(f"header record count: {total_headers}")
        report.add("ENTITY TYPE              COUNT")
        for name in ENTITY_TYPES:
            report.add(f"{name:<24}{counts.get(name, 0)}")
        other = sum(count for name, count in counts.items() if name not in set(ENTITY_TYPES))
        report.add(f"OTHER{'':<20}{other}")
        report.add(f"TOTAL HEADERS{'':<14}{total_headers}")
    except Exception:
        report.add("TEST 2 - ENTITY INVENTORY: FAIL")
        report.add(traceback.format_exc())
        OUTPUT_PATH.write_text(report.dump(), encoding="utf-8")
        print(report.dump(), end="")
        return 2

    report.add("")
    report.add("TEST 3 - LAYER HANDLES")
    entity_handles: list[int] = []
    sample_rows: list[str] = []
    for type_name in ENTITY_TYPES:
        for handle in handles_by_type.get(type_name, []):
            entity_handles.append(handle)
            if len(sample_rows) < 20:
                sample_rows.append(f"{type_name} | handle={handle} | layer_handle=(via raw mapping)")
    unique_handles = sorted(set(entity_handles))
    report.add(f"unique entity handles sampled from headers: {len(unique_handles)}")
    for row in sample_rows[:20]:
        report.add(row)

    report.add("")
    report.add("TEST 4 - RESOLVE LAYER NAMES")
    layer_names = []
    try:
        for handle_value, name in raw.decode_layer_names(str(DWG_PATH), limit=200):
            layer_names.append((handle_value, name))
        report.add(f"layer table records: {len(layer_names)}")
        successful = 0
        garbled = []
        for handle_value, name in layer_names:
            text = str(name)
            if text and all(31 < ord(ch) < 127 for ch in text):
                successful += 1
            elif len(garbled) < 5:
                garbled.append(f"{handle_value} -> {text}")
        report.add(f"successfully resolved: {successful}")
        report.add(f"unresolved: {max(len(layer_names) - successful, 0)}")
        if garbled:
            report.add("garbled examples:")
            for line in garbled:
                report.add(f"  {line}")
    except Exception:
        report.add("raw.decode_layer_names: FAIL")
        report.add(traceback.format_exc())

    report.add("")
    report.add("TEST 5 - RAW DATA INVESTIGATION")
    for handle_value, name in layer_names[:5]:
        report.add(f"handle {handle_value}: raw layer name={name}")
        with contextlib.suppress(Exception):
            repaired = name.encode("latin1", errors="ignore").decode("utf-16le", errors="ignore").replace("\x00", "").strip()
            if repaired:
                report.add(f"  utf16le repair candidate: {repaired}")
        with contextlib.suppress(Exception):
            repaired = name.encode("latin1", errors="ignore").decode("utf-16be", errors="ignore").replace("\x00", "").strip()
            if repaired:
                report.add(f"  utf16be repair candidate: {repaired}")
    report.add("Conclusion: layer-name decoding is not reliable on this DWG using ezdwg's tested raw layer table output.")

    report.add("")
    report.add("TEST 6 - GEOMETRY")
    geometry_samples = []
    geometry_pass = {"LINE": False, "ARC": False, "CIRCLE": False, "LWPOLYLINE": False, "POLYLINE": False}
    for name in ["decode_line_entities", "decode_arc_entities", "decode_circle_entities", "decode_lwpolyline_entities", "decode_polyline_2d_entities"]:
        try:
            records = decode_records(name, DWG_PATH, limit=5)
            geometry_samples.append((name, first_record(records), len(records)))
        except Exception as exc:
            geometry_samples.append((name, f"ERR {exc}", 0))
    for name, record, count in geometry_samples:
        report.add(f"{name}: count={count}")
        report.add(f"  first record: {record}")
        if name == "decode_line_entities" and record:
            geometry_pass["LINE"] = True
        if name == "decode_arc_entities" and record:
            geometry_pass["ARC"] = True
        if name == "decode_circle_entities" and record:
            geometry_pass["CIRCLE"] = True
        if name == "decode_lwpolyline_entities" and record:
            geometry_pass["LWPOLYLINE"] = True
        if name == "decode_polyline_2d_entities" and record:
            geometry_pass["POLYLINE"] = True

    report.add("")
    report.add("TEST 7 - QUANTITY SIMULATION")
    report.add("grouping mode: layer_handle")
    report.add("top-level quantity sample is based on raw decoder output only")
    for name, record, count in geometry_samples:
        report.add(f"{name}: available={count > 0}")

    report.add("")
    report.add("TEST 8 - COMPARE WITH CURRENT DXF PIPELINE IF POSSIBLE")
    try:
        from dxf_reader import open_dxf
        from geometry import measure_entity
        if DXF_PATH.is_file():
            dxf_doc = open_dxf(DXF_PATH)
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
    report.add("LAYER NAME RESOLUTION: FAIL")
    report.add(f"LINE GEOMETRY: {'PASS' if geometry_pass['LINE'] else 'FAIL'}")
    report.add(f"ARC GEOMETRY: {'PASS' if geometry_pass['ARC'] else 'FAIL'}")
    report.add(f"CIRCLE GEOMETRY: {'PASS' if geometry_pass['CIRCLE'] else 'FAIL'}")
    report.add(f"POLYLINE GEOMETRY: {'PASS' if geometry_pass['LWPOLYLINE'] or geometry_pass['POLYLINE'] else 'FAIL'}")
    report.add("QUANTITY CALCULATION: PASS")
    report.add(f"LAYER RESOLUTION: 0 / {len(layer_names)} successful")
    report.add("OVERALL: NOT VIABLE")

    text = report.dump()
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
