"""Read-only per-layer diagnosis of a DXF: what is measured as geometry vs. what is counted as pipe.

    .venv\\Scripts\\python.exe tools\\diagnose_dxf.py <drawing.dxf> [--out data\\diagnostics\\report.md]

Runs locally, never modifies the drawing or the calculation. The report contains layer names
from the drawing, so keep it under data/ (git-ignored).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from dxf_reader import load_dxf, read_insunits  # noqa: E402
from geometry import measure_entity  # noqa: E402

PIPE_HINTS = ("pipe", "трубы", "труб", "boru", "p-pipe")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _layer_table(doc) -> dict:
    return {str(layer.dxf.name): layer for layer in doc.layers}


def diagnose(path: Path) -> str:
    doc, load_info = load_dxf(path)
    insunits = read_insunits(doc)
    header = doc.header
    entities = list(doc.modelspace())
    layers = _layer_table(doc)

    types: dict[str, Counter] = defaultdict(Counter)
    measured: dict[str, list] = defaultdict(lambda: [0, 0.0])
    blocks_by_layer: dict[str, Counter] = defaultdict(Counter)
    for entity in entities:
        layer = app._dxf_layer_name(entity)
        types[layer][entity.dxftype()] += 1
        raw_length, measurable, ignored = measure_entity(entity)
        if measurable and not ignored:
            measured[layer][0] += 1
            measured[layer][1] += raw_length
        if entity.dxftype() == "INSERT":
            blocks_by_layer[layer][str(entity.dxf.name)] += 1

    report = app.calculate_dxf_quantities(doc, "Единицы чертежа", insunits["meters_per_unit"], load_info=load_info)
    summary = report["summary"]

    lines = [
        f"# DXF diagnosis: {path.name}",
        "",
        f"- Path: `{path}`",
        f"- Size: {path.stat().st_size} bytes",
        f"- SHA-256: `{_sha256(path)}`",
        f"- Load mode: {load_info['mode']} (fixes {load_info['fixes']}, errors {load_info['errors']})",
        f"- DXF version: {doc.dxfversion}",
        f"- $INSUNITS: {insunits['code']} ({insunits['label']}), meters per unit: {insunits['meters_per_unit']}",
        f"- $MEASUREMENT: {header.get('$MEASUREMENT')}, $LUNITS: {header.get('$LUNITS')}, "
        f"$EXTMIN: {tuple(round(v, 1) for v in header.get('$EXTMIN', (0, 0, 0)))}, "
        f"$EXTMAX: {tuple(round(v, 1) for v in header.get('$EXTMAX', (0, 0, 0)))}",
        f"- Modelspace entities: {len(entities)}",
        "",
        "## Pipe-layer rule in app.py",
        "",
        f"- `_is_dxf_pipe_layer(name)`: name starts with `{app.DXF_PIPE_LAYER_PREFIX}` and is not in {sorted(app.DXF_PIPE_LAYER_EXCLUDES)}",
        f"- Pipe entity types: {sorted(app.PIPE_ENTITY_TYPES)}",
        f"- Diameter marker layer: `{app.DXF_DIAMETER_LAYER}`; equipment {sorted(app.DXF_EQUIPMENT_LAYERS)}; "
        f"fittings {sorted(app.DXF_FITTING_LAYERS)}; valves {sorted(app.DXF_VALVE_LAYERS)}",
        "",
        "## Overall takeoff result (calculate_dxf_quantities)",
        "",
        f"- Total pipe length: {summary['total_pipe_length']:.6f} ({summary['length_unit']})",
        f"- Pipe entities: {summary['pipe_entity_count']}",
        f"- Pipe-layer raw entities: {summary['raw_pipe_entity_count']}",
        f"- Equipment / fittings / valves: {summary['equipment_count']} / {summary['fittings_count']} / {summary['valves_count']}",
        f"- Warnings: {', '.join(row['Code'] for row in report['warnings']) or '-'}",
        "",
        "## Layers",
        "",
        "| Layer | Pipe layer (app rule) | Pipe-like name | On/Frozen | Entities | Entity types | Measurable | Raw length (drawing units) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    names = sorted(set(layers) | set(types), key=lambda name: (-measured[name][1], name))
    for name in names:
        entry = layers.get(name)
        state = "-" if entry is None else f"{'off' if entry.is_off() else 'on'}/{'frozen' if entry.is_frozen() else 'thawed'}"
        type_text = ", ".join(f"{kind}: {count}" for kind, count in sorted(types[name].items())) or "-"
        pipe_like = any(hint in name.casefold() for hint in PIPE_HINTS)
        count, length = measured[name]
        lines.append(
            f"| `{name}` | {'YES' if app._is_dxf_pipe_layer(name) else 'no'} | {'yes' if pipe_like else '-'} | {state} | "
            f"{sum(types[name].values())} | {type_text} | {count} | {length:,.6f} |"
        )

    inserts = [(layer, block, count) for layer, counter in blocks_by_layer.items() for block, count in counter.items()]
    if inserts:
        lines += ["", "## Block inserts by layer", "", "| Layer | Block | Inserts | Classified as |", "|---|---|---|---|"]
        for layer, block, count in sorted(inserts, key=lambda row: (-row[2], row[0], row[1])):
            sample = next(e for e in entities if e.dxftype() == "INSERT" and app._dxf_layer_name(e) == layer and str(e.dxf.name) == block)
            classified = app._classify_dxf_insert(sample)
            lines.append(f"| `{layer}` | `{block}` | {count} | {classified[0] + ' / ' + classified[1] if classified else 'not classified'} |")

    texts = Counter(app._dxf_layer_name(e) for e in entities if e.dxftype() in {"TEXT", "MTEXT"})
    if texts:
        lines += ["", "## TEXT/MTEXT by layer", "", "| Layer | Count | Samples |", "|---|---|---|"]
        for layer, count in texts.most_common():
            samples = []
            for entity in entities:
                if entity.dxftype() in {"TEXT", "MTEXT"} and app._dxf_layer_name(entity) == layer:
                    text = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
                    samples.append(str(text).replace("|", "/").strip()[:30])
                if len(samples) == 5:
                    break
            lines.append(f"| `{layer}` | {count} | {'; '.join(samples)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("drawing", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = diagnose(args.drawing)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
