"""Impact analysis on the private project drawing (authorised local environment only)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app
from tools.impact_analysis import analyse

PRIVATE_DXF = Path(__file__).resolve().parents[1] / "data" / "input" / "MIR_OT_ANTP_R22_K2_8.dxf"

pytestmark = pytest.mark.private_data


def test_private_drawing_impact_selection_matches_takeoff(validation):
    """On the private drawing the analysis reproduces the takeoff's pipe selection."""
    result = analyse(app.open_dxf(PRIVATE_DXF))
    validation.equal(
        "IMP-PRIV-01",
        "private drawing: analysis selection = takeoff selection",
        expected=(True, 3769),
        actual=(result["drawing"]["selection_matches_app"], result["drawing"]["app_pipe_entity_count"]),
        basis="MIR_OT_ANTP_R22_K2_8.dxf (3769 pipe entities per existing baseline test)",
        kind="IMPACT",
    )
