from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd


def build_takeoff_excel(
    *,
    file_name: str,
    layer_name: str,
    object_count: int,
    total_length: float,
    unit_label: str,
    details: list[dict[str, Any]],
    object_type_rows: list[dict[str, Any]],
) -> bytes:
    summary_df = pd.DataFrame(
        [
            {
                "File": file_name,
                "Layer": layer_name,
                "Object Count": object_count,
                "Total Length": total_length,
                "Unit": unit_label,
            }
        ]
    )

    details_df = pd.DataFrame(details)
    if details_df.empty:
        details_df = pd.DataFrame(columns=["Object ID", "Layer", "Entity Type", "Length", "Unit"])

    types_df = pd.DataFrame(object_type_rows)
    if types_df.empty:
        types_df = pd.DataFrame(columns=["Entity Type", "Count", "Total Length"])

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="SUMMARY", index=False)
        details_df.to_excel(writer, sheet_name="DETAILS", index=False)
        types_df.to_excel(writer, sheet_name="OBJECT TYPES", index=False)

    return buffer.getvalue()


def save_takeoff_excel(
    output_path: str | Path,
    **kwargs: Any,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_takeoff_excel(**kwargs))
    return output_path