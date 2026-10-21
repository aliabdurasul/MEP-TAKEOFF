"""Report what the DXF takeoff does not measure.

These functions only describe skipped entities, external references and unit
status so the user can review them; they never add, remove or estimate quantities.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import Any

BLOCK_FLAG_XREF = 4
BLOCK_FLAG_XREF_OVERLAY = 8
MAX_LISTED_HANDLES = 20

LENGTH_UNIT_METRES = "m"
LENGTH_UNIT_DRAWING = "drawing units"


def length_unit(meters_per_unit: float | None) -> str:
    return LENGTH_UNIT_METRES if meters_per_unit is not None else LENGTH_UNIT_DRAWING


def unsupported_pipe_entities(
    entities: Iterable[Any],
    *,
    is_pipe_layer: Callable[[str], bool],
    layer_of: Callable[[Any], str],
    is_measured: Callable[[Any], bool],
) -> list[dict[str, Any]]:
    """Group entities on included pipe layers that the takeoff does not measure."""

    handles_by_group: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entity in entities:
        layer = layer_of(entity)
        if not is_pipe_layer(layer) or is_measured(entity):
            continue
        handles_by_group[(layer, entity.dxftype())].append(str(entity.dxf.handle))

    rows = []
    for (layer, entity_type), handles in sorted(handles_by_group.items()):
        listed = ", ".join(handles[:MAX_LISTED_HANDLES])
        if len(handles) > MAX_LISTED_HANDLES:
            listed += f", … (+{len(handles) - MAX_LISTED_HANDLES})"
        rows.append({"Layer": layer, "Entity Type": entity_type, "Count": len(handles), "Handles": listed})
    return rows


def external_references(doc: Any) -> list[dict[str, Any]]:
    """List XREF block definitions and how often each is inserted in model space."""

    insert_counts = Counter(str(entity.dxf.name) for entity in doc.modelspace().query("INSERT"))
    rows = []
    for block_layout in doc.blocks:
        flags = int(_block_attribute(block_layout, "flags", 0) or 0)
        if not flags & BLOCK_FLAG_XREF:
            continue
        rows.append(
            {
                "Name": block_layout.name,
                "Path": str(_block_attribute(block_layout, "xref_path", "") or ""),
                "Model Space Inserts": insert_counts.get(block_layout.name, 0),
                "Overlay": bool(flags & BLOCK_FLAG_XREF_OVERLAY),
            }
        )
    return rows


def xref_dependent_layer_count(doc: Any) -> int:
    return sum(1 for layer in doc.layers if "|" in str(layer.dxf.name))


def _block_attribute(block_layout: Any, name: str, default: Any) -> Any:
    try:
        return block_layout.block.dxf.get(name, default)
    except Exception:
        return default


def takeoff_warnings(
    *,
    meters_per_unit: float | None,
    pipe_entity_count: int,
    pipe_layers_label: str,
    unsupported_rows: list[dict[str, Any]],
    xref_rows: list[dict[str, Any]],
    xref_layer_count: int,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    if meters_per_unit is None:
        warnings.append(
            {
                "Code": "UNKNOWN_UNITS",
                "Severity": "warning",
                "Count": None,
                "Message": (
                    "Единицы чертежа не определены: все длины указаны в единицах чертежа, а не в метрах. "
                    "Перевод в метры не выполнен — выберите единицы вручную."
                ),
            }
        )

    if pipe_entity_count == 0:
        warnings.append(
            {
                "Code": "NO_PIPE_GEOMETRY",
                "Severity": "warning",
                "Count": 0,
                "Message": (
                    f"На трубных слоях ({pipe_layers_label}) не найдено измеряемой геометрии "
                    "(LINE, LWPOLYLINE, POLYLINE, ARC). Метраж труб не рассчитан."
                ),
            }
        )

    if unsupported_rows:
        total = sum(int(row["Count"]) for row in unsupported_rows)
        by_type: Counter = Counter()
        for row in unsupported_rows:
            by_type[row["Entity Type"]] += int(row["Count"])
        types = ", ".join(f"{entity_type}: {count}" for entity_type, count in sorted(by_type.items()))
        layers = ", ".join(sorted({str(row["Layer"]) for row in unsupported_rows}))
        warnings.append(
            {
                "Code": "UNSUPPORTED_PIPE_ENTITIES",
                "Severity": "warning",
                "Count": total,
                "Message": (
                    f"На трубных слоях {total} объект(ов) не измерены и не включены в метраж: {types}. "
                    f"Слои: {layers}. Требуется ручная проверка."
                ),
            }
        )

    if xref_rows:
        references = ", ".join(
            f"{row['Name']} ({row['Path'] or 'путь не указан'}, вставок в модели: {row['Model Space Inserts']})"
            for row in xref_rows
        )
        layer_note = f" Слоёв из XREF: {xref_layer_count}." if xref_layer_count else ""
        warnings.append(
            {
                "Code": "XREF_NOT_PROCESSED",
                "Severity": "warning",
                "Count": len(xref_rows),
                "Message": (
                    f"Чертёж содержит внешние ссылки (XREF): {references}. "
                    f"Их содержимое не обрабатывается и не входит в метраж.{layer_note}"
                ),
            }
        )

    return warnings
