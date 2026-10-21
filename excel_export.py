from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd


def build_takeoff_excel(
    *,
    file_name: str,
    layer_name: str | None = None,
    object_count: int | None = None,
    total_length: float | None = None,
    unit_label: str | None = None,
    details: list[dict[str, Any]] | None = None,
    object_type_rows: list[dict[str, Any]] | None = None,
    summary_rows: list[dict[str, Any]] | None = None,
    pipe_by_diameter_rows: list[dict[str, Any]] | None = None,
    pipes_rows: list[dict[str, Any]] | None = None,
    pipes_detail_rows: list[dict[str, Any]] | None = None,
    equipment_rows: list[dict[str, Any]] | None = None,
    fittings_rows: list[dict[str, Any]] | None = None,
    valves_rows: list[dict[str, Any]] | None = None,
    layers_rows: list[dict[str, Any]] | None = None,
    unknown_review_rows: list[dict[str, Any]] | None = None,
    category_diameter_rows: list[dict[str, Any]] | None = None,
    details_duplicate_count: int = 0,
    details_duplicate_raw_length: float = 0.0,
    details_duplicate_converted_length: float = 0.0,
    warning_rows: list[dict[str, Any]] | None = None,
    unsupported_rows: list[dict[str, Any]] | None = None,
    length_unit_known: bool = True,
) -> bytes:
    length_unit_ru = "м" if length_unit_known else "ед. чертежа"
    length_column = f"Длина ({length_unit_ru})"
    measured_length_column = f"Измеренная длина ({length_unit_ru})"
    english_length_column = "Length (m)" if length_unit_known else "Length (drawing units)"

    summary_df = pd.DataFrame(summary_rows) if summary_rows is not None else pd.DataFrame(
        [
            {
                "Файл": file_name,
                "Слой": layer_name,
                "Количество объектов": object_count,
                "Общая длина": total_length,
                "Единица": unit_label,
                "Duplicates Removed": 0,
                "Duplicate Length": 0.0,
                "Raw Length": total_length,
                "Excluded Entities": 0,
                "Excluded Length": 0.0,
                "Final Length": total_length,
            }
        ]
    )
    for column in (
        "Duplicates Removed",
        "Duplicate Length",
        "Raw Length",
        "Excluded Entities",
        "Excluded Length",
        "Final Length",
    ):
        if column not in summary_df.columns:
            summary_df[column] = 0

    if details is not None:
        details_df = pd.DataFrame(details)
        if details_df.empty:
            details_df = pd.DataFrame(columns=["ID объекта", "Слой", "Тип объекта", "Длина", "Единица"])
        else:
            details_df = details_df.rename(columns={"Object ID": "ID объекта", "Layer": "Слой", "Entity Type": "Тип объекта", "Length": "Длина", "Unit": "Единица"})
        details_df = pd.concat(
            [
                details_df,
                pd.DataFrame(
                    [
                        {
                            "ID объекта": "SUMMARY",
                            "Слой": layer_name or "",
                            "Тип объекта": "DUPLICATES EXCLUDED",
                            "Raw Length": round(details_duplicate_raw_length, 6),
                            "Длина": round(details_duplicate_converted_length, 6),
                            "Единица": f"{details_duplicate_count} duplicate entities excluded",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    else:
        details_df = pd.DataFrame()

    if object_type_rows is not None:
        types_df = pd.DataFrame(object_type_rows)
        if types_df.empty:
            types_df = pd.DataFrame(columns=["Тип объекта", "Количество", "Общая длина"])
        else:
            types_df = types_df.rename(columns={"Entity Type": "Тип объекта", "Count": "Количество", "Total Length": "Общая длина"})
    else:
        types_df = pd.DataFrame()

    pipe_by_diameter_df = pd.DataFrame(pipe_by_diameter_rows or [])
    if pipe_by_diameter_df.empty:
        pipe_by_diameter_df = pd.DataFrame(columns=["Диаметр", length_column, "Процент"])
    else:
        pipe_by_diameter_df = pipe_by_diameter_df.rename(columns={"Diameter": "Диаметр", "Length": length_column, "Length (m)": length_column, "Percentage": "Процент"})
        if "Процент" not in pipe_by_diameter_df.columns:
            pipe_by_diameter_df["Процент"] = 0.0

    pipe_source_rows = pipes_detail_rows if pipes_detail_rows is not None else (pipes_rows or [])
    pipes_df = pd.DataFrame(pipe_source_rows)
    if pipes_df.empty:
        pipes_df = pd.DataFrame(columns=["Слой", "Система", "Диаметр", "Тип объекта", length_column])
    else:
        pipes_df = pipes_df.rename(columns={"Layer": "Слой", "System": "Система", "Diameter": "Диаметр", "Entity Type": "Тип объекта", "Length": length_column, "Length (m)": length_column})
        if "Тип объекта" not in pipes_df.columns:
            pipes_df["Тип объекта"] = ""
        if length_column not in pipes_df.columns:
            pipes_df[length_column] = 0.0

    equipment_df = pd.DataFrame(equipment_rows or [])
    if equipment_df.empty:
        equipment_df = pd.DataFrame(columns=["Тип", "Количество"])
    else:
        equipment_df = equipment_df.rename(columns={"Type": "Тип", "Quantity": "Количество"})

    fittings_df = pd.DataFrame(fittings_rows or [])
    if fittings_df.empty:
        fittings_df = pd.DataFrame(columns=["Тип", "Диаметр", "Количество"])
    else:
        fittings_df = fittings_df.rename(columns={"Type": "Тип", "Diameter": "Диаметр", "Quantity": "Количество"})

    valves_df = pd.DataFrame(valves_rows or [])
    if valves_df.empty:
        valves_df = pd.DataFrame(columns=["Тип", "Диаметр", "Количество"])
    else:
        valves_df = valves_df.rename(columns={"Type": "Тип", "Diameter": "Диаметр", "Quantity": "Количество"})

    layers_df = pd.DataFrame(layers_rows or [])
    if layers_df.empty:
        layers_df = pd.DataFrame(columns=["Слой", "Количество объектов", measured_length_column])
    else:
        layers_df = layers_df.rename(columns={"Layer": "Слой", "Object Count": "Количество объектов", "Measured Length": measured_length_column, "Entity Count": "Количество объектов", "Measured Length (m)": measured_length_column})
        if "Количество объектов" not in layers_df.columns:
            layers_df["Количество объектов"] = 0
        if measured_length_column not in layers_df.columns:
            layers_df[measured_length_column] = 0.0

    category_diameter_df = pd.DataFrame(category_diameter_rows or [])
    if category_diameter_df.empty:
        category_diameter_df = pd.DataFrame(columns=["Category", "Diameter", english_length_column])
    else:
        category_diameter_df = category_diameter_df.rename(columns={"Category": "Category", "Diameter": "Diameter", "Length (m)": english_length_column})

    unknown_review_df = pd.DataFrame(unknown_review_rows or [])
    if unknown_review_df.empty:
        unknown_review_df = pd.DataFrame(columns=["Category", "Handle", "Layer", "Entity Type", "Raw Length", english_length_column, "Diameter", "Diameter Source", "Reason", "Status"])
    else:
        unknown_review_df = unknown_review_df.rename(columns={"Length (m)": english_length_column})

    warnings_df = None
    if warning_rows is not None:
        warnings_df = pd.DataFrame(warning_rows, columns=["Code", "Severity", "Count", "Message"])
    unsupported_df = None
    if unsupported_rows is not None:
        unsupported_df = pd.DataFrame(unsupported_rows, columns=["Layer", "Entity Type", "Count", "Handles"])

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="СВОДКА", index=False)
        category_diameter_df.to_excel(writer, sheet_name="CATEGORY_DIAMETER", index=False)
        pipe_by_diameter_df.to_excel(writer, sheet_name="ПО ДИАМЕТРУ", index=False)
        pipes_df.to_excel(writer, sheet_name="ТРУБЫ", index=False)
        equipment_df.to_excel(writer, sheet_name="ОБОРУДОВАНИЕ", index=False)
        fittings_df.to_excel(writer, sheet_name="ФИТИНГИ", index=False)
        valves_df.to_excel(writer, sheet_name="КЛАПАНЫ", index=False)
        layers_df.to_excel(writer, sheet_name="СЛОИ", index=False)
        if not details_df.empty:
            details_df.to_excel(writer, sheet_name="ДЕТАЛИ", index=False)
        if not types_df.empty:
            types_df.to_excel(writer, sheet_name="ТИПЫ ОБЪЕКТОВ", index=False)
        unknown_review_df.to_excel(writer, sheet_name="UNKNOWN_REVIEW", index=False)
        if warnings_df is not None:
            warnings_df.to_excel(writer, sheet_name="ПРЕДУПРЕЖДЕНИЯ", index=False)
        if unsupported_df is not None:
            unsupported_df.to_excel(writer, sheet_name="НЕ ИЗМЕРЕНО", index=False)

    return buffer.getvalue()


def save_takeoff_excel(
    output_path: str | Path,
    **kwargs: Any,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_takeoff_excel(**kwargs))
    return output_path