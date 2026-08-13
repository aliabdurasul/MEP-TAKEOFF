from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from dwg_converter import convert_dwg_to_dxf, is_available
from dxf_reader import get_layer_entities, layer_entity_counts, open_dxf, read_insunits, summarize_layer
from excel_export import build_takeoff_excel
from geometry import MeasurementRow, approximate_entity_segments, convert_length, measure_entity


APP_TITLE = "DWG Layer Quantity Calculator"
APP_SUBTITLE = "Calculate total geometric length by CAD layer"

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
    "mm": "Millimeters",
    "cm": "Centimeters",
    "m": "Meters",
    "inches": "Inches",
    "feet": "Feet",
    "unknown": "Unknown",
    "drawing units": "Drawing Units",
}


def init_state() -> None:
    defaults = {
        "upload_signature": None,
        "upload_name": None,
        "source_path": None,
        "converted_path": None,
        "dxf_doc": None,
        "insunits": None,
        "layers_table": None,
        "calculation": None,
        "calculation_key": None,
        "selected_layer": None,
        "oda_path": "",
        "unit_override": "Auto",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_analysis() -> None:
    st.session_state["dxf_doc"] = None
    st.session_state["insunits"] = None
    st.session_state["layers_table"] = None
    st.session_state["calculation"] = None
    st.session_state["calculation_key"] = None
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

    return "Drawing Units", None, False


def prepare_document(file_path: Path, runtime_dirs: dict[str, Path]) -> tuple[Path, object, dict]:
    suffix = file_path.suffix.lower()
    if suffix == ".dwg":
        if not is_available(st.session_state.get("oda_path")):
            raise FileNotFoundError("DWG converter not found. Please install ODA File Converter.")
        converted = convert_dwg_to_dxf(file_path, st.session_state.get("oda_path"), runtime_dirs["converted"])
        st.session_state["converted_path"] = str(converted)
        dxf_path = converted
    else:
        dxf_path = file_path

    doc = open_dxf(dxf_path)
    insunits = read_insunits(doc)
    st.session_state["dxf_doc"] = doc
    st.session_state["insunits"] = insunits
    st.session_state["source_path"] = str(file_path)
    return dxf_path, doc, insunits


def build_layer_table(doc) -> list[dict]:
    return layer_entity_counts(doc)


def calculate_layer(doc, layer_name: str, display_unit_label: str, meters_per_unit: float | None) -> dict:
    entities = get_layer_entities(doc, layer_name)
    type_counts = Counter(entity.dxftype() for entity in entities)
    measurement_rows = []
    object_type_totals = defaultdict(lambda: {"Count": 0, "Total Length": 0.0})

    detail_rows = []
    measurable_count = 0
    circle_count = int(type_counts.get("CIRCLE", 0))
    ignored_count = 0
    object_id = 1

    for entity in entities:
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
                    "Object ID": object_id,
                    "Layer": layer_name,
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
        "measurable_entities": measurable_count,
        "circle_count": circle_count,
        "ignored_count": ignored_count,
        "total_length": total_length,
        "detail_rows": detail_rows,
        "object_type_rows": object_type_rows,
        "measurement_rows": measurement_rows,
        "type_counts": dict(type_counts),
    }


def plot_selected_layer(entities) -> None:
    if not entities:
        st.info("No geometry to preview for this layer.")
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
        st.info("Selected layer contains no previewable geometry.")
        return

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Selected Layer Geometry")
    ax.grid(True, alpha=0.3)
    st.pyplot(fig, clear_figure=True)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    runtime_dirs = ensure_runtime_dirs()

    st.title(APP_TITLE)
    st.subheader(APP_SUBTITLE)

    with st.sidebar:
        st.header("Local Setup")
        st.session_state["oda_path"] = st.text_input(
            "ODA File Converter executable path",
            value=st.session_state.get("oda_path", ""),
            placeholder=r"C:\Program Files\ODA\ODAFileConverter.exe",
        )
        st.caption("Everything stays local. No cloud upload is used.")
        st.session_state["unit_override"] = st.selectbox(
            "Unit override",
            ["Auto", "mm", "cm", "m", "inches", "feet", "unknown"],
            index=["Auto", "mm", "cm", "m", "inches", "feet", "unknown"].index(st.session_state.get("unit_override", "Auto")),
        )

    uploaded_file = st.file_uploader("Upload DWG / DXF", type=["dwg", "dxf"])

    if uploaded_file is None:
        st.info("Upload a DWG or DXF file to inspect layers and calculate length.")
        return

    current_signature = file_signature(uploaded_file.getvalue())
    if st.session_state.get("upload_signature") != current_signature:
        st.session_state["upload_signature"] = current_signature
        st.session_state["upload_name"] = uploaded_file.name
        reset_analysis()

    st.success(f"File: {uploaded_file.name}")
    st.write("Status: Ready")

    source_path = Path(st.session_state["source_path"]) if st.session_state.get("source_path") else None
    if source_path is None or source_path.name != uploaded_file.name:
        try:
            source_path = load_uploaded_file(uploaded_file, runtime_dirs)
            st.session_state["source_path"] = str(source_path)
        except Exception as exc:
            st.error(f"Failed to save upload: {exc}")
            return

    if st.button("Read / Convert Drawing", type="primary") or st.session_state.get("dxf_doc") is None:
        try:
            _, doc, insunits = prepare_document(source_path, runtime_dirs)
            st.session_state["layers_table"] = build_layer_table(doc)
            st.session_state["dxf_doc"] = doc
            st.session_state["insunits"] = insunits
            if source_path.suffix.lower() == ".dwg":
                st.success("DWG conversion successful.")
            else:
                st.success("DXF loaded successfully.")
        except FileNotFoundError as exc:
            st.error(str(exc))
            return
        except Exception as exc:
            st.error(f"DXF/DWG processing failed. Error: {exc}")
            return

    doc = st.session_state.get("dxf_doc")
    if doc is None:
        st.warning("No drawing loaded.")
        return

    insunits = st.session_state.get("insunits") or {"label": "unknown", "meters_per_unit": None, "known": False}
    unit_label, meters_per_unit, overridden = get_effective_unit(insunits, st.session_state.get("unit_override", "Auto"))

    st.markdown(f"**Drawing Unit:** {insunits.get('label', 'unknown').title()}")
    if not insunits.get("known") and st.session_state.get("unit_override") == "Auto":
        st.warning("Drawing unit could not be determined. Result will stay in drawing units until you choose a manual override.")

    layers_table = st.session_state.get("layers_table") or build_layer_table(doc)
    layers_df = pd.DataFrame(layers_table)
    st.write(f"Layers found: {len(layers_df)}")
    st.dataframe(layers_df[["Layer", "Object Count"]], use_container_width=True, hide_index=True)

    if layers_df.empty:
        st.warning("Empty drawing.")
        return

    layer_options = layers_df["Layer"].tolist()
    default_layer = st.session_state.get("selected_layer") or layer_options[0]
    selected_layer = st.selectbox("Select Layer", layer_options, index=layer_options.index(default_layer) if default_layer in layer_options else 0)
    st.session_state["selected_layer"] = selected_layer

    layer_summary = summarize_layer(doc, selected_layer)
    st.write(f"Selected Layer: {selected_layer}")
    st.write(f"Objects: {layer_summary['total_entities']}")

    calculation_key = (selected_layer, st.session_state.get("unit_override", "Auto"), insunits.get("code"))
    calculate_clicked = st.button("Calculate Layer Length")
    if calculate_clicked or st.session_state.get("calculation") is None or st.session_state.get("calculation_key") != calculation_key:
        try:
            st.session_state["calculation"] = calculate_layer(doc, selected_layer, unit_label, meters_per_unit)
            st.session_state["calculation_key"] = calculation_key
        except Exception as exc:
            st.error(f"Calculation failed: {exc}")
            return

    calculation = st.session_state["calculation"]

    st.markdown("### Result")
    if calculation["measurable_entities"] == 0:
        st.warning("Selected layer contains no measurable geometry.")
        st.write(f"Objects: {calculation['total_entities']}")
        st.write("Supported measurable objects: 0")
    else:
        total_display = calculation["total_length"]
        display_unit = "m" if meters_per_unit is not None else unit_label
        st.metric("Total geometric length", f"{total_display:,.2f} {display_unit}")
        st.write(f"Objects: {calculation['total_entities']}")
        st.write(f"Measured: {calculation['measurable_entities']}")
        st.write(f"Ignored: {calculation['ignored_count']}")
        st.write(f"Circle objects: {calculation['circle_count']}")

    counts = calculation["type_counts"]
    st.write(
        f"LINE objects: {counts.get('LINE', 0)} | LWPOLYLINE objects: {counts.get('LWPOLYLINE', 0)} | POLYLINE objects: {counts.get('POLYLINE', 0)} | ARC objects: {counts.get('ARC', 0)}"
    )

    details_df = pd.DataFrame(calculation["detail_rows"])
    if not details_df.empty:
        st.markdown("### Detail Table")
        st.dataframe(details_df, use_container_width=True, hide_index=True)
        st.write(f"TOTAL = {calculation['total_length']:,.2f} {display_unit}")
    else:
        st.info("0 measurable objects")

    st.markdown("### Geometry Preview")
    plot_selected_layer(get_layer_entities(doc, selected_layer))

    excel_bytes = build_takeoff_excel(
        file_name=uploaded_file.name,
        layer_name=selected_layer,
        object_count=calculation["total_entities"],
        total_length=round(calculation["total_length"], 6),
        unit_label=display_unit,
        details=calculation["detail_rows"],
        object_type_rows=calculation["object_type_rows"],
    )

    st.download_button(
        "Export Excel",
        data=excel_bytes,
        file_name="takeoff_result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()