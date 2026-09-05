from __future__ import annotations

import hashlib
import contextlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from dxf_reader import get_layer_entities, layer_entity_counts, open_dxf, read_insunits, summarize_layer
from excel_export import build_takeoff_excel
from geometry import (
    MeasurementRow,
    approximate_entity_segments,
    convert_length,
    deduplicate_entities,
    entity_geometry_signature,
    measure_entity,
)
from ezdwg_reader import EZDWG_AVAILABLE, get_entities as get_dwg_entities
from ezdwg_reader import get_layers as get_dwg_layers
from ezdwg_reader import open_dwg, read_insunits as read_dwg_insunits


APP_TITLE = "MEP Метраж V0"
APP_SUBTITLE = "Рассчитывает метраж труб, оборудования, фитингов и клапанов по реальному DXF"

UNIT_FACTORS = {
    "unknown": None,
    "drawing units": None,
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "inches": 0.0254,
    "feet": 0.3048,
}

UNIT_LABELS = {
    "mm": "Миллиметры",
    "cm": "Сантиметры",
    "m": "Метры",
    "inches": "Дюймы",
    "feet": "Футы",
    "unknown": "Не определено",
    "drawing units": "Единицы чертежа",
}

PIPE_ENTITY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "POLYLINE_2D", "POLYLINE_3D", "ARC"}
DIAMETER_LABEL_RE = re.compile(r"(?i)(?:DN|Ø|ø)\s*([0-9]+(?:[.,][0-9]+)?)")
DXF_UNICODE_ESCAPE_RE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")
DIAMETER_MARKER_CELL_SIZE = 5000.0
MAX_REASONABLE_LENGTH = 1_000_000_000.0
DXF_PIPE_LAYER_PREFIX = "П_Трубы"
DXF_PIPE_LAYER_EXCLUDES = {"П_Трубы_ Осевая линия"}
DXF_DIAMETER_LAYER = "П_Марки труб"
DXF_EQUIPMENT_LAYERS = {"Оборудование", "Марки оборудования"}
DXF_FITTING_LAYERS = {"Соединительные детали трубопроводов"}
DXF_VALVE_LAYERS = {"Арматура трубопроводов"}
DXF_MARKER_CELL_SIZE = 5000.0
EQUIPMENT_KEYWORDS = {
    "ahu": "AHU",
    "fcu": "FCU",
    "fan coil": "FCU",
    "fancoil": "FCU",
    "pump": "PUMP",
    "boiler": "BOILER",
    "tank": "TANK",
    "radiator": "RADIATOR",
    "chiller": "CHILLER",
    "unit": "UNIT",
    "fan": "FAN",
}
FITTING_KEYWORDS = {
    "elbow": "ELBOW",
    "tee": "TEE",
    "reducer": "REDUCER",
    "coupling": "COUPLING",
    "flange": "FLANGE",
}
VALVE_KEYWORDS = {
    "valve": "VALVE",
    "gate valve": "VALVE",
    "ball valve": "VALVE",
    "check valve": "VALVE",
}


def init_state() -> None:
    defaults = {
        "upload_signature": None,
        "upload_name": None,
        "source_path": None,
        "drawing_kind": None,
        "drawing_doc": None,
        "dwg_entities": None,
        "converted_path": None,
        "dxf_doc": None,
        "insunits": None,
        "layers_table": None,
        "calculation": None,
        "calculation_key": None,
        "dxf_layer_calculation": None,
        "dxf_layer_calculation_key": None,
        "selected_layer": None,
        "unit_override": "Auto",
        "remove_duplicate_geometry": True,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_analysis() -> None:
    st.session_state["drawing_kind"] = None
    st.session_state["drawing_doc"] = None
    st.session_state["dwg_entities"] = None
    st.session_state["dxf_doc"] = None
    st.session_state["insunits"] = None
    st.session_state["layers_table"] = None
    st.session_state["calculation"] = None
    st.session_state["calculation_key"] = None
    st.session_state["dxf_layer_calculation"] = None
    st.session_state["dxf_layer_calculation_key"] = None
    st.session_state["selected_layer"] = None
    st.session_state["converted_path"] = None


def file_signature(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def ensure_runtime_dirs() -> dict[str, Path]:
    base = Path.cwd()
    data_dir = base / "data"
    paths = {
        "input": data_dir / "input",
        "converted": data_dir / "converted",
        "output": data_dir / "output",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def load_uploaded_file(uploaded_file, runtime_dirs: dict[str, Path]) -> Path:
    target = runtime_dirs["input"] / uploaded_file.name
    target.write_bytes(uploaded_file.getvalue())
    return target


def get_effective_unit(automatic: dict, override: str) -> tuple[str, float | None, bool]:
    if override != "Auto":
        factor = UNIT_FACTORS.get(override)
        label = UNIT_LABELS.get(override, override)
        return label, factor, True

    if automatic and automatic.get("known"):
        code_label = automatic["label"]
        factor = automatic["meters_per_unit"]
        label = UNIT_LABELS.get(code_label, code_label)
        return label, factor, False

    return "Единицы чертежа", None, False


def _dwg_layer_label(entity: dict) -> str:
    if entity.get("layer"):
        return str(entity["layer"])
    layer_handle = entity.get("layer_handle")
    return f"handle:{layer_handle}" if layer_handle is not None else "handle:unknown"


def build_dwg_layer_table(layers: list[dict], entities: list[dict]) -> list[dict]:
    counts = Counter(_dwg_layer_label(entity) for entity in entities)
    rows: list[dict] = []
    for layer in layers:
        label = layer["name"] if layer.get("name") else f"handle:{layer['handle']}"
        rows.append(
            {
                "Layer": label,
                "Handle": layer["handle"],
                "Resolved Name": layer.get("name"),
                "Object Count": int(counts.get(label, 0)),
            }
        )
    rows.sort(key=lambda row: row["Object Count"], reverse=True)
    return rows


def _dwg_measurement_value(entity: dict) -> float:
    geometry = entity.get("geometry", {})
    value = geometry.get("length")
    if value is None:
        return 0.0
    try:
        measurement = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(measurement) or abs(measurement) > MAX_REASONABLE_LENGTH:
        return 0.0
    return measurement


def _dwg_text_value(entity: dict) -> str:
    raw = entity.get("raw", {})
    for key in ("text", "raw_text"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _dwg_reference_point(entity: dict) -> tuple[float, float] | None:
    geometry = entity.get("geometry", {})
    entity_type = entity.get("type")
    if entity_type == "LINE":
        start = geometry.get("start")
        end = geometry.get("end")
        if start and end:
            point = ((float(start[0]) + float(end[0])) / 2.0, (float(start[1]) + float(end[1])) / 2.0)
            if all(math.isfinite(value) for value in point):
                return point
    elif entity_type == "ARC":
        center = geometry.get("center")
        if center and len(center) >= 2:
            point = float(center[0]), float(center[1])
            if all(math.isfinite(value) for value in point):
                return point
    elif entity_type in {"LWPOLYLINE", "POLYLINE", "POLYLINE_2D", "POLYLINE_3D"}:
        vertices = geometry.get("vertices") or []
        points = [point for point in vertices if len(point) >= 2]
        if points:
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            point = (sum(xs) / len(xs), sum(ys) / len(ys))
            if all(math.isfinite(value) for value in point):
                return point
    return None


def _normalize_diameter_label(text: str) -> str | None:
    match = DIAMETER_LABEL_RE.search(text.replace(" ", ""))
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed.is_integer():
        diameter_text = str(int(parsed))
    else:
        diameter_text = value
    return f"DN{diameter_text}"


def _normalize_symbol_name(name: str | None) -> str:
    if not name:
        return "UNKNOWN"
    value = str(name).strip()
    if not value:
        return "UNKNOWN"
    lowered = value.lower()
    for keyword, label in EQUIPMENT_KEYWORDS.items():
        if keyword in lowered:
            return label
    for keyword, label in FITTING_KEYWORDS.items():
        if keyword in lowered:
            return label
    for keyword, label in VALVE_KEYWORDS.items():
        if keyword in lowered:
            return label
    if value.isalpha() and len(value) >= 3:
        return value.upper()
    return "UNKNOWN"


def _best_diameter_label(entity: dict, markers_by_layer: dict[str, list[dict]]) -> str:
    layer_handle = entity.get("layer_handle")
    if layer_handle is None:
        return "UNKNOWN"
    candidates = markers_by_layer.get(str(layer_handle), [])
    if not candidates:
        return "UNKNOWN"
    reference = _dwg_reference_point(entity)
    if reference is None:
        return "UNKNOWN"
    best_label = "UNKNOWN"
    best_distance = float("inf")
    for marker in candidates:
        marker_point = marker.get("point")
        if marker_point is None:
            continue
        distance = math.hypot(reference[0] - marker_point[0], reference[1] - marker_point[1])
        threshold = max(3000.0, float(marker.get("height") or 0.0) * 8.0)
        if distance < best_distance and distance <= threshold:
            best_distance = distance
            best_label = marker["label"]
    return best_label


def _marker_cell(point: tuple[float, float]) -> tuple[int, int]:
    if not all(math.isfinite(value) for value in point):
        raise ValueError("non-finite point")
    return (
        int(math.floor(point[0] / DIAMETER_MARKER_CELL_SIZE)),
        int(math.floor(point[1] / DIAMETER_MARKER_CELL_SIZE)),
    )


def _collect_diameter_markers(entities: list[dict]) -> tuple[dict[str, list[dict]], dict[tuple[int, int], list[dict]]]:
    markers_by_layer: dict[str, list[dict]] = defaultdict(list)
    markers_by_cell: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for entity in entities:
        if entity.get("type") not in {"TEXT", "MTEXT"}:
            continue
        text_value = _dwg_text_value(entity)
        label = _normalize_diameter_label(text_value)
        if not label:
            continue
        raw = entity.get("raw", {})
        point = raw.get("insert") or raw.get("location") or raw.get("position")
        if not point or len(point) < 2:
            continue
        if not all(math.isfinite(float(value)) for value in point[:2]):
            continue
        layer_handle = entity.get("layer_handle")
        marker = {
            "label": label,
            "text": text_value,
            "point": (float(point[0]), float(point[1])),
            "height": float(raw.get("char_height") or raw.get("height") or 0.0),
            "layer_handle": str(layer_handle) if layer_handle is not None else None,
        }
        if layer_handle is not None:
            markers_by_layer[str(layer_handle)].append(marker)
        markers_by_cell[_marker_cell(marker["point"])].append(marker)
    return markers_by_layer, markers_by_cell


def _candidate_markers_for_point(
    point: tuple[float, float],
    markers_by_cell: dict[tuple[int, int], list[dict]],
) -> list[dict]:
    if not all(math.isfinite(value) for value in point):
        return []
    cell_x, cell_y = _marker_cell(point)
    candidates: list[dict] = []
    for offset_x in (-1, 0, 1):
        for offset_y in (-1, 0, 1):
            candidates.extend(markers_by_cell.get((cell_x + offset_x, cell_y + offset_y), []))
    return candidates


def calculate_dwg_quantities(entities: list[dict], display_unit_label: str, meters_per_unit: float | None) -> dict:
    markers_by_layer, markers_by_cell = _collect_diameter_markers(entities)

    pipes_rows: list[dict] = []
    pipes_by_diameter = defaultdict(float)
    layer_rows = []
    layer_counts = Counter(_dwg_layer_label(entity) for entity in entities)

    for entity in entities:
        if entity.get("type") not in PIPE_ENTITY_TYPES:
            continue
        raw_length = _dwg_measurement_value(entity)
        converted_length = convert_length(raw_length, meters_per_unit)
        diameter = _best_diameter_label(entity, markers_by_layer)
        if diameter == "UNKNOWN":
            reference = _dwg_reference_point(entity)
            if reference is not None:
                best_distance = float("inf")
                for marker in _candidate_markers_for_point(reference, markers_by_cell):
                    marker_point = marker.get("point")
                    if marker_point is None:
                        continue
                    distance = math.hypot(reference[0] - marker_point[0], reference[1] - marker_point[1])
                    threshold = max(3000.0, float(marker.get("height") or 0.0) * 8.0)
                    if distance < best_distance and distance <= threshold:
                        best_distance = distance
                        diameter = marker["label"]
        layer_label = _dwg_layer_label(entity)
        pipes_rows.append(
            {
                "Layer": layer_label,
                "System": layer_label,
                "Diameter": diameter,
                "Length": round(converted_length, 6),
            }
        )
        if math.isfinite(converted_length):
            pipes_by_diameter[diameter] += converted_length

    equipment_counts = Counter()
    fitting_counts = Counter()
    valve_counts = Counter()
    for entity in entities:
        if entity.get("type") not in {"INSERT", "MINSERT"}:
            continue
        raw = entity.get("raw", {})
        symbol_name = raw.get("name") or raw.get("block_name") or entity.get("block_name")
        label = _normalize_symbol_name(symbol_name)
        if label in EQUIPMENT_KEYWORDS.values():
            equipment_counts[label] += 1
        elif label in FITTING_KEYWORDS.values():
            fitting_counts[label] += 1
        elif label in VALVE_KEYWORDS.values():
            valve_counts[label] += 1
        else:
            equipment_counts["UNKNOWN"] += 1

    pipe_rows_df = [
        {"Diameter": diameter, "Length": round(total, 6)}
        for diameter, total in sorted(pipes_by_diameter.items(), key=lambda item: item[0])
    ]
    if not pipe_rows_df:
        pipe_rows_df = [{"Diameter": "UNKNOWN", "Length": 0.0}]

    equipment_rows = [{"Type": key, "Quantity": value} for key, value in sorted(equipment_counts.items())]
    if not equipment_rows:
        equipment_rows = [{"Type": "UNKNOWN", "Quantity": 0}]

    fittings_rows = [{"Type": key, "Diameter": "UNKNOWN", "Quantity": value} for key, value in sorted(fitting_counts.items())]
    if not fittings_rows:
        fittings_rows = [{"Type": "UNKNOWN", "Diameter": "UNKNOWN", "Quantity": 0}]

    valves_rows = [{"Type": key, "Diameter": "UNKNOWN", "Quantity": value} for key, value in sorted(valve_counts.items())]
    if not valves_rows:
        valves_rows = [{"Type": "UNKNOWN", "Diameter": "UNKNOWN", "Quantity": 0}]

    summary = {
        "total_pipe_length": math.fsum(value for value in pipes_by_diameter.values() if math.isfinite(value)),
        "equipment_count": int(sum(equipment_counts.values())),
        "fittings_count": int(sum(fitting_counts.values())),
        "valves_count": int(sum(valve_counts.values())),
    }

    layers_rows = [
        {"Layer": label, "Object Count": count}
        for label, count in sorted(layer_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "summary": summary,
        "pipes_rows": pipe_rows_df,
        "equipment_rows": equipment_rows,
        "fittings_rows": fittings_rows,
        "valves_rows": valves_rows,
        "layers_rows": layers_rows,
        "detail_rows": pipes_rows,
    }


def calculate_dwg_layer(entities: list[dict], layer_label: str, display_unit_label: str, meters_per_unit: float | None) -> dict:
    layer_entities = [entity for entity in entities if _dwg_layer_label(entity) == layer_label]
    type_counts = Counter(entity["type"] for entity in layer_entities)
    measurement_rows = []
    object_type_totals = defaultdict(lambda: {"Count": 0, "Total Length": 0.0})

    detail_rows = []
    measurable_count = 0
    circle_count = int(type_counts.get("CIRCLE", 0))
    ignored_count = 0
    object_id = 1

    for entity in layer_entities:
        entity_type = entity["type"]
        if entity_type == "CIRCLE":
            ignored_count += 1
            continue

        if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}:
            ignored_count += 1
            continue

        raw_length = _dwg_measurement_value(entity)
        measurable_count += 1
        converted_length = convert_length(raw_length, meters_per_unit)
        detail_rows.append(
            {
                "Object ID": object_id,
                "Layer": layer_label,
                "Entity Type": entity_type,
                "Length": round(converted_length, 6),
                "Unit": "m" if meters_per_unit is not None else display_unit_label,
            }
        )
        object_type_totals[entity_type]["Count"] += 1
        object_type_totals[entity_type]["Total Length"] += converted_length
        measurement_rows.append(
            MeasurementRow(
                object_id=object_id,
                layer=layer_label,
                entity_type=entity_type,
                raw_length=raw_length,
                converted_length=converted_length,
                display_unit=display_unit_label,
            )
        )
        object_id += 1

    total_length = sum(row.converted_length for row in measurement_rows)
    object_type_rows = [
        {
            "Entity Type": entity_type,
            "Count": stats["Count"],
            "Total Length": round(stats["Total Length"], 6),
        }
        for entity_type, stats in object_type_totals.items()
    ]

    for entity_type in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"):
        if entity_type not in object_type_totals:
            object_type_rows.append({"Entity Type": entity_type, "Count": 0, "Total Length": 0.0})

    object_type_rows.sort(key=lambda row: (row["Entity Type"] not in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"), row["Entity Type"]))

    return {
        "layer": layer_label,
        "total_entities": len(layer_entities),
        "measurable_entities": measurable_count,
        "circle_count": circle_count,
        "ignored_count": ignored_count,
        "total_length": total_length,
        "detail_rows": detail_rows,
        "object_type_rows": object_type_rows,
        "measurement_rows": measurement_rows,
        "type_counts": dict(type_counts),
    }


def _dwg_arc_points(center: list[float], radius: float, start_angle: float, end_angle: float, segments: int = 48) -> list[tuple[float, float]]:
    import math as _math

    start = _math.radians(start_angle)
    end = _math.radians(end_angle)
    sweep = end - start
    if sweep <= 0:
        sweep += 2 * _math.pi
    points = []
    for index in range(segments + 1):
        angle = start + sweep * index / segments
        points.append((center[0] + radius * _math.cos(angle), center[1] + radius * _math.sin(angle)))
    return points


def plot_dwg_selected_layer(entities: list[dict]) -> None:
    if not entities:
        st.info("Для этого слоя нет геометрии для предпросмотра.")
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    drawn = False

    for entity in entities:
        geometry = entity.get("geometry", {})
        entity_type = entity.get("type")
        if entity_type == "LINE":
            start = geometry.get("start")
            end = geometry.get("end")
            if start and end:
                ax.plot([start[0], end[0]], [start[1], end[1]], linewidth=1.2)
                drawn = True
        elif entity_type == "ARC":
            center = geometry.get("center")
            radius = geometry.get("radius")
            start_angle = geometry.get("start_angle")
            end_angle = geometry.get("end_angle")
            if center and radius is not None and start_angle is not None and end_angle is not None:
                points = _dwg_arc_points(center, float(radius), float(start_angle), float(end_angle))
                ax.plot([point[0] for point in points], [point[1] for point in points], linewidth=1.2)
                drawn = True
        elif entity_type == "CIRCLE":
            center = geometry.get("center")
            radius = geometry.get("radius")
            if center and radius is not None:
                points = _dwg_arc_points(center, float(radius), 0.0, 360.0)
                ax.plot([point[0] for point in points], [point[1] for point in points], linewidth=1.2)
                drawn = True
        elif entity_type in {"LWPOLYLINE", "POLYLINE", "POLYLINE_2D", "POLYLINE_3D"}:
            vertices = geometry.get("vertices") or []
            if len(vertices) >= 2:
                ax.plot([point[0] for point in vertices], [point[1] for point in vertices], linewidth=1.2)
                drawn = True

    if not drawn:
        st.info("В выбранном слое нет геометрии для предпросмотра.")
        return

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Геометрия выбранного слоя")
    ax.grid(True, alpha=0.3)
    st.pyplot(fig, clear_figure=True)


def prepare_document(file_path: Path, runtime_dirs: dict[str, Path]) -> tuple[Path, object, dict]:
    suffix = file_path.suffix.lower()
    if suffix == ".dwg":
        dwg_doc = open_dwg(file_path)
        insunits = read_dwg_insunits(dwg_doc)
        st.session_state["drawing_kind"] = "dwg"
        st.session_state["drawing_doc"] = dwg_doc
        st.session_state["dwg_entities"] = None
        st.session_state["dxf_doc"] = None
        st.session_state["insunits"] = insunits
        st.session_state["layers_table"] = []
        st.session_state["source_path"] = str(file_path)
        st.session_state["converted_path"] = None
        return file_path, dwg_doc, insunits
    else:
        doc = open_dxf(file_path)
        insunits = read_insunits(doc)
        st.session_state["drawing_kind"] = "dxf"
        st.session_state["drawing_doc"] = doc
        st.session_state["dxf_doc"] = doc
        st.session_state["dwg_entities"] = None
        st.session_state["insunits"] = insunits
        st.session_state["layers_table"] = build_layer_table(doc)
        st.session_state["source_path"] = str(file_path)
        st.session_state["converted_path"] = None
        return file_path, doc, insunits


def build_layer_table(doc) -> list[dict]:
    return layer_entity_counts(doc)


def calculate_layer(
    doc,
    layer_name: str,
    display_unit_label: str,
    meters_per_unit: float | None,
    remove_duplicate_geometry: bool = True,
) -> dict:
    entities = get_layer_entities(doc, layer_name)
    seen_layer_handles: set[str] = set()
    handle_unique_entities: list = []
    for entity in entities:
        handle = _entity_handle(entity)
        if handle != "NO_HANDLE" and handle in seen_layer_handles:
            continue
        if handle != "NO_HANDLE":
            seen_layer_handles.add(handle)
        handle_unique_entities.append(entity)

    measurable_raw_length = 0.0
    for entity in handle_unique_entities:
        raw_length, measurable, ignored = measure_entity(entity)
        if measurable and not ignored:
            measurable_raw_length += raw_length

    if remove_duplicate_geometry:
        unique_entities, duplicate_entities = deduplicate_entities(handle_unique_entities)
    else:
        unique_entities, duplicate_entities = handle_unique_entities, []

    duplicate_raw_length = sum(
        measure_entity(entity)[0]
        for entity in duplicate_entities
        if measure_entity(entity)[1] and not measure_entity(entity)[2]
    )
    duplicate_converted_length = convert_length(duplicate_raw_length, meters_per_unit)

    type_counts = Counter(entity.dxftype() for entity in unique_entities)
    measurement_rows = []
    object_type_totals = defaultdict(lambda: {"Count": 0, "Total Length": 0.0})

    detail_rows = []
    measurable_count = 0
    circle_count = int(type_counts.get("CIRCLE", 0))
    ignored_count = 0
    object_id = 1

    for entity in unique_entities:
        raw_length, measurable, ignored = measure_entity(entity)
        entity_type = entity.dxftype()
        if entity_type == "CIRCLE":
            ignored_count += 1
            continue

        if ignored:
            ignored_count += 1
            continue

        if measurable:
            measurable_count += 1
            converted_length = convert_length(raw_length, meters_per_unit)
            detail_rows.append(
                {
                    "Handle": _entity_handle(entity),
                    "Object ID": object_id,
                    "Layer": layer_name,
                    "Entity Type": entity_type,
                    "Raw Length": round(float(raw_length), 6),
                    "Length": round(float(converted_length), 6),
                    "Unit": "m" if meters_per_unit is not None else display_unit_label,
                    "Diameter": "UNKNOWN",
                    "Diameter Source": "not applicable",
                    "Status": "CONFIRMED",
                    "Reason": "Измерение геометрии подтверждено DXF",
                }
            )
            object_type_totals[entity_type]["Count"] += 1
            object_type_totals[entity_type]["Total Length"] += converted_length
            measurement_rows.append(
                MeasurementRow(
                    object_id=object_id,
                    layer=layer_name,
                    entity_type=entity_type,
                    raw_length=raw_length,
                    converted_length=converted_length,
                    display_unit=display_unit_label,
                )
            )
            object_id += 1

    total_length = sum(row.converted_length for row in measurement_rows)
    object_type_rows = [
        {
            "Entity Type": entity_type,
            "Count": stats["Count"],
            "Total Length": round(stats["Total Length"], 6),
        }
        for entity_type, stats in object_type_totals.items()
    ]

    for entity_type in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"):
        if entity_type not in object_type_totals:
            object_type_rows.append({"Entity Type": entity_type, "Count": 0, "Total Length": 0.0})

    object_type_rows.sort(key=lambda row: (row["Entity Type"] not in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"), row["Entity Type"]))

    return {
        "layer": layer_name,
        "total_entities": len(entities),
        "duplicate_entities": len(duplicate_entities),
        "duplicate_raw_length": duplicate_raw_length,
        "duplicate_converted_length": duplicate_converted_length,
        "raw_total_length": convert_length(measurable_raw_length, meters_per_unit),
        "final_total_length": total_length,
        "measurable_entities": measurable_count,
        "circle_count": circle_count,
        "ignored_count": ignored_count,
        "total_length": total_length,
        "detail_rows": detail_rows,
        "object_type_rows": object_type_rows,
        "measurement_rows": measurement_rows,
        "type_counts": dict(type_counts),
    }


def _entity_handle(entity) -> str:
    handle = getattr(entity, "handle", None)
    if handle is None:
        handle = getattr(getattr(entity, "dxf", None), "handle", None)
    if handle is None:
        return "NO_HANDLE"
    return str(handle)


def _dxf_layer_name(entity) -> str:
    return str(getattr(entity.dxf, "layer", None) or "0")


def _is_dxf_pipe_layer(layer_name: str) -> bool:
    return layer_name.startswith(DXF_PIPE_LAYER_PREFIX) and layer_name not in DXF_PIPE_LAYER_EXCLUDES


def _validate_pipe_invariants(total_pipe_length: float, pipe_rows: list[dict], pipe_detail_rows: list[dict], pipe_entity_count: int) -> None:
    if pipe_rows:
        diameter_total = sum(float(row.get("Length (m)") or 0.0) for row in pipe_rows)
        if not math.isclose(diameter_total, total_pipe_length, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(
                f"Pipe diameter total mismatch: total={total_pipe_length} diameter_total={diameter_total}"
            )
    if pipe_detail_rows:
        real_handles = {row["Handle"] for row in pipe_detail_rows if row.get("Handle") not in (None, "NO_HANDLE")}
        if real_handles and len(real_handles) != pipe_entity_count:
            raise ValueError(
                f"Duplicate or unstable pipe handle selection: handles={len(real_handles)} pipe_entity_count={pipe_entity_count}"
            )


def _entity_geometry_signature(entity) -> tuple | None:
    return entity_geometry_signature(entity)


def _count_duplicate_candidates(entities: list) -> int:
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for entity in entities:
        signature = _entity_geometry_signature(entity)
        if signature is None:
            continue
        buckets[signature].append(_entity_handle(entity))
    return sum(len(values) - 1 for values in buckets.values() if len(values) > 1)


def _dxf_text_value(entity) -> str:
    if entity.dxftype() == "MTEXT":
        with contextlib.suppress(Exception):
            return _decode_dxf_text(entity.plain_text()).strip()
        raw_text = getattr(entity.dxf, "text", None)
        if isinstance(raw_text, str):
            return _decode_dxf_text(raw_text).strip()
        return ""
    value = getattr(entity.dxf, "text", None)
    return _decode_dxf_text(value).strip() if isinstance(value, str) else ""


def _decode_dxf_text(text: str) -> str:
    if "\\U+" not in text:
        return text

    def replace_match(match: re.Match[str]) -> str:
        code_point = int(match.group(1), 16)
        with contextlib.suppress(Exception):
            return chr(code_point)
        return ""

    return DXF_UNICODE_ESCAPE_RE.sub(replace_match, text)


def _dxf_point_2d(value) -> tuple[float, float] | None:
    if value is None:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
    except Exception:
        return None
    if not all(math.isfinite(component) for component in (x, y)):
        return None
    return (x, y)


def _dxf_reference_point(entity) -> tuple[float, float] | None:
    kind = entity.dxftype()
    if kind == "LINE":
        start = _dxf_point_2d(getattr(entity.dxf, "start", None))
        end = _dxf_point_2d(getattr(entity.dxf, "end", None))
        if start and end:
            point = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
            return point if all(math.isfinite(value) for value in point) else None
    elif kind == "ARC":
        center = _dxf_point_2d(getattr(entity.dxf, "center", None))
        return center
    elif kind == "CIRCLE":
        center = _dxf_point_2d(getattr(entity.dxf, "center", None))
        return center
    elif kind == "LWPOLYLINE":
        points = []
        with contextlib.suppress(Exception):
            points = [tuple(point[:2]) for point in entity.get_points("xy")]
        coords = [(_dxf_point_2d(point) or (None, None)) for point in points]
        filtered = [(x, y) for x, y in coords if x is not None and y is not None]
        if filtered:
            xs = [point[0] for point in filtered]
            ys = [point[1] for point in filtered]
            point = (sum(xs) / len(xs), sum(ys) / len(ys))
            return point if all(math.isfinite(value) for value in point) else None
    elif kind == "POLYLINE":
        points = []
        vertices = getattr(entity, "vertices", None)
        if callable(vertices):
            with contextlib.suppress(Exception):
                points = [vertex.dxf.location for vertex in vertices()]
        elif vertices is not None:
            with contextlib.suppress(Exception):
                points = [vertex.dxf.location for vertex in vertices]
        filtered = [point for point in (_dxf_point_2d(point) for point in points) if point is not None]
        if filtered:
            xs = [point[0] for point in filtered]
            ys = [point[1] for point in filtered]
            point = (sum(xs) / len(xs), sum(ys) / len(ys))
            return point if all(math.isfinite(value) for value in point) else None
    return None


def _normalize_dxf_diameter_label(text: str) -> str | None:
    cleaned = _decode_dxf_text(text).replace(" ", "")
    match = DIAMETER_LABEL_RE.search(cleaned)
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed.is_integer():
        diameter_text = str(int(parsed))
    else:
        diameter_text = value
    return f"DN{diameter_text}"


def _marker_cell(point: tuple[float, float]) -> tuple[int, int]:
    if not all(math.isfinite(value) for value in point):
        raise ValueError("non-finite point")
    return (
        int(math.floor(point[0] / DXF_MARKER_CELL_SIZE)),
        int(math.floor(point[1] / DXF_MARKER_CELL_SIZE)),
    )


def _collect_dxf_diameter_markers(entities: list) -> dict[tuple[int, int], list[dict]]:
    markers_by_cell: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for entity in entities:
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        if _dxf_layer_name(entity) != DXF_DIAMETER_LAYER:
            continue
        text_value = _dxf_text_value(entity)
        label = _normalize_dxf_diameter_label(text_value)
        if not label:
            continue
        insert = _dxf_point_2d(getattr(entity.dxf, "insert", None) or getattr(entity.dxf, "location", None) or getattr(entity.dxf, "position", None))
        if insert is None:
            continue
        height_value = getattr(entity.dxf, "char_height", None) or getattr(entity.dxf, "height", None) or 0.0
        try:
            height = float(height_value)
        except Exception:
            height = 0.0
        marker = {"label": label, "point": insert, "height": height}
        markers_by_cell[_marker_cell(insert)].append(marker)
    return markers_by_cell


def _axis_category_from_points(start: tuple[float, float], end: tuple[float, float]) -> str:
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dx == 0.0 and dy == 0.0:
        return "UNKNOWN"
    return "X" if dx >= dy else "Z"


def _infer_pipe_category(entity) -> str:
    kind = entity.dxftype()
    if kind == "LINE":
        start = _dxf_point_2d(getattr(entity.dxf, "start", None))
        end = _dxf_point_2d(getattr(entity.dxf, "end", None))
        if start is None or end is None:
            return "UNKNOWN"
        return _axis_category_from_points(start, end)

    if kind in {"LWPOLYLINE", "POLYLINE"}:
        try:
            points = [
                _dxf_point_2d(point)
                for point in entity.get_points("xy")
            ]
        except Exception:
            points = []
        filtered = [point for point in points if point is not None]
        if len(filtered) < 2:
            return "UNKNOWN"
        total_x = 0.0
        total_z = 0.0
        for index in range(len(filtered) - 1):
            start = filtered[index]
            end = filtered[index + 1]
            total_x += abs(end[0] - start[0])
            total_z += abs(end[1] - start[1])
        return "X" if total_x >= total_z else "Z"

    if kind == "ARC":
        center = _dxf_point_2d(getattr(entity.dxf, "center", None))
        if center is None:
            return "UNKNOWN"
        start = getattr(entity.dxf, "start_angle", 0.0)
        end = getattr(entity.dxf, "end_angle", 0.0)
        with contextlib.suppress(Exception):
            start = float(start)
            end = float(end)
        if not math.isfinite(start) or not math.isfinite(end):
            return "UNKNOWN"
        return "X" if abs(start - end) <= 180.0 else "Z"

    return "UNKNOWN"


def _candidate_markers_for_point(point: tuple[float, float], markers_by_cell: dict[tuple[int, int], list[dict]]) -> list[dict]:
    if not all(math.isfinite(value) for value in point):
        return []
    cell_x, cell_y = _marker_cell(point)
    candidates: list[dict] = []
    for offset_x in (-1, 0, 1):
        for offset_y in (-1, 0, 1):
            candidates.extend(markers_by_cell.get((cell_x + offset_x, cell_y + offset_y), []))
    return candidates


def _best_dxf_diameter_label(entity, markers_by_cell: dict[tuple[int, int], list[dict]]) -> str:
    reference = _dxf_reference_point(entity)
    if reference is None:
        return "UNKNOWN"
    best_label = "UNKNOWN"
    best_distance = float("inf")
    for marker in _candidate_markers_for_point(reference, markers_by_cell):
        marker_point = marker.get("point")
        if marker_point is None:
            continue
        distance = math.hypot(reference[0] - marker_point[0], reference[1] - marker_point[1])
        threshold = max(3000.0, float(marker.get("height") or 0.0) * 8.0)
        if distance < best_distance and distance <= threshold:
            best_distance = distance
            best_label = marker["label"]
    return best_label


def _dxf_diameter_evidence(entity, markers_by_cell: dict[tuple[int, int], list[dict]]) -> dict:
    reference = _dxf_reference_point(entity)
    if reference is None:
        return {
            "reference": None,
            "marker_label": None,
            "marker_distance": None,
            "marker_threshold": None,
            "reason": "NO_REFERENCE_POINT",
        }

    nearest = None
    for marker in _candidate_markers_for_point(reference, markers_by_cell):
        marker_point = marker.get("point")
        if marker_point is None:
            continue
        distance = math.hypot(reference[0] - marker_point[0], reference[1] - marker_point[1])
        threshold = max(3000.0, float(marker.get("height") or 0.0) * 8.0)
        candidate = (distance, marker, threshold)
        if nearest is None or distance < nearest[0]:
            nearest = candidate

    if nearest is None:
        return {
            "reference": reference,
            "marker_label": None,
            "marker_distance": None,
            "marker_threshold": None,
            "reason": "NO_DIAMETER_MARKER_IN_ADJACENT_CELLS",
        }

    distance, marker, threshold = nearest
    accepted = distance <= threshold
    return {
        "reference": reference,
        "marker_label": marker.get("label"),
        "marker_distance": distance,
        "marker_threshold": threshold,
        "reason": "MARKER_WITHIN_THRESHOLD" if accepted else "NEAREST_MARKER_OUTSIDE_THRESHOLD",
    }


def _classify_dxf_insert(entity) -> tuple[str, str] | None:
    layer_name = _dxf_layer_name(entity)
    block_name = str(getattr(entity.dxf, "name", None) or "").strip()
    if not block_name:
        return None
    lowered = block_name.lower()

    if layer_name in DXF_FITTING_LAYERS:
        if any(keyword in lowered for keyword in ("отвод", "угольник")):
            return "FITTING", "Elbow"
        if "тройник" in lowered:
            return "FITTING", "Tee"
        if any(keyword in lowered for keyword in ("переход", "редук")):
            return "FITTING", "Reducer"
        if any(keyword in lowered for keyword in ("фланец",)):
            return "FITTING", "Flange"
        if any(keyword in lowered for keyword in ("муфт", "кольцо", "соедин")):
            return "FITTING", "Coupling"
        return "FITTING", "Fitting"

    if layer_name in DXF_VALVE_LAYERS:
        if any(keyword in lowered for keyword in ("кран", "клапан", "задвиж", "вентиль", "valve")):
            return "VALVE", "Valve"
        return None

    if layer_name in DXF_EQUIPMENT_LAYERS or any(keyword in lowered for keyword in (
        "оборудование",
        "отопительный прибор",
        "шрв",
        "радиатор",
        "pump",
        "fcu",
        "ahu",
        "boiler",
        "tank",
        "fan",
        "чиллер",
        "насос",
    )):
        if "отопительный прибор" in lowered:
            return "EQUIPMENT", "Heating fixture"
        if "шрв" in lowered:
            return "EQUIPMENT", "Manifold cabinet"
        if "радиатор" in lowered:
            return "EQUIPMENT", "Radiator"
        if "pump" in lowered or "насос" in lowered:
            return "EQUIPMENT", "Pump"
        if any(keyword in lowered for keyword in ("fcu", "fan coil", "fancoil")):
            return "EQUIPMENT", "FCU"
        if "ahu" in lowered:
            return "EQUIPMENT", "AHU"
        if "boiler" in lowered or "котел" in lowered:
            return "EQUIPMENT", "Boiler"
        if "tank" in lowered:
            return "EQUIPMENT", "Tank"
        if "чиллер" in lowered:
            return "EQUIPMENT", "Chiller"
        if "fan" in lowered:
            return "EQUIPMENT", "Fan"
        return "EQUIPMENT", "Equipment"

    return None


def calculate_dxf_quantities(
    doc,
    display_unit_label: str,
    meters_per_unit: float | None,
    remove_duplicate_geometry: bool = True,
) -> dict:
    entities = list(doc.modelspace())
    markers_by_cell = _collect_dxf_diameter_markers(entities)

    raw_entity_count = len(entities)
    raw_prefixed_pipe_geometry_entities = [
        entity for entity in entities
        if _dxf_layer_name(entity).startswith(DXF_PIPE_LAYER_PREFIX)
        and entity.dxftype() in PIPE_ENTITY_TYPES
        and measure_entity(entity)[1]
        and not measure_entity(entity)[2]
    ]
    raw_pipe_layer_entities = [
        entity for entity in entities
        if _is_dxf_pipe_layer(_dxf_layer_name(entity)) and entity.dxftype() in PIPE_ENTITY_TYPES
    ]
    excluded_pipe_geometry_entities = [
        entity for entity in raw_prefixed_pipe_geometry_entities
        if not _is_dxf_pipe_layer(_dxf_layer_name(entity))
    ]
    after_auxiliary_filter = []
    for entity in raw_pipe_layer_entities:
        if entity.dxftype() not in PIPE_ENTITY_TYPES:
            continue
        raw_length, measurable, ignored = measure_entity(entity)
        if not measurable or ignored:
            continue
        if entity.dxftype() in {"POLYLINE", "LWPOLYLINE"} and getattr(entity, "closed", False):
            continue
        after_auxiliary_filter.append(entity)

    duplicate_candidates = _count_duplicate_candidates(after_auxiliary_filter)

    pipes_by_diameter = defaultdict(float)
    pipe_detail_rows: list[dict] = []
    layer_counts = Counter()
    layer_measured_length = defaultdict(float)
    layer_raw_length = defaultdict(float)
    layer_duplicate_count = Counter()
    layer_duplicate_raw_length = defaultdict(float)
    pipe_entity_count = 0
    seen_entity_handles: set[str] = set()
    pipe_entities_by_layer: dict[str, list] = defaultdict(list)

    for entity in entities:
        handle = _entity_handle(entity)
        if handle != "NO_HANDLE" and handle in seen_entity_handles:
            continue
        if handle != "NO_HANDLE":
            seen_entity_handles.add(handle)

        layer_name = _dxf_layer_name(entity)
        layer_counts[layer_name] += 1
        if not _is_dxf_pipe_layer(layer_name):
            continue
        raw_length, measurable, ignored = measure_entity(entity)
        if not measurable or ignored:
            continue
        converted_length = convert_length(raw_length, meters_per_unit)
        if not math.isfinite(converted_length) or converted_length < 0:
            continue
        layer_raw_length[layer_name] += converted_length
        pipe_entities_by_layer[layer_name].append(entity)

    unique_pipe_entities: list = []
    for layer_name, layer_entities in pipe_entities_by_layer.items():
        if remove_duplicate_geometry:
            unique_entities, duplicate_entities = deduplicate_entities(layer_entities)
        else:
            unique_entities, duplicate_entities = layer_entities, []
        unique_pipe_entities.extend(unique_entities)
        layer_duplicate_count[layer_name] = len(duplicate_entities)
        layer_duplicate_raw_length[layer_name] = sum(
            convert_length(measure_entity(entity)[0], meters_per_unit)
            for entity in duplicate_entities
            if measure_entity(entity)[1] and not measure_entity(entity)[2]
        )

    unique_pipe_handles = {_entity_handle(entity) for entity in unique_pipe_entities}

    for entity in unique_pipe_entities:
        handle = _entity_handle(entity)
        layer_name = _dxf_layer_name(entity)
        raw_length, measurable, ignored = measure_entity(entity)
        if not measurable or ignored:
            continue
        converted_length = convert_length(raw_length, meters_per_unit)
        if not math.isfinite(converted_length) or converted_length < 0:
            continue
        diameter = _best_dxf_diameter_label(entity, markers_by_cell)
        diameter_evidence = _dxf_diameter_evidence(entity, markers_by_cell)
        diameter_source = "TEXT/MTEXT marker on DXF layer"
        status = "CONFIRMED"
        reason = "Диаметр подтверждён по маркерам DXF"
        if diameter == "UNKNOWN":
            diameter_source = "UNKNOWN"
            status = "UNKNOWN"
            reason = "NO_DIAMETER_FOUND"
        category = _infer_pipe_category(entity)
        entity_type = entity.dxftype()
        pipe_entity_count += 1
        pipes_by_diameter[diameter] += converted_length
        layer_measured_length[layer_name] += converted_length
        pipe_detail_rows.append(
            {
                "Category": category,
                "Handle": handle,
                "Layer": layer_name,
                "System": layer_name.replace("П_", "").strip(),
                "Entity Type": entity_type,
                "Raw Length": round(float(raw_length), 6),
                "Length (m)": round(float(converted_length), 6),
                "Diameter": diameter,
                "Diameter Source": diameter_source,
                "Reference Point": diameter_evidence["reference"],
                "Nearest Marker Label": diameter_evidence["marker_label"],
                "Nearest Marker Distance": diameter_evidence["marker_distance"],
                "Marker Threshold": diameter_evidence["marker_threshold"],
                "Diameter Evidence": diameter_evidence["reason"],
                "Status": status,
                "Reason": reason,
            }
        )

    equipment_counts = Counter()
    fitting_counts = Counter()
    valve_counts = Counter()

    for entity in entities:
        if entity.dxftype() != "INSERT":
            continue
        classification = _classify_dxf_insert(entity)
        if classification is None:
            continue
        category, label = classification
        if category == "EQUIPMENT":
            equipment_counts[label] += 1
        elif category == "FITTING":
            fitting_counts[label] += 1
        elif category == "VALVE":
            valve_counts[label] += 1

    pipe_rows = [
        {"Diameter": diameter, "Length (m)": round(total, 6)}
        for diameter, total in sorted(pipes_by_diameter.items(), key=lambda item: item[0])
    ]
    if not pipe_rows:
        pipe_rows = [{"Diameter": "UNKNOWN", "Length (m)": 0.0}]

    total_pipe_length = math.fsum(value for value in pipes_by_diameter.values() if math.isfinite(value))
    raw_pipe_length = math.fsum(value for value in layer_raw_length.values() if math.isfinite(value))
    duplicate_raw_length = math.fsum(value for value in layer_duplicate_raw_length.values() if math.isfinite(value))
    raw_prefixed_pipe_length = math.fsum(
        convert_length(measure_entity(entity)[0], meters_per_unit)
        for entity in raw_prefixed_pipe_geometry_entities
    )
    excluded_pipe_length = math.fsum(
        convert_length(measure_entity(entity)[0], meters_per_unit)
        for entity in excluded_pipe_geometry_entities
    )
    pipe_by_diameter_rows = []
    for row in pipe_rows:
        length_value = float(row.get("Length (m)") or 0.0)
        percentage = (length_value / total_pipe_length * 100.0) if total_pipe_length > 0 else 0.0
        pipe_by_diameter_rows.append(
            {
                "Diameter": row["Diameter"],
                "Length (m)": round(length_value, 6),
                "Percentage": round(percentage, 2),
            }
        )

    category_summary = defaultdict(float)
    for row in pipe_detail_rows:
        category_summary[(row.get("Category", "UNKNOWN"), row.get("Diameter", "UNKNOWN"))] += float(row.get("Length (m)") or 0.0)
    category_diameter_rows = [
        {"Category": category, "Diameter": diameter, "Length (m)": round(total, 6)}
        for (category, diameter), total in sorted(category_summary.items(), key=lambda item: (item[0][0], item[0][1]))
    ]

    category_totals = defaultdict(float)
    for row in pipe_detail_rows:
        category_totals[row.get("Category", "UNKNOWN")] += float(row.get("Length (m)") or 0.0)
    summary_by_category = {
        "X": category_totals.get("X", 0.0),
        "Z": category_totals.get("Z", 0.0),
        "UNKNOWN": category_totals.get("UNKNOWN", 0.0),
    }

    equipment_rows = [{"Type": key, "Quantity": value} for key, value in sorted(equipment_counts.items())]
    if not equipment_rows:
        equipment_rows = [{"Type": "NOT DETECTED", "Quantity": 0}]

    fittings_rows = [{"Type": key, "Quantity": value} for key, value in sorted(fitting_counts.items())]
    if not fittings_rows:
        fittings_rows = [{"Type": "NOT DETECTED", "Quantity": 0}]

    valves_rows = [{"Type": key, "Quantity": value} for key, value in sorted(valve_counts.items())]
    if not valves_rows:
        valves_rows = [{"Type": "NOT DETECTED", "Quantity": 0}]

    layers_rows = [
        {
            "Layer": layer_name,
            "Entity Count": count,
            "Measured Length (m)": round(layer_measured_length.get(layer_name, 0.0), 6),
            "Duplicates Removed": int(layer_duplicate_count.get(layer_name, 0)),
            "Duplicate Length": round(layer_duplicate_raw_length.get(layer_name, 0.0), 6),
            "Raw Length": round(layer_raw_length.get(layer_name, 0.0), 6),
            "Final Length": round(layer_measured_length.get(layer_name, 0.0), 6),
            "Unique Entities Measured": int(sum(1 for entity in unique_pipe_entities if _dxf_layer_name(entity) == layer_name)),
        }
        for layer_name, count in sorted(layer_counts.items(), key=lambda item: (layer_measured_length.get(item[0], 0.0), item[1]), reverse=True)
    ]

    unknown_review_rows = [
        {
            "Category": row.get("Category", "UNKNOWN"),
            "Handle": row["Handle"],
            "Layer": row["Layer"],
            "Entity Type": row["Entity Type"],
            "Raw Length": row["Raw Length"],
            "Length (m)": row["Length (m)"],
            "Diameter": row["Diameter"],
            "Diameter Source": row["Diameter Source"],
            "Reference Point": row["Reference Point"],
            "Nearest Marker Label": row["Nearest Marker Label"],
            "Nearest Marker Distance": row["Nearest Marker Distance"],
            "Marker Threshold": row["Marker Threshold"],
            "Diameter Evidence": row["Diameter Evidence"],
            "Reason": row["Reason"],
            "Status": row["Status"],
        }
        for row in pipe_detail_rows
        if row["Status"] == "UNKNOWN"
    ]

    _validate_pipe_invariants(total_pipe_length, pipe_rows, pipe_detail_rows, pipe_entity_count)

    debug = {
        "raw_entities": raw_entity_count,
        "pipe_layer_raw_entities": len(raw_pipe_layer_entities),
        "after_auxiliary_filter": len(after_auxiliary_filter),
        "duplicate_candidates": duplicate_candidates,
        "duplicate_entities_by_layer": dict(layer_duplicate_count),
        "duplicate_raw_length_by_layer": dict(layer_duplicate_raw_length),
        "raw_length_by_layer": dict(layer_raw_length),
        "raw_pipe_length": raw_pipe_length,
        "raw_prefixed_pipe_length": raw_prefixed_pipe_length,
        "excluded_pipe_geometry_count": len(excluded_pipe_geometry_entities),
        "excluded_pipe_geometry_length": excluded_pipe_length,
        "duplicate_raw_length": duplicate_raw_length,
        "final_pipe_length": total_pipe_length,
        "reconciliation_difference": raw_prefixed_pipe_length - excluded_pipe_length - duplicate_raw_length - total_pipe_length,
        "real_pipe_entities": pipe_entity_count,
        "identified_dn_count": sum(1 for row in pipe_rows if row["Diameter"] != "UNKNOWN"),
        "unknown_dn_count": sum(1 for row in pipe_rows if row["Diameter"] == "UNKNOWN"),
        "x_total_length": summary_by_category["X"],
        "z_total_length": summary_by_category["Z"],
        "unknown_category_length": summary_by_category["UNKNOWN"],
        "notes": [
            "Only DXF entities on pipe layers with measurable LINE/LWPOLYLINE/POLYLINE/ARC geometry are treated as candidate pipe runs.",
            "Closed polylines and non-pipe auxiliary geometry remain excluded unless explicitly supported by the real DXF evidence.",
            "Duplicate detection is logged conservatively and does not guess a diameter.",
        ],
    }

    return {
        "summary": {
            "total_pipe_length": total_pipe_length,
            "raw_pipe_length": raw_pipe_length,
            "raw_prefixed_pipe_length": raw_prefixed_pipe_length,
            "excluded_pipe_geometry_count": len(excluded_pipe_geometry_entities),
            "excluded_pipe_geometry_length": excluded_pipe_length,
            "duplicate_raw_length": duplicate_raw_length,
            "final_pipe_length": total_pipe_length,
            "duplicate_entity_count": int(sum(layer_duplicate_count.values())),
            "raw_pipe_entity_count": len(raw_pipe_layer_entities),
            "final_pipe_entity_count": pipe_entity_count,
            "pipe_entity_count": pipe_entity_count,
            "equipment_count": int(sum(equipment_counts.values())),
            "fittings_count": int(sum(fitting_counts.values())),
            "valves_count": int(sum(valve_counts.values())),
            "x_total_length": summary_by_category["X"],
            "z_total_length": summary_by_category["Z"],
            "unknown_category_length": summary_by_category["UNKNOWN"],
        },
        "pipe_rows": pipe_rows,
        "pipe_by_diameter_rows": pipe_by_diameter_rows,
        "pipe_detail_rows": pipe_detail_rows,
        "category_diameter_rows": category_diameter_rows,
        "unknown_review_rows": unknown_review_rows,
        "equipment_rows": equipment_rows,
        "fittings_rows": fittings_rows,
        "valves_rows": valves_rows,
        "layers_rows": layers_rows,
        "debug": debug,
    }


def plot_selected_layer(entities) -> None:
    if not entities:
        st.info("Для этого слоя нет геометрии для предпросмотра.")
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    drawn = False

    for entity in entities:
        for segment in approximate_entity_segments(entity):
            if len(segment) < 2:
                continue
            xs = [point[0] for point in segment]
            ys = [point[1] for point in segment]
            ax.plot(xs, ys, linewidth=1.2)
            drawn = True

    if not drawn:
        st.info("В выбранном слое нет геометрии для предпросмотра.")
        return

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Геометрия выбранного слоя")
    ax.grid(True, alpha=0.3)
    st.pyplot(fig, clear_figure=True)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    runtime_dirs = ensure_runtime_dirs()

    st.title(APP_TITLE)
    st.subheader(APP_SUBTITLE)

    with st.sidebar:
        st.header("Локальная настройка")
        st.caption("Всё хранится локально. V0 работает в первую очередь с DXF.")
        if not EZDWG_AVAILABLE:
            st.warning("DWG support is optional and disabled in this environment. DXF workflow remains active for deployment.")
        st.session_state["unit_override"] = st.selectbox(
            "Единицы измерения",
            ["Auto", "mm", "cm", "m", "inches", "feet", "unknown"],
            index=["Auto", "mm", "cm", "m", "inches", "feet", "unknown"].index(st.session_state.get("unit_override", "Auto")),
            format_func=lambda value: {
                "Auto": "Авто",
                "mm": "мм",
                "cm": "см",
                "m": "м",
                "inches": "дюймы",
                "feet": "футы",
                "unknown": "не определено",
            }[value],
        )
        st.session_state["remove_duplicate_geometry"] = st.checkbox(
            "Remove duplicate geometry (recommended)",
            value=st.session_state.get("remove_duplicate_geometry", True),
        )

    uploaded_file = st.file_uploader("Загрузить DXF", type=["dxf"])

    if uploaded_file is None:
        st.info("Загрузите DXF-файл для расчёта метража.")
        return

    current_signature = file_signature(uploaded_file.getvalue())
    if st.session_state.get("upload_signature") != current_signature:
        st.session_state["upload_signature"] = current_signature
        st.session_state["upload_name"] = uploaded_file.name
        reset_analysis()

    st.success(f"Файл: {uploaded_file.name}")
    st.write("Статус: готово")

    source_path = Path(st.session_state["source_path"]) if st.session_state.get("source_path") else None
    if source_path is None or source_path.name != uploaded_file.name:
        try:
            source_path = load_uploaded_file(uploaded_file, runtime_dirs)
            st.session_state["source_path"] = str(source_path)
        except Exception:
            st.error("Не удалось сохранить загруженный файл.")
            return

    if st.button("Загрузить чертёж", type="primary") or st.session_state.get("drawing_doc") is None:
        try:
            _, doc, insunits = prepare_document(source_path, runtime_dirs)
            if source_path.suffix.lower() == ".dwg":
                st.success("DWG загружен локально через ezdwg.")
            else:
                st.success("DXF успешно загружен.")
        except Exception:
            if source_path.suffix.lower() == ".dwg":
                st.error("DWG не удалось прочитать локально.")
            else:
                st.error("Не удалось обработать DXF-файл.")
            return

    drawing_kind = st.session_state.get("drawing_kind")
    doc = st.session_state.get("drawing_doc")
    if doc is None:
        st.warning("Загруженный чертёж отсутствует.")
        return

    insunits = st.session_state.get("insunits") or {"label": "unknown", "meters_per_unit": None, "known": False}
    unit_label, meters_per_unit, overridden = get_effective_unit(insunits, st.session_state.get("unit_override", "Auto"))

    st.markdown(f"**Единицы чертежа:** {insunits.get('label', 'unknown').title()}")
    if not insunits.get("known") and st.session_state.get("unit_override") == "Auto":
        st.warning("Единицы чертежа не определены. До ручного выбора расчёт будет в единицах чертежа.")

    layers_table = st.session_state.get("layers_table") or (build_layer_table(doc) if drawing_kind != "dwg" else [])
    layers_df = pd.DataFrame(layers_table)
    st.write(f"Найдено слоёв: {len(layers_df)}")

    if drawing_kind == "dwg" and not layers_df.empty and {"Handle", "Resolved Name"}.issubset(layers_df.columns):
        st.dataframe(
            layers_df[["Layer", "Handle", "Resolved Name", "Object Count"]].rename(
                columns={"Layer": "Слой", "Handle": "Идентификатор", "Resolved Name": "Разрешённое имя", "Object Count": "Количество объектов"}
            ),
            use_container_width=True,
            hide_index=True,
        )
    elif not layers_df.empty:
        st.dataframe(
            layers_df[["Layer", "Object Count"]].rename(columns={"Layer": "Слой", "Object Count": "Количество объектов"}),
            use_container_width=True,
            hide_index=True,
        )

    if layers_df.empty and drawing_kind != "dwg":
        st.warning("Чертёж пуст.")
        return

    layer_options = layers_df["Layer"].tolist() if not layers_df.empty else ["Все"]
    default_layer = st.session_state.get("selected_layer") or layer_options[0]
    selected_layer = st.selectbox("Выберите слой", layer_options, index=layer_options.index(default_layer) if default_layer in layer_options else 0)
    st.session_state["selected_layer"] = selected_layer

    if drawing_kind == "dwg":
        report_key = (st.session_state.get("unit_override", "Auto"), insunits.get("code"))
        if st.button("Рассчитать метраж") or st.session_state.get("dwg_report") is None or st.session_state.get("dwg_report_key") != report_key:
            try:
                dwg_entities = st.session_state.get("dwg_entities")
                if dwg_entities is None:
                    dwg_entities = get_dwg_entities(doc)
                    st.session_state["dwg_entities"] = dwg_entities
                st.session_state["dwg_report"] = calculate_dwg_quantities(dwg_entities, unit_label, meters_per_unit)
                st.session_state["dwg_report_key"] = report_key
            except Exception:
                st.error("Не удалось выполнить расчёт DWG-метража.")
                return

        report = st.session_state["dwg_report"]
        display_unit = "m" if meters_per_unit is not None else unit_label
        layers_out_df = pd.DataFrame(report["layers_rows"])

        st.markdown("### Общий результат")
        st.metric("Общая длина труб", f"{report['summary']['total_pipe_length']:,.2f} {display_unit}")
        st.write(f"Оборудование: {report['summary']['equipment_count']}")
        st.write(f"Фитинги: {report['summary']['fittings_count']}")
        st.write(f"Клапаны: {report['summary']['valves_count']}")

        st.markdown("### Трубы по диаметрам")
        pipes_df = pd.DataFrame(report["pipes_rows"])
        st.dataframe(pipes_df, use_container_width=True, hide_index=True)

        st.markdown("### Оборудование")
        equipment_df = pd.DataFrame(report["equipment_rows"])
        st.dataframe(equipment_df, use_container_width=True, hide_index=True)

        st.markdown("### Фитинги")
        fittings_df = pd.DataFrame(report["fittings_rows"])
        st.dataframe(fittings_df, use_container_width=True, hide_index=True)

        st.markdown("### Клапаны")
        valves_df = pd.DataFrame(report["valves_rows"])
        st.dataframe(valves_df, use_container_width=True, hide_index=True)

        st.markdown("### Слои")
        st.dataframe(layers_out_df, use_container_width=True, hide_index=True)

        st.markdown("### Предпросмотр геометрии")
        selected_entities = [entity for entity in (st.session_state.get("dwg_entities") or []) if _dwg_layer_label(entity) == selected_layer]
        plot_dwg_selected_layer(selected_entities)

        excel_bytes = build_takeoff_excel(
            file_name=uploaded_file.name,
            summary_rows=[
                {
                    "Total Pipe Length": round(report["summary"]["total_pipe_length"], 6),
                    "Pipe Unit": display_unit,
                    "Equipment Count": report["summary"]["equipment_count"],
                    "Fittings Count": report["summary"]["fittings_count"],
                    "Valves Count": report["summary"]["valves_count"],
                }
            ],
            pipes_rows=report["pipes_rows"],
            equipment_rows=report["equipment_rows"],
            fittings_rows=report["fittings_rows"],
            valves_rows=report["valves_rows"],
            layers_rows=layers_out_df.to_dict(orient="records"),
        )

        st.download_button(
            "Скачать Excel",
            data=excel_bytes,
            file_name="takeoff_result.xlsx",
            key="download_takeoff_excel_dwg_v0",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    elif drawing_kind == "dxf":
        report_key = (
            uploaded_file.name,
            st.session_state.get("unit_override", "Auto"),
            insunits.get("code"),
            st.session_state.get("remove_duplicate_geometry", True),
        )
        if st.button("Рассчитать MEP метраж", type="primary") or st.session_state.get("dxf_report") is None or st.session_state.get("dxf_report_key") != report_key:
            try:
                st.session_state["dxf_report"] = calculate_dxf_quantities(
                    doc,
                    unit_label,
                    meters_per_unit,
                    st.session_state.get("remove_duplicate_geometry", True),
                )
                st.session_state["dxf_report_key"] = report_key
            except Exception:
                st.error("Не удалось рассчитать MEP-метраж для DXF.")
                return

        report = st.session_state["dxf_report"]
        display_unit = "m" if meters_per_unit is not None else unit_label

        st.markdown("### Общий результат")
        st.metric("Общая длина труб", f"{report['summary']['total_pipe_length']:,.2f} {display_unit}")
        st.write(f"Количество труб: {report['summary']['pipe_entity_count']}")
        st.write(f"Оборудование: {report['summary']['equipment_count']}")
        st.write(f"Фитинги: {report['summary']['fittings_count']}")
        st.write(f"Клапаны: {report['summary']['valves_count']}")

        st.markdown("### Метод расчёта")
        st.write("Общая длина труб: сумма измеряемой DXF-геометрии трубных объектов.")
        st.write("Единицы: миллиметры → метры по INSUNITS чертежа.")
        st.write("Диаметр: определяется по доступным маркерам DXF и детерминированной связи с геометрией.")
        st.write("Неопределённые значения: не угадываются и помещаются в UNKNOWN.")

        st.markdown("### Трубы по диаметрам")
        pipes_df = pd.DataFrame(report["pipe_by_diameter_rows"])
        if pipes_df.empty:
            st.info("Не обнаружено")
        else:
            st.dataframe(
                pipes_df[["Diameter", "Length (m)"]],
                use_container_width=True,
                hide_index=True,
            )

        if "UNKNOWN" in set(pipes_df.get("Diameter", [])):
            st.info("UNKNOWN означает, что геометрия DXF или метаданные слоя не дали надёжного соответствия диаметру.")

        pipe_detail_df = pd.DataFrame(report["pipe_detail_rows"])
        if not pipe_detail_df.empty:
            st.markdown("### Детальная таблица труб")
            st.dataframe(
                pipe_detail_df[["Diameter", "Length (m)", "Handle", "Layer", "Entity Type", "Diameter Source", "Status", "Reason"]],
                use_container_width=True,
                hide_index=True,
            )

        unknown_df = pd.DataFrame(report.get("unknown_review_rows", []))
        if not unknown_df.empty:
            st.markdown("### UNKNOWN REVIEW")
            st.write(f"Unknown objects: {len(unknown_df)}")
            st.write(f"Unknown length: {float(unknown_df['Length (m)'].sum()):.6f} m")
            st.dataframe(
                unknown_df[["Handle", "Layer", "Entity Type", "Length (m)", "Reason", "Status"]],
                use_container_width=True,
                hide_index=True,
            )

        layer_report_key = (
            uploaded_file.name,
            selected_layer,
            st.session_state.get("unit_override", "Auto"),
            insunits.get("code"),
            st.session_state.get("remove_duplicate_geometry", True),
        )
        if st.session_state.get("dxf_layer_calculation") is None or st.session_state.get("dxf_layer_calculation_key") != layer_report_key:
            try:
                st.session_state["dxf_layer_calculation"] = calculate_layer(
                    doc,
                    selected_layer,
                    unit_label,
                    meters_per_unit,
                    st.session_state.get("remove_duplicate_geometry", True),
                )
                st.session_state["dxf_layer_calculation_key"] = layer_report_key
            except Exception:
                st.error("Не удалось выполнить расчёт по выбранному слою.")
                return

        layer_calculation = st.session_state["dxf_layer_calculation"]
        st.markdown("### Анализ выбранного слоя")
        st.write(f"Выбранный слой: {selected_layer}")
        st.write(f"Количество объектов: {layer_calculation['total_entities']}")
        st.write(f"Дубликаты удалены: {layer_calculation['duplicate_entities']} ({layer_calculation['duplicate_raw_length']:,.6f} raw)")
        st.write(f"Уникальные измеренные объекты: {layer_calculation['measurable_entities']}")
        st.write(f"Raw длина: {layer_calculation['raw_total_length']:,.6f}")
        st.write(f"Final длина: {layer_calculation['final_total_length']:,.6f} {display_unit}")
        if layer_calculation["measurable_entities"] == 0:
            st.warning("В выбранном слое нет измеримой геометрии.")
        else:
            st.metric("Общая геометрическая длина", f"{layer_calculation['total_length']:,.2f} {display_unit}")
            st.write(f"Измеряемые объекты: {layer_calculation['measurable_entities']}")
            st.write(f"Игнорируемые объекты: {layer_calculation['ignored_count']}")
            st.write(f"Круги: {layer_calculation['circle_count']}")
            layer_counts = layer_calculation["type_counts"]
            st.write(
                f"LINE: {layer_counts.get('LINE', 0)} | LWPOLYLINE: {layer_counts.get('LWPOLYLINE', 0)} | POLYLINE: {layer_counts.get('POLYLINE', 0)} | ARC: {layer_counts.get('ARC', 0)} | CIRCLE: {layer_counts.get('CIRCLE', 0)}"
            )

        details_df = pd.DataFrame(layer_calculation["detail_rows"])
        if not details_df.empty:
            st.markdown("### Детальная таблица")
            st.dataframe(
                details_df.rename(columns={"Object ID": "ID объекта", "Layer": "Слой", "Entity Type": "Тип объекта", "Length": "Длина", "Unit": "Единица"}),
                use_container_width=True,
                hide_index=True,
            )
            st.write(f"ИТОГО = {layer_calculation['total_length']:,.2f} {display_unit}")
        else:
            st.info("Измеримые объекты отсутствуют")

        st.markdown("### Предпросмотр геометрии")
        plot_selected_layer(get_layer_entities(doc, selected_layer))

        excel_bytes = build_takeoff_excel(
            file_name=uploaded_file.name,
            summary_rows=[
                {
                    "Total Pipe Length (m)": round(report["summary"]["total_pipe_length"], 6),
                    "Pipe Entities": report["summary"]["pipe_entity_count"],
                    "Equipment Count": report["summary"]["equipment_count"],
                    "Fittings Count": report["summary"]["fittings_count"],
                    "Valves Count": report["summary"]["valves_count"],
                    "Unit": display_unit,
                    "Duplicates Removed": sum(report["debug"].get("duplicate_entities_by_layer", {}).values()),
                    "Duplicate Length": round(report["summary"].get("duplicate_raw_length", 0.0), 6),
                    "Raw Length": round(report["summary"].get("raw_prefixed_pipe_length", 0.0), 6),
                    "Excluded Entities": report["summary"].get("excluded_pipe_geometry_count", 0),
                    "Excluded Length": round(report["summary"].get("excluded_pipe_geometry_length", 0.0), 6),
                    "Final Length": round(report["summary"]["total_pipe_length"], 6),
                }
            ],
            pipe_by_diameter_rows=report["pipe_by_diameter_rows"],
            pipes_rows=report["pipe_rows"],
            pipes_detail_rows=report["pipe_detail_rows"],
            equipment_rows=report["equipment_rows"],
            fittings_rows=report["fittings_rows"],
            valves_rows=report["valves_rows"],
            layers_rows=report["layers_rows"],
            details=layer_calculation["detail_rows"],
            layer_name=selected_layer,
            details_duplicate_count=layer_calculation["duplicate_entities"],
            details_duplicate_raw_length=layer_calculation["duplicate_raw_length"],
            details_duplicate_converted_length=layer_calculation["duplicate_converted_length"],
            object_type_rows=layer_calculation["object_type_rows"],
            unknown_review_rows=report.get("unknown_review_rows", []),
        )

        st.download_button(
            "Скачать Excel",
            data=excel_bytes,
            file_name="takeoff_result.xlsx",
            key="download_takeoff_excel_dxf_v0",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.warning("Поддерживаемый формат чертежа не распознан.")
        return


if __name__ == "__main__":
    main()