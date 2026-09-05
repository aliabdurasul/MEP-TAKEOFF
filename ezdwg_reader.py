from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import contextlib
import math

try:
    import ezdwg
    import ezdwg.raw as raw
except Exception:  # pragma: no cover - optional dependency on Linux/Cloud
    ezdwg = None
    raw = None

EZDWG_AVAILABLE = ezdwg is not None and raw is not None


def _require_ezdwg() -> None:
    if not EZDWG_AVAILABLE:
        raise RuntimeError("DWG support is unavailable in this environment. DXF mode remains available for the V0 pilot workflow.")


@dataclass(frozen=True)
class LayerInfo:
    handle: str
    name: str | None


@dataclass(frozen=True)
class EntityInfo:
    type: str
    handle: str
    layer_handle: str | None
    layer: str | None
    geometry: dict[str, Any]

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


def open_dwg(path: str | Path) -> Any:
    _require_ezdwg()
    return ezdwg.read(str(Path(path)))


def read_insunits(dwg: Any) -> dict[str, Any]:
    _require_ezdwg()
    code = getattr(dwg, "insunits", None)
    try:
        code_int = int(code)
    except Exception:
        return {"code": code, "label": "unknown", "meters_per_unit": None, "known": False}

    label, factor = INSUNITS_MAP.get(code_int, (f"unit_code_{code_int}", None))
    return {"code": code_int, "label": label, "meters_per_unit": factor, "known": factor is not None}


def _graph_layers(path: str | Path) -> dict[int, LayerInfo]:
    graph = raw.decode_document_graph(str(Path(path)), limit=1)
    layer_records = graph[4] if isinstance(graph, tuple) and len(graph) > 4 else []
    resolved: dict[int, LayerInfo] = {}
    for record in layer_records:
        if not isinstance(record, tuple) or len(record) < 2:
            continue
        handle = record[0]
        raw_name = record[1]
        if not isinstance(handle, int):
            continue
        chosen: str | None = None
        if isinstance(raw_name, str):
            candidate = raw_name.replace("\x00", "").strip()
            if candidate and (candidate == "Defpoints" or (candidate.isascii() and all(ch.isalnum() or ch in {"_", "-", " ", "."} for ch in candidate))):
                chosen = candidate
        resolved[handle] = LayerInfo(handle=str(handle), name=chosen)
    return resolved


def get_layers(dwg: Any | str | Path) -> list[dict[str, str | None]]:
    _require_ezdwg()
    if isinstance(dwg, (str, Path)):
        layers = _graph_layers(dwg)
    else:
        path = getattr(dwg, "path", None) or getattr(getattr(dwg, "doc", None), "path", None)
        if path is None:
            raise ValueError("DWG path is required to read layers")
        layers = _graph_layers(path)
    return [{"handle": info.handle, "name": info.name} for info in layers.values()]


def resolve_layer_name(layer_handle: int | str | None, dwg: Any | str | Path | None = None) -> str | None:
    if layer_handle is None:
        return None
    try:
        handle_value = int(layer_handle)
    except Exception:
        return None
    if dwg is None:
        return None
    path = dwg if isinstance(dwg, (str, Path)) else getattr(dwg, "path", None) or getattr(getattr(dwg, "doc", None), "path", None)
    if path is None:
        return None
    layers = _graph_layers(path)
    layer = layers.get(handle_value)
    return layer.name if layer else None


def _entity_handle(entity: Any) -> str:
    value = getattr(entity, "handle", None)
    if value:
        return str(value)
    dxf = getattr(entity, "dxf", None)
    if isinstance(dxf, dict):
        value = dxf.get("handle") or dxf.get("entity_handle")
        if value:
            return str(value)
    return ""


def _entity_type(entity: Any) -> str:
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
    return str(value or type(entity).__name__)


def _entity_layer_handle(entity: Any) -> str | None:
    dxf = getattr(entity, "dxf", None)
    if isinstance(dxf, dict):
        value = dxf.get("layer_handle")
        return str(value) if value is not None else None
    return None


def _point(value: Any) -> list[float]:
    if isinstance(value, (tuple, list)):
        return [float(value[0]), float(value[1])] if len(value) >= 2 else [float(value[0])]
    if hasattr(value, "x") and hasattr(value, "y"):
        return [float(value.x), float(value.y)]
    return []


def read_line(entity: Any) -> dict[str, Any]:
    dxf = entity.dxf
    start = dxf.get("start")
    end = dxf.get("end")
    start_point = _point(start)
    end_point = _point(end)
    length = math.dist(start[:2], end[:2])
    if not math.isfinite(length):
        length = 0.0
    return {"start": start_point, "end": end_point, "length": float(length)}


def read_arc(entity: Any) -> dict[str, Any]:
    dxf = entity.dxf
    center = dxf.get("center")
    radius = float(dxf.get("radius"))
    start_angle = float(dxf.get("start_angle"))
    end_angle = float(dxf.get("end_angle"))
    sweep = (end_angle - start_angle) % 360.0
    length = math.radians(sweep) * radius
    if not math.isfinite(length):
        length = 0.0
    return {"center": _point(center), "radius": radius, "start_angle": start_angle, "end_angle": end_angle, "length": float(length)}


def read_circle(entity: Any) -> dict[str, Any]:
    dxf = entity.dxf
    return {"center": _point(dxf.get("center")), "radius": float(dxf.get("radius"))}


def read_polyline(entity: Any) -> dict[str, Any]:
    vertices_attr = getattr(entity, "vertices", None)
    if callable(vertices_attr):
        vertices = list(vertices_attr())
    elif vertices_attr is not None:
        vertices = list(vertices_attr)
    else:
        vertices = []
        with contextlib.suppress(Exception):
            vertices = list(entity.to_points())
    points = [_point(point) for point in vertices]
    length = 0.0
    if len(points) >= 2:
        for left, right in zip(points, points[1:]):
            if len(left) >= 2 and len(right) >= 2:
                segment = math.dist(left[:2], right[:2])
                if math.isfinite(segment):
                    length += segment
    if not math.isfinite(length):
        length = 0.0
    return {"vertices": points, "length": float(length)}


def get_entities(dwg: Any | str | Path) -> list[dict[str, Any]]:
    _require_ezdwg()
    if isinstance(dwg, (str, Path)):
        document = open_dwg(dwg)
    else:
        document = dwg
    layers: dict[int, LayerInfo] = {}
    entities: list[dict[str, Any]] = []
    msp = document.modelspace()
    query_groups = [
        ["LINE"],
        ["ARC"],
        ["LWPOLYLINE"],
        ["POLYLINE_2D"],
        ["POLYLINE_3D"],
        ["TEXT"],
        ["MTEXT"],
        ["CIRCLE"],
        ["INSERT"],
        ["MINSERT"],
    ]
    seen_handles: set[str] = set()
    for query_types in query_groups:
        if hasattr(msp, "query"):
            iterator = msp.query(query_types[0], include_styles=False)
        else:
            iterator = msp.iter_entities() if hasattr(msp, "iter_entities") else iter(msp)
        for entity in iterator:
            kind = _entity_type(entity)
            handle = _entity_handle(entity)
            if handle and handle in seen_handles:
                continue
            if handle:
                seen_handles.add(handle)
            layer_handle = _entity_layer_handle(entity)
            layer_name = layers.get(int(layer_handle)).name if layer_handle and int(layer_handle) in layers else None
            dxf = getattr(entity, "dxf", {})
            geometry: dict[str, Any] = {}
            if kind == "LINE":
                geometry = read_line(entity)
            elif kind == "ARC":
                geometry = read_arc(entity)
            elif kind == "CIRCLE":
                geometry = read_circle(entity)
            elif kind in {"LWPOLYLINE", "POLYLINE", "POLYLINE_2D", "POLYLINE_3D"}:
                geometry = read_polyline(entity)
            entities.append(
                {
                    "type": kind,
                    "handle": handle,
                    "layer_handle": layer_handle,
                    "layer": layer_name,
                    "block_name": dxf.get("block_name") if isinstance(dxf, dict) else None,
                    "attributes": list(getattr(entity, "attribs", []) or []),
                    "raw": dict(dxf) if isinstance(dxf, dict) else {},
                    "geometry": geometry,
                }
            )
    return entities
