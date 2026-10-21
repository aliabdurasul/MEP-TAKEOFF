from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.lldxf.const import DXFError


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


BINARY_DXF_SENTINEL = b"AutoCAD Binary DXF"


class InvalidDrawingError(ValueError):
    """The file is empty, not a DXF drawing, or too damaged to recover."""


def open_dxf(file_path: str | Path) -> ezdxf.EzdxfDocument:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"DXF file not found: {path}")
    return ezdxf.readfile(path)


def looks_like_dxf(path: Path) -> bool:
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head.startswith(BINARY_DXF_SENTINEL):
        return True
    tokens = [line.strip() for line in head.decode("latin-1").splitlines()]
    while len(tokens) >= 2 and tokens[0] == "999":
        tokens = tokens[2:]
    return len(tokens) >= 2 and tokens[0] == "0" and tokens[1].upper() == "SECTION"


def _has_eof_marker(path: Path) -> bool:
    with open(path, "rb") as handle:
        handle.seek(max(path.stat().st_size - 1024, 0))
        tail = handle.read()
    if tail.endswith(b"\x00") or BINARY_DXF_SENTINEL in tail:
        return True
    return "EOF" in [line.strip().upper() for line in tail.decode("latin-1").splitlines()]


def load_dxf(file_path: str | Path) -> tuple[ezdxf.EzdxfDocument, dict[str, Any]]:
    """Open a DXF strictly; fall back to ezdxf recovery for damaged files and say so.

    Returns the document and load information: mode ("strict" or "recovered"),
    the number of recovery fixes and unrecoverable errors, and the first messages.
    """

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"DXF file not found: {path}")
    if path.stat().st_size == 0:
        raise InvalidDrawingError("The file is empty.")
    if not looks_like_dxf(path):
        raise InvalidDrawingError("The file is not a DXF drawing (no DXF SECTION header).")

    strict_error: Exception | None = None
    if _has_eof_marker(path):
        try:
            return ezdxf.readfile(path), {"mode": "strict", "fixes": 0, "errors": 0, "messages": []}
        except (DXFError, UnicodeError, ValueError) as error:
            strict_error = error

    from ezdxf import recover

    try:
        doc, auditor = recover.readfile(path)
    except Exception as error:
        reason = strict_error or "missing EOF marker"
        raise InvalidDrawingError(f"DXF could not be read or recovered: {reason}; recovery: {error}") from error
    messages = [str(getattr(entry, "message", entry)) for entry in list(auditor.errors)[:10]]
    if strict_error is not None:
        messages.insert(0, f"strict read failed: {strict_error}")
    else:
        messages.insert(0, "missing EOF marker: file is truncated")
    return doc, {"mode": "recovered", "fixes": len(auditor.fixes), "errors": len(auditor.errors), "messages": messages}


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