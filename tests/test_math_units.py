"""Drawing units: $INSUNITS interpretation and conversion to metres.

Reference factors are SI definitions: 1 in = 0.0254 m and 1 ft = 0.3048 m (exact).
"""

from __future__ import annotations

import pytest

import app
from synthetic_dxf import (
    INSUNITS_CM,
    INSUNITS_FOOT,
    INSUNITS_INCH,
    INSUNITS_M,
    INSUNITS_MM,
    INSUNITS_UNKNOWN,
    add_line,
    new_doc,
    reload,
)

UNIT_CASES = [
    ("UNIT-01", INSUNITS_MM, "millimetres", 0.001),
    ("UNIT-02", INSUNITS_CM, "centimetres", 0.01),
    ("UNIT-03", INSUNITS_M, "metres", 1.0),
    ("UNIT-04", INSUNITS_INCH, "inches", 0.0254),
    ("UNIT-05", INSUNITS_FOOT, "feet", 0.3048),
]


@pytest.mark.parametrize(("case_id", "code", "name", "metres_per_unit"), UNIT_CASES)
def test_insunits_factor(validation, case_id, code, name, metres_per_unit):
    """$INSUNITS code maps to the SI metres-per-unit factor."""
    doc = reload(new_doc(code))
    validation.close(
        case_id,
        f"INSUNITS={code} ({name}) factor",
        expected=metres_per_unit,
        actual=app.read_insunits(doc)["meters_per_unit"],
        basis=f"$INSUNITS={code}",
        rel_tol=1e-15,
        abs_tol=0.0,
    )


@pytest.mark.parametrize(("case_id", "code", "name", "metres_per_unit"), UNIT_CASES)
def test_pipe_total_converted_to_metres(validation, case_id, code, name, metres_per_unit):
    """A 5000-unit pipe LINE is reported as 5000 * factor metres."""
    doc = new_doc(code)
    add_line(doc, (0, 0), (3000, 4000))
    doc = reload(doc)
    factor = app.read_insunits(doc)["meters_per_unit"]
    report = app.calculate_dxf_quantities(doc, "m", factor)
    validation.close(
        f"{case_id}-PIPE",
        f"pipe length in metres ({name})",
        expected=5000.0 * metres_per_unit,
        actual=report["summary"]["total_pipe_length"],
        basis=f"LINE (0,0)-(3000,4000) = 5000 units; $INSUNITS={code}",
    )


def test_unknown_units_are_not_converted(validation):
    """$INSUNITS=0 yields no metres factor (no conversion is guessed)."""
    insunits = app.read_insunits(reload(new_doc(INSUNITS_UNKNOWN)))
    validation.equal(
        "UNIT-06",
        "unknown units -> no metres factor",
        expected=(False, None),
        actual=(insunits["known"], insunits["meters_per_unit"]),
        basis="$INSUNITS=0",
        kind="MATH",
    )


OVERRIDE_CASES = [
    ("UNIT-OVR-01", "mm", 0.001),
    ("UNIT-OVR-02", "cm", 0.01),
    ("UNIT-OVR-03", "m", 1.0),
    ("UNIT-OVR-04", "inches", 0.0254),
    ("UNIT-OVR-05", "feet", 0.3048),
    ("UNIT-OVR-06", "unknown", None),
]


@pytest.mark.parametrize(("case_id", "override", "expected"), OVERRIDE_CASES)
def test_unit_override(validation, case_id, override, expected):
    """A manual unit override replaces the header factor with the SI factor of the chosen unit."""
    header_mm = {"code": 4, "label": "millimeters", "meters_per_unit": 0.001, "known": True}
    _label, factor, overridden = app.get_effective_unit(header_mm, override)
    validation.equal(
        case_id,
        f"override '{override}' factor",
        expected=(expected, True),
        actual=(factor, overridden),
        basis="header $INSUNITS=4 overridden in sidebar",
        kind="MATH",
    )
