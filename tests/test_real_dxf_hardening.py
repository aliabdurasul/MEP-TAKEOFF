from pathlib import Path

import pytest

import app

REAL_DXF = Path(__file__).resolve().parents[1] / "data" / "input" / "MIR_OT_ANTP_R22_K2_8.dxf"


def _load_real_doc():
    doc = app.open_dxf(REAL_DXF)
    insunits = app.read_insunits(doc)
    return doc, insunits


def test_real_dxf_loads_and_units_detected():
    _, insunits = _load_real_doc()
    assert insunits["code"] == 4
    assert insunits["label"] == "millimeters"
    assert insunits["known"] is True
    assert insunits["meters_per_unit"] == 0.001


def test_real_dxf_pipe_totals_are_consistent_and_repeatable():
    doc, insunits = _load_real_doc()
    report1 = app.calculate_dxf_quantities(doc, "m", insunits["meters_per_unit"])
    report2 = app.calculate_dxf_quantities(doc, "m", insunits["meters_per_unit"])

    assert report1["summary"]["total_pipe_length"] == report2["summary"]["total_pipe_length"]
    assert report1["summary"]["pipe_entity_count"] == report2["summary"]["pipe_entity_count"] == 3769
    assert report1["summary"]["equipment_count"] == report2["summary"]["equipment_count"] == 145
    assert report1["summary"]["fittings_count"] == report2["summary"]["fittings_count"] == 1183
    assert report1["summary"]["valves_count"] == report2["summary"]["valves_count"] == 119

    diameter_total = sum(float(row["Length (m)"]) for row in report1["pipe_rows"])
    assert abs(diameter_total - report1["summary"]["total_pipe_length"]) < 1e-6


def test_real_dxf_diameter_breakdown_matches_expected_values():
    doc, insunits = _load_real_doc()
    report = app.calculate_dxf_quantities(doc, "m", insunits["meters_per_unit"])
    by_diameter = {row["Diameter"]: float(row["Length (m)"]) for row in report["pipe_rows"]}

    assert abs(by_diameter["DN15"] - 77.455369) < 1e-3
    assert abs(by_diameter["DN16"] - 1534.931168) < 1e-3
    assert abs(by_diameter["DN20"] - 41.920497) < 1e-3
    assert abs(by_diameter["DN25"] - 48.637282) < 1e-3
    assert abs(by_diameter["DN76"] - 21.481290) < 1e-3
    assert abs(by_diameter["UNKNOWN"] - 290.710181) < 1e-3


def test_real_dxf_selected_layer_isolated_and_repeatable():
    doc, insunits = _load_real_doc()
    layer_a_1 = app.calculate_layer(doc, "П_Трубы", "m", insunits["meters_per_unit"])
    layer_b = app.calculate_layer(doc, "Соединительные детали трубопроводов", "m", insunits["meters_per_unit"])
    layer_a_2 = app.calculate_layer(doc, "П_Трубы", "m", insunits["meters_per_unit"])

    assert layer_a_1["total_entities"] == 4215
    assert layer_a_1["total_length"] == pytest.approx(1995.4837115635553, abs=1e-6)
    assert layer_a_1["measurable_entities"] == 2913
    assert layer_a_1["duplicate_entities"] == 114
    assert layer_a_1["duplicate_raw_length"] == pytest.approx(911.9999999999181, abs=1e-6)
    assert layer_a_1["ignored_count"] == 1188

    assert layer_b["total_entities"] == 2171
    assert layer_b["total_length"] == pytest.approx(12.671735883525427, abs=1e-6)
    assert layer_b["measurable_entities"] == 638
    assert layer_b["duplicate_entities"] == 278
    assert layer_b["duplicate_raw_length"] == pytest.approx(5525.55744874662, abs=1e-6)
    assert layer_b["ignored_count"] == 1255

    assert layer_a_1["total_entities"] == layer_a_2["total_entities"]
    assert layer_a_1["total_length"] == pytest.approx(layer_a_2["total_length"], abs=1e-9)
    assert layer_a_1["measurable_entities"] == layer_a_2["measurable_entities"]
    assert layer_a_1["ignored_count"] == layer_a_2["ignored_count"]


def test_real_dxf_excel_export_is_consistent_with_calculation():
    doc, insunits = _load_real_doc()
    report = app.calculate_dxf_quantities(doc, "m", insunits["meters_per_unit"])
    layer_a = app.calculate_layer(doc, "П_Трубы", "m", insunits["meters_per_unit"])
    excel_bytes = app.build_takeoff_excel(
        file_name="MIR_OT_ANTP_R22_K2_8.dxf",
        summary_rows=[
            {
                "Total Pipe Length (m)": round(report["summary"]["total_pipe_length"], 6),
                "Pipe Entities": report["summary"]["pipe_entity_count"],
                "Equipment Count": report["summary"]["equipment_count"],
                "Fittings Count": report["summary"]["fittings_count"],
                "Valves Count": report["summary"]["valves_count"],
                "Unit": "m",
            }
        ],
        pipe_by_diameter_rows=report["pipe_by_diameter_rows"],
        pipes_rows=report["pipe_rows"],
        pipes_detail_rows=report["pipe_detail_rows"],
        equipment_rows=report["equipment_rows"],
        fittings_rows=report["fittings_rows"],
        valves_rows=report["valves_rows"],
        layers_rows=report["layers_rows"],
        details=layer_a["detail_rows"],
        object_type_rows=layer_a["object_type_rows"],
        unknown_review_rows=report["unknown_review_rows"],
    )
    assert len(excel_bytes) > 0


def test_real_dxf_pipeline_debug_tracks_auxiliary_and_duplicate_filtering():
    doc, insunits = _load_real_doc()
    report = app.calculate_dxf_quantities(doc, "m", insunits["meters_per_unit"])
    debug = report["debug"]

    assert debug["raw_entities"] == 12276
    assert debug["pipe_layer_raw_entities"] == 3899
    assert debug["after_auxiliary_filter"] == 3899
    assert debug["real_pipe_entities"] == report["summary"]["pipe_entity_count"]
    assert report["summary"]["duplicate_entity_count"] == 130
    assert report["summary"]["raw_pipe_length"] == pytest.approx(2016.9648182240394, abs=1e-9)
    assert report["summary"]["duplicate_raw_length"] == pytest.approx(1.8290308955827725, abs=1e-9)
    assert report["summary"]["final_pipe_length"] == pytest.approx(2015.135787328415, abs=1e-9)
    assert report["summary"]["raw_prefixed_pipe_length"] == pytest.approx(4009.061271353399, abs=1e-9)
    assert report["summary"]["excluded_pipe_geometry_count"] == 1958
    assert report["summary"]["excluded_pipe_geometry_length"] == pytest.approx(1992.0964531294128, abs=1e-9)
    assert debug["reconciliation_difference"] == pytest.approx(0.0, abs=1e-9)
    assert debug["duplicate_candidates"] >= 0
    assert debug["identified_dn_count"] == sum(1 for row in report["pipe_rows"] if row["Diameter"] != "UNKNOWN")
    assert debug["unknown_dn_count"] == sum(1 for row in report["pipe_rows"] if row["Diameter"] == "UNKNOWN")
