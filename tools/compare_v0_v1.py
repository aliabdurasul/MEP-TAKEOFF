"""Read-only comparison of the V0 (main) takeoff with V1 on one DXF drawing.

Run only in an authorised local environment; the drawing is never uploaded:

    python tools/compare_v0_v1.py data/input/<drawing>.dxf --git "C:\\Program Files\\Git\\cmd\\git.exe"
    python tools/compare_v0_v1.py data/input/<drawing>.dxf --baseline-dir <dir with main's app.py,
        geometry.py, dxf_reader.py, excel_export.py> --output data/output/v0_v1.md

Both versions read the same drawing object. Every entity-level difference and every
count difference is attributed to a documented V1 rule (docs/V1_BEHAVIOR_CONTRACT.md)
or reported as UNEXPLAINED. Nothing is written unless --output is given, and existing
files are never overwritten.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from dxf_reader import load_dxf  # noqa: E402
from geometry import is_mesh_polyline  # noqa: E402
from mep_takeoff.diagnostics import insert_instance_count, polyline_xyb  # noqa: E402

BASELINE_FILES = ("app.py", "geometry.py", "dxf_reader.py", "excel_export.py")
BASELINE_DEPENDENCIES = ("geometry", "dxf_reader", "excel_export")
UNEXPLAINED = "UNEXPLAINED"
TOLERANCE = 1e-6


def export_baseline(ref: str, directory: Path, git: str = "git") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in BASELINE_FILES:
        content = subprocess.run([git, "-C", str(ROOT), "show", f"{ref}:{name}"], check=True, capture_output=True).stdout
        (directory / name).write_bytes(content)


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_baseline(directory: Path) -> dict[str, Any]:
    """main's app.py bound to main's geometry, dxf_reader and excel_export."""

    loaded = {name: _load(f"v0_{name}", directory / f"{name}.py") for name in BASELINE_DEPENDENCIES}
    saved = {name: sys.modules.get(name) for name in BASELINE_DEPENDENCIES}
    try:
        sys.modules.update(loaded)
        loaded["app"] = _load("v0_app", directory / "app.py")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return loaded


def _v0_label(label: str) -> str:
    return "DN" + label[1:] if label.startswith("Ø") else label


def _v1_only_marker_points(entities, baseline_app) -> list[tuple[float, float]]:
    points = []
    for entity in entities:
        if entity.dxftype() not in {"TEXT", "MTEXT"} or app._dxf_layer_name(entity) != app.DXF_DIAMETER_LAYER:
            continue
        if not app._normalize_dxf_diameter_label(app._dxf_text_value(entity)):
            continue
        if baseline_app._normalize_dxf_diameter_label(baseline_app._dxf_text_value(entity)):
            continue
        point = app._dxf_point_2d(getattr(entity.dxf, "insert", None))
        if point is not None:
            points.append(point)
    return points


def _has_bulge(entity) -> bool:
    return entity.dxftype() in {"LWPOLYLINE", "POLYLINE"} and any(abs(point[2]) > 1e-12 for point in polyline_xyb(entity))


def compare(doc, baseline: dict[str, Any], meters_per_unit: float | None = None, load_info: dict | None = None) -> dict[str, Any]:
    v0_app, v0_geometry = baseline["app"], baseline["geometry"]
    factor = app.read_insunits(doc)["meters_per_unit"] if meters_per_unit is None else meters_per_unit
    old = v0_app.calculate_dxf_quantities(doc, "m", factor)
    new = app.calculate_dxf_quantities(doc, "m", factor, load_info=load_info)
    entities = list(doc.modelspace())
    v1_only_markers = _v1_only_marker_points(entities, v0_app)
    base_threshold = app._marker_settings(factor)[0]
    max_text_height = max((marker["height"] for marker in app._dxf_diameter_markers(entities)), default=0.0)

    old_rows = {row["Handle"]: row for row in old["pipe_detail_rows"]}
    new_rows = {row["Handle"]: row for row in new["pipe_detail_rows"]}
    old_signatures = defaultdict(set)
    for handle in new_rows:
        entity = doc.entitydb.get(handle)
        if entity is not None:
            old_signatures[(app._dxf_layer_name(entity), v0_geometry.entity_geometry_signature(entity))].add(handle)

    differences: list[dict[str, Any]] = []
    notation_renames = 0

    def add(handle, change, old_value, new_value, length_delta, rule, reason):
        differences.append(
            {"Handle": handle, "Change": change, "V0": old_value, "V1": new_value, "Length delta": round(length_delta, 6), "Rule": rule, "Reason": reason}
        )

    for handle in sorted(set(old_rows) | set(new_rows)):
        old_row, new_row = old_rows.get(handle), new_rows.get(handle)
        entity = doc.entitydb.get(handle)
        if old_row is None:
            layer = app._dxf_layer_name(entity)
            twins = old_signatures[(layer, v0_geometry.entity_geometry_signature(entity))] - {handle}
            if twins and (_has_bulge(entity) or any(_has_bulge(doc.entitydb.get(twin)) for twin in twins)):
                add(handle, "now measured", None, new_row["Length (m)"], new_row["Length (m)"], "V1-DUP-01", "V0 removed it as a duplicate although its arcs (bulges) differ")
            else:
                add(handle, "now measured", None, new_row["Length (m)"], new_row["Length (m)"], UNEXPLAINED, "measured by V1 only")
            continue
        if new_row is None:
            if entity is not None and is_mesh_polyline(entity):
                add(handle, "no longer measured", old_row["Length (m)"], None, -old_row["Length (m)"], "V1-ENT-02", "polyface/polygon mesh is not a pipe run")
            else:
                add(handle, "no longer measured", old_row["Length (m)"], None, -old_row["Length (m)"], UNEXPLAINED, "measured by V0 only")
            continue
        if abs(float(old_row["Length (m)"]) - float(new_row["Length (m)"])) > TOLERANCE:
            add(handle, "length", old_row["Length (m)"], new_row["Length (m)"], new_row["Length (m)"] - old_row["Length (m)"], UNEXPLAINED, "length of the same entity changed")
        if new_row["Diameter"] != old_row["Diameter"] and _v0_label(new_row["Diameter"]) == old_row["Diameter"]:
            notation_renames += 1
        elif _v0_label(new_row["Diameter"]) != old_row["Diameter"]:
            reference = new_row.get("Reference Point")
            if entity is not None and not app._has_default_extrusion(entity):
                rule, reason = "V1-DIA-05", "reference point converted from OCS to world coordinates"
            elif reference and any(math.hypot(reference[0] - x, reference[1] - y) <= max(base_threshold, max_text_height * 8.0) for x, y in v1_only_markers):
                rule, reason = "V1-DIA-02", "marker written as %%c, ⌀ or Ду is now recognised"
            elif factor and not math.isclose(base_threshold, app.DXF_MARKER_BASE_THRESHOLD):
                rule, reason = "V1-DIA-04", "marker distance is 3 m converted to drawing units"
            elif max_text_height * 8.0 > app.DXF_MARKER_CELL_SIZE:
                rule, reason = "V1-DIA-04", "marker grid now covers the full search distance of large texts"
            else:
                rule, reason = UNEXPLAINED, "diameter changed"
            add(handle, "diameter", old_row["Diameter"], new_row["Diameter"], 0.0, rule, reason)

    expected_count_change: Counter = Counter()
    for insert in doc.modelspace().query("INSERT"):
        classification = app._classify_dxf_insert(insert)
        if classification is not None:
            expected_count_change[classification[0]] += insert_instance_count(insert) - 1
    count_rows = []
    for category, key in (("EQUIPMENT", "equipment_count"), ("FITTING", "fittings_count"), ("VALVE", "valves_count")):
        delta = int(new["summary"][key]) - int(old["summary"][key])
        rule = "—" if delta == 0 else ("V1-BLK-02" if delta == expected_count_change[category] else UNEXPLAINED)
        count_rows.append({"Category": category, "V0": old["summary"][key], "V1": new["summary"][key], "Delta": delta, "Rule": rule})

    old_by_label: dict[str, float] = defaultdict(float)
    for row in old["pipe_rows"]:
        old_by_label[row["Diameter"]] += float(row["Length (m)"])
    new_by_label: dict[str, float] = defaultdict(float)
    v1_labels: dict[str, set] = defaultdict(set)
    for row in new["pipe_rows"]:
        new_by_label[_v0_label(row["Diameter"])] += float(row["Length (m)"])
        v1_labels[_v0_label(row["Diameter"])].add(row["Diameter"])
    diameter_rows = [
        {
            "V0 label": label,
            "V1 label(s)": ", ".join(sorted(v1_labels.get(label, set()))) or "—",
            "V0 length": round(old_by_label.get(label, 0.0), 6),
            "V1 length": round(new_by_label.get(label, 0.0), 6),
            "Delta": round(new_by_label.get(label, 0.0) - old_by_label.get(label, 0.0), 6),
        }
        for label in sorted(set(old_by_label) | set(new_by_label), key=app._diameter_sort_key)
    ]

    old_total, new_total = float(old["summary"]["total_pipe_length"]), float(new["summary"]["total_pipe_length"])
    entity_delta = math.fsum(row["Length delta"] for row in differences)
    unexplained = [row for row in differences if row["Rule"] == UNEXPLAINED] + [row for row in count_rows if row["Rule"] == UNEXPLAINED]
    total_reconciled = math.isclose(new_total - old_total, entity_delta, abs_tol=1e-5)
    return {
        "drawing": {
            "meters_per_unit": factor,
            "load_mode": (load_info or {}).get("mode", "strict"),
            "v0_total": round(old_total, 6),
            "v1_total": round(new_total, 6),
            "total_delta": round(new_total - old_total, 6),
            "total_reconciled_with_entity_differences": total_reconciled,
        },
        "duplicates": {
            "v0_removed": old["summary"]["duplicate_entity_count"],
            "v1_removed": new["summary"]["duplicate_entity_count"],
            "v0_removed_length": round(float(old["summary"]["duplicate_raw_length"]), 6),
            "v1_removed_length": round(float(new["summary"]["duplicate_raw_length"]), 6),
        },
        "diameters": diameter_rows,
        "notation": {
            "outside_diameter_rows": sum(1 for row in new["pipe_detail_rows"] if row["Diameter Type"] == "OUTSIDE_DIAMETER"),
            "nominal_dn_rows": sum(1 for row in new["pipe_detail_rows"] if row["Diameter Type"] == "NOMINAL_DN"),
            "label_renamed_only": notation_renames,
        },
        "unknown_and_review": {
            "v0_unknown_length": round(old_by_label.get("UNKNOWN", 0.0), 6),
            "v1_unknown_length": round(float(new["summary"]["unknown_diameter_length"]), 6),
            "v1_candidate_length": round(float(new["summary"]["diameter_candidate_length"]), 6),
            "v1_review_length": round(float(new["summary"]["ambiguous_pipe_length"]), 6),
            "v1_total_3d": round(float(new["summary"]["total_pipe_length_3d"]), 6),
        },
        "counts": count_rows,
        "entity_differences": differences,
        "v1_visibility": {
            "warnings": [{"Code": w["Code"], "Count": w["Count"], "Length": w["Length"]} for w in new["warnings"]],
            "unsupported_pipe_entities": new["summary"]["unsupported_pipe_entity_count"],
            "pipe_geometry_in_blocks_length": round(float(new["summary"]["pipe_geometry_in_blocks_length"]), 6),
            "xrefs": [row["Name"] for row in new["xrefs"]],
            "unrecognized_inserts": new["summary"]["unrecognized_insert_count"],
        },
        "verdict": {
            "unexplained": len(unexplained),
            "status": "ALL DIFFERENCES EXPLAINED" if not unexplained and total_reconciled else "UNEXPLAINED DIFFERENCES — DO NOT ACCEPT",
        },
    }


def _table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["(none)"]
    headers = list(rows[0])
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(row[key]) for key in headers) + " |" for row in rows]
    return lines


def to_markdown(result: dict[str, Any]) -> str:
    lines = ["# V0 → V1 comparison", "", "Read-only. Lengths in metres (or drawing units if units are unknown).", ""]
    for section in ("drawing", "duplicates", "notation", "unknown_and_review", "v1_visibility", "verdict"):
        lines += [f"## {section}", ""] + [f"- {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in result[section].items()] + [""]
    for section in ("diameters", "counts", "entity_differences"):
        lines += [f"## {section}", ""] + _table(result[section]) + [""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only V0 (main) versus V1 takeoff comparison on a DXF drawing.")
    parser.add_argument("dxf", type=Path)
    parser.add_argument("--baseline-dir", type=Path, help="Directory with main's app.py, geometry.py, dxf_reader.py, excel_export.py")
    parser.add_argument("--baseline-ref", default="main", help="Git ref exported when --baseline-dir is not given")
    parser.add_argument("--git", default="git", help="git executable used to export the baseline")
    parser.add_argument("--output", type=Path, help="Markdown report; a .json file is written next to it. Never overwritten.")
    args = parser.parse_args(argv)

    if args.output is not None:
        existing = [str(path) for path in (args.output, args.output.with_suffix(".json")) if path.exists()]
        if existing:
            print(f"Refusing to overwrite existing file(s): {', '.join(existing)}", file=sys.stderr)
            return 2

    with tempfile.TemporaryDirectory(prefix="mep_v0_") as temporary:
        directory = args.baseline_dir
        if directory is None:
            directory = Path(temporary)
            export_baseline(args.baseline_ref, directory, args.git)
        baseline = load_baseline(directory)
        doc, load_info = load_dxf(args.dxf)
        result = compare(doc, baseline, load_info=load_info)

    markdown = to_markdown(result)
    if args.output is None:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.stdout.write(markdown)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "x", encoding="utf-8") as handle:
            handle.write(markdown)
        with open(args.output.with_suffix(".json"), "x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, default=str)
        print(f"Wrote {args.output} and {args.output.with_suffix('.json')}")
    return 0 if result["verdict"]["unexplained"] == 0 and result["drawing"]["total_reconciled_with_entity_differences"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
