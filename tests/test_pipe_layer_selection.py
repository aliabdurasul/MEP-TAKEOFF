"""User-controlled pipe layers, pipe-like layer warning and possible double-line warning.

Default behaviour must stay the project rule (П_Трубы*, except the centreline layer). Other layers
are included only by explicit selection; warnings never change quantities.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

import app
from synthetic_dxf import (
    CENTERLINE_LAYER,
    FITTING_LAYER,
    INSUNITS_MM,
    INSUNITS_UNKNOWN,
    MARKER_LAYER,
    PIPE_LAYER,
    RISER_LAYER,
    VALVE_LAYER,
    add_insert,
    add_line,
    define_block,
    new_doc,
    reload,
    to_bytes,
)

OUTLINE_LAYER = "P-PIPE-____-OTLN"
DETAIL_LAYER = "A-DETL-____-HDLN"


def _codes(report) -> list[str]:
    return [row["Code"] for row in report["warnings"]]


def _warning(report, code):
    return next((row for row in report["warnings"] if row["Code"] == code), None)


def _project_drawing():
    """П_Трубы 5000 + Опуск 1000 + centreline 2000 (excluded) + outline pair 2 x 10000 (25 apart) + detail 1000 + block on outline."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (5000, 0), layer=PIPE_LAYER)
    add_line(doc, (0, 5000), (0, 6000), layer=RISER_LAYER)
    add_line(doc, (0, 9000), (2000, 9000), layer=CENTERLINE_LAYER)
    add_line(doc, (0, 20000), (10000, 20000), layer=OUTLINE_LAYER)
    add_line(doc, (0, 20025), (10000, 20025), layer=OUTLINE_LAYER)
    add_line(doc, (0, 30000), (1000, 30000), layer=DETAIL_LAYER)
    define_block(doc, "ELBOW_OUTLINE", lines=[((0, 0), (300, 0)), ((0, 25), (300, 25))], line_layer=OUTLINE_LAYER)
    add_insert(doc, "ELBOW_OUTLINE", (12000, 20000), layer=OUTLINE_LAYER)
    return reload(doc)


def _quantities(report):
    return (
        round(report["summary"]["total_pipe_length"], 6),
        report["summary"]["pipe_entity_count"],
        report["pipe_rows"],
        report["pipe_detail_rows"],
        report["layers_rows"],
        report["summary"]["equipment_count"],
        report["summary"]["fittings_count"],
        report["summary"]["valves_count"],
    )


def test_explicit_default_selection_equals_rule(validation):
    """PLS-01: passing the default layer list gives exactly the rule's quantities; outline is not included."""
    doc = _project_drawing()
    rule = app.calculate_dxf_quantities(doc, "m", 0.001)
    defaults = app.default_pipe_layers(app.dxf_layer_names(doc))
    explicit = app.calculate_dxf_quantities(doc, "m", 0.001, pipe_layers=defaults)
    validation.equal(
        "PLS-01",
        "default pipe layers = project rule",
        expected=([PIPE_LAYER, RISER_LAYER], 6.0, True, "default"),
        actual=(defaults, round(rule["summary"]["total_pipe_length"], 6), _quantities(rule) == _quantities(explicit), rule["summary"]["pipe_layer_mode"]),
        basis="LINE 5000 on П_Трубы + 1000 on Опуск; centreline 2000, outline 2x10000, detail 1000 not in the rule",
        kind="CONTRACT",
    )


def test_manual_selection_adds_only_chosen_layers(validation):
    """PLS-02: an explicitly chosen outline layer is measured; detail lines, blocks and unchosen layers are not."""
    doc = _project_drawing()
    report = app.calculate_dxf_quantities(doc, "m", 0.001, pipe_layers=[PIPE_LAYER, OUTLINE_LAYER])
    included = {row["Layer"]: row for row in report["pipe_layer_rows"] if row["Included"] == "да"}
    validation.equal(
        "PLS-02",
        "manual selection: exactly the chosen layers",
        expected=(25.0, 3, [OUTLINE_LAYER, PIPE_LAYER], 20.0, 0.6, (0, 0, 0), "manual"),
        actual=(
            round(report["summary"]["total_pipe_length"], 6),
            report["summary"]["pipe_entity_count"],
            sorted(included),
            included[OUTLINE_LAYER]["Length (m)"],
            round(report["summary"]["pipe_geometry_in_blocks_length"], 6),
            (report["summary"]["equipment_count"], report["summary"]["fittings_count"], report["summary"]["valves_count"]),
            report["summary"]["pipe_layer_mode"],
        ),
        basis="П_Трубы 5000 + outline 2x10000 chosen; Опуск not chosen; detail 1000 not chosen; block (2x300 on outline) reported, not measured",
        kind="CONTRACT",
    )


def test_pipe_layer_rows_sum_to_total(validation):
    """PLS-03: included pipe-layer rows add up to the overall total in both modes."""
    doc = _project_drawing()
    sums = []
    for selection in (None, [PIPE_LAYER, OUTLINE_LAYER]):
        report = app.calculate_dxf_quantities(doc, "m", 0.001, pipe_layers=selection)
        included = sum(row["Length (m)"] for row in report["pipe_layer_rows"] if row["Included"] == "да")
        sums.append((round(included, 6), round(report["summary"]["total_pipe_length"], 6)))
    validation.equal(
        "PLS-03",
        "pipe-layer table reconciles with total",
        expected=[(6.0, 6.0), (25.0, 25.0)],
        actual=sums,
        basis="default rule, then П_Трубы + outline",
        kind="CONTRACT",
    )


def test_pipe_like_layer_warning(validation):
    """PLW-01: a PIPE-named layer with geometry outside the rule is reported with count and raw length."""
    doc = _project_drawing()
    report = app.calculate_dxf_quantities(doc, "m", 0.001)
    warning = _warning(report, "PIPE_LIKE_LAYER_NOT_INCLUDED")
    not_included = [(row["Layer"], row["Entities"], row["Measurable Entities"], row["Raw Length (du)"]) for row in report["pipe_layer_rows"] if row["Included"] == "нет"]
    validation.equal(
        "PLW-01",
        "pipe-like layer outside the rule is warned, quantity unchanged",
        expected=(True, [(OUTLINE_LAYER, 3, 2, 20000.0)], True, True, 6.0),
        actual=(
            warning is not None,
            not_included,
            warning is not None and OUTLINE_LAYER in warning["Message"] and "20,000.000" in warning["Message"],
            warning is not None and "не подтверждение" in warning["Message"],
            round(report["summary"]["total_pipe_length"], 6),
        ),
        basis="outline layer: 2 LINE x 10000 + 1 INSERT; INSERT is not measurable",
        kind="WARNING",
    )


def test_pipe_like_warning_skips_role_layers_and_included_layers(validation):
    """PLW-02: centreline, marker, fitting and valve layers (names contain 'труб') are not reported; chosen layers are not either."""
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (1000, 0), layer=PIPE_LAYER)
    for index, layer in enumerate((CENTERLINE_LAYER, MARKER_LAYER, FITTING_LAYER, VALVE_LAYER)):
        add_line(doc, (0, 1000 * (index + 1)), (500, 1000 * (index + 1)), layer=layer)
    add_line(doc, (0, 9000), (700, 9000), layer="pipe-supply")
    doc = reload(doc)
    default_codes = _codes(app.calculate_dxf_quantities(doc, "m", 0.001))
    default_rows = [row["Layer"] for row in app.calculate_dxf_quantities(doc, "m", 0.001)["pipe_layer_rows"] if row["Included"] == "нет"]
    chosen = app.calculate_dxf_quantities(doc, "m", 0.001, pipe_layers=[PIPE_LAYER, "pipe-supply"])
    validation.equal(
        "PLW-02",
        "no pipe-like warning for role layers or chosen layers",
        expected=(True, ["pipe-supply"], False),
        actual=("PIPE_LIKE_LAYER_NOT_INCLUDED" in default_codes, default_rows, "PIPE_LIKE_LAYER_NOT_INCLUDED" in _codes(chosen)),
        basis="LINEs on centreline, П_Марки труб, fitting and valve layers; 'pipe-supply' LINE 700",
        kind="WARNING",
    )


def _double_line_doc(offset: float, insunits: int = INSUNITS_MM, length: float = 10000.0, shift: float = 0.0):
    doc = new_doc(insunits)
    add_line(doc, (0, 0), (length, 0))
    add_line(doc, (shift, offset), (shift + length, offset))
    return reload(doc)


def test_double_line_warning_is_review_only(validation):
    """DL-01: two parallel walls 25 mm apart are flagged; both stay in the total (no merge, no correction)."""
    report = app.calculate_dxf_quantities(_double_line_doc(25.0), "m", 0.001)
    warning = _warning(report, "DOUBLE_LINE_PIPE")
    validation.equal(
        "DL-01",
        "DOUBLE_LINE_PIPE flags, never corrects",
        expected=(True, 2, 20.0, 20.0, 2, 2, True),
        actual=(
            warning is not None,
            warning and warning["Count"],
            warning and warning["Length"],
            round(report["summary"]["total_pipe_length"], 6),
            report["summary"]["pipe_entity_count"],
            report["summary"]["possible_double_line_segments"],
            warning is not None and "вероятность" in warning["Message"],
        ),
        basis="LINE (0,0)-(10000,0) and (0,25)-(10000,25) on П_Трубы, mm",
        kind="WARNING",
    )


@pytest.mark.parametrize(
    ("case_id", "offset", "insunits", "shift", "expected", "basis"),
    [
        ("DL-02", 1000.0, INSUNITS_MM, 0.0, False, "parallel lines 1000 mm apart (limit 0.3 m)"),
        ("DL-03", 0.0, INSUNITS_MM, 2000.0, False, "collinear overlap (offset 0) is an overlap, not a double line"),
        ("DL-04", 25.0, INSUNITS_MM, 20000.0, False, "parallel 25 mm apart but not side by side"),
        ("DL-05", 25.0, INSUNITS_UNKNOWN, 0.0, True, "unknown units: 25 drawing units apart (limit 300)"),
        ("DL-06", 400.0, INSUNITS_UNKNOWN, 0.0, False, "unknown units: 400 drawing units apart (limit 300)"),
    ],
)
def test_double_line_limits(case_id, offset, insunits, shift, expected, basis, validation):
    doc = _double_line_doc(offset, insunits=insunits, shift=shift)
    factor = 0.001 if insunits == INSUNITS_MM else None
    report = app.calculate_dxf_quantities(doc, "m" if factor else "Единицы чертежа", factor)
    validation.equal(case_id, "DOUBLE_LINE_PIPE limits", expected=expected, actual="DOUBLE_LINE_PIPE" in _codes(report), basis=basis, kind="WARNING")


# --- UI and Excel ------------------------------------------------------------------------------

pytest.importorskip("streamlit.testing.v1")

from streamlit_harness import dataframes, exceptions, metric_values, render_app, rerun, warning_texts  # noqa: E402


def _ui_drawing(pipe_length: float) -> bytes:
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (pipe_length, 0), layer=PIPE_LAYER)
    add_line(doc, (0, 20000), (10000, 20000), layer=OUTLINE_LAYER)
    add_line(doc, (0, 20025), (10000, 20025), layer=OUTLINE_LAYER)
    return to_bytes(doc)


def _pipe_layer_widget(app_test):
    return next(widget for widget in app_test.multiselect if widget.label == "Трубные слои в метраже")


def _ui_pipe_layer_rows(app_test):
    for frame in dataframes(app_test):
        if "Basis" in frame.columns:
            return sorted((row["Layer"], row["Included"], round(float(row.iloc[7]), 6)) for _index, row in frame.iterrows())
    return None


def test_ui_selection_matches_excel(tmp_path, monkeypatch, validation):
    """PLS-UI-01: default UI excludes the outline; choosing it changes UI total, warnings and Excel identically."""
    app_test = render_app(_ui_drawing(5000.0), tmp_path, monkeypatch, name="plan.dxf")
    default_state = (metric_values(app_test)[0], _pipe_layer_widget(app_test).value, any("PIPE_LIKE_LAYER_NOT_INCLUDED" in text for text in warning_texts(app_test)))
    _pipe_layer_widget(app_test).set_value([PIPE_LAYER, OUTLINE_LAYER])
    app_test.run()
    report = app_test.session_state["dxf_report"]
    layer = app_test.session_state["dxf_layer_calculation"]
    sheets = pd.read_excel(
        io.BytesIO(app.build_dxf_takeoff_excel(file_name="plan.dxf", report=report, layer_calculation=layer, selected_layer=PIPE_LAYER, display_unit="m")),
        sheet_name=None,
    )
    excel_rows = sorted((row["Слой"], row["В метраже"], round(float(row["Длина (м)"]), 6)) for _index, row in sheets["ТРУБНЫЕ СЛОИ"].iterrows())
    summary = sheets["СВОДКА"].iloc[0]
    manual_state = (
        metric_values(app_test)[0],
        any("DOUBLE_LINE_PIPE" in text for text in warning_texts(app_test)),
        any("выбраны вручную" in str(item.value) for item in app_test.info),
        _ui_pipe_layer_rows(app_test) == excel_rows,
        (round(float(summary["Total Pipe Length (m)"]), 6), summary["Pipe Layer Mode"]),
        exceptions(app_test),
    )
    validation.equal(
        "PLS-UI-01",
        "UI selection and Excel agree",
        expected=(("5.00 m", [PIPE_LAYER], True), ("25.00 m", True, True, True, (25.0, "manual"), [])),
        actual=(default_state, manual_state),
        basis=f"П_Трубы 5000 + outline 2x10000 (25 apart); UI rows={_ui_pipe_layer_rows(app_test)}, Excel rows={excel_rows}",
        kind="WORKFLOW",
    )


def test_selection_does_not_survive_new_content_with_same_name(tmp_path, monkeypatch, validation):
    """PLS-UI-02: a manual selection is not applied to a different drawing uploaded under the same name."""
    app_test = render_app(_ui_drawing(5000.0), tmp_path, monkeypatch, name="plan.dxf")
    _pipe_layer_widget(app_test).set_value([PIPE_LAYER, OUTLINE_LAYER])
    app_test.run()
    manual_total = metric_values(app_test)[0]
    rerun(app_test, _ui_drawing(3000.0), tmp_path, monkeypatch, name="plan.dxf")
    validation.equal(
        "PLS-UI-02",
        "same name, new content: default layers and fresh result",
        expected=("25.00 m", "3.00 m", [PIPE_LAYER], "default", []),
        actual=(
            manual_total,
            metric_values(app_test)[0],
            _pipe_layer_widget(app_test).value,
            app_test.session_state["dxf_report"]["summary"]["pipe_layer_mode"],
            exceptions(app_test),
        ),
        basis="plan.dxf (П_Трубы 5000 + outline, outline chosen) then plan.dxf (П_Трубы 3000 + outline)",
        kind="WORKFLOW",
    )
