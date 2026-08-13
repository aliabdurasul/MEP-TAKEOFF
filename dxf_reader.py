from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import ezdxf


INSUNITS_MAP = {
    0: ("unknown", None),
    1: ("inches", 0.0254),
    2: ("feet", 0.3048),
    3: ("miles", 1609.344),
    4: ("millimeters", 0.001),
    5: ("centimeters", 0.01),
    6: ("meters", 1.0),
    7: ("kilometers", 1000.0),
    10: ("yards", 0.9144),
    14: ("decimeters", 0.1),
}

SUPPORTED_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"}
IGNORED_TYPES = {"TEXT", "MTEXT", "INSERT", "HATCH", "DIMENSION"}


def open_dxf(file_path: str | Path) -> ezdxf.EzdxfDocument:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"DXF file not found: {path}")
    return ezdxf.readfile(path)


def read_insunits(doc: ezdxf.EzdxfDocument) -> dict[str, Any]:
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    label, factor = INSUNITS_MAP.get(code, (f"unit_code_{code}", None))
    return {
        "code": code,
        "label": label,
        "meters_per_unit": factor,
        "known": factor is not None,
    }


def iter_modelspace_entities(doc: ezdxf.EzdxfDocument):
    return doc.modelspace()


def layer_entity_counts(doc: ezdxf.EzdxfDocument) -> list[dict[str, Any]]:
    layer_names = [layer.dxf.name for layer in doc.layers]
    counts = Counter()
    type_counts_by_layer: dict[str, Counter] = defaultdict(Counter)

    for entity in doc.modelspace():
        layer = entity.dxf.layer or "0"
        counts[layer] += 1
        type_counts_by_layer[layer][entity.dxftype()] += 1

    rows = []
    for layer_name in layer_names:
        rows.append(
            {
                "Layer": layer_name,
                "Object Count": int(counts.get(layer_name, 0)),
                "Entity Type Counts": dict(type_counts_by_layer.get(layer_name, {})),
            }
        )

    rows.sort(key=lambda row: row["Object Count"], reverse=True)
    return rows


def layer_names(doc: ezdxf.EzdxfDocument) -> list[str]:
    rows = layer_entity_counts(doc)
    return [row["Layer"] for row in rows]


def get_layer_entities(doc: ezdxf.EzdxfDocument, layer_name: str):
    return [entity for entity in doc.modelspace() if entity.dxf.layer == layer_name]


def summarize_layer(doc: ezdxf.EzdxfDocument, layer_name: str) -> dict[str, Any]:
    entities = get_layer_entities(doc, layer_name)
    total = len(entities)
    type_counts = Counter(entity.dxftype() for entity in entities)
    measurable = sum(type_counts.get(name, 0) for name in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"))
    ignored = total - measurable
    return {
        "layer": layer_name,
        "total_entities": total,
        "measurable_entities": measurable,
        "circle_count": int(type_counts.get("CIRCLE", 0)),
        "ignored_count": int(max(ignored, 0)),
        "type_counts": dict(type_counts),
    }