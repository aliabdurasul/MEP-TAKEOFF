"""tools/compare_v0_v1.py attributes every V0 -> V1 difference to a documented rule."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from synthetic_dxf import (
    EQUIPMENT_LAYER,
    INSUNITS_MM,
    PIPE_LAYER,
    add_arc,
    add_insert,
    add_line,
    add_lwpolyline,
    add_text,
    ensure_layer,
    new_doc,
    reload,
)
from tools.compare_v0_v1 import compare, load_baseline

BASELINE_DIR = Path(os.environ["MEP_BASELINE_DIR"]).resolve() if os.environ.get("MEP_BASELINE_DIR") else None

pytestmark = pytest.mark.skipif(BASELINE_DIR is None, reason="NOT RUN: MEP_BASELINE_DIR (main's modules) is not set; CI sets it")


def _drawing():
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (2000, 0))
    add_text(doc, "ø16", (1000, 1000))
    add_lwpolyline(doc, [(0, 10000, 0), (2000, 10000, 0)])
    add_lwpolyline(doc, [(0, 10000, 1.0), (2000, 10000, 0)])
    add_lwpolyline(doc, [(0, 20000, 1.0), (2000, 20000, 0)])
    add_lwpolyline(doc, [(0, 20000, 0), (2000, 20000, 0)])
    add_arc(doc, (50000, 0), 1000.0, 0.0, 90.0, extrusion=(0, 0, -1))
    add_text(doc, "DN20", (-50000, 500))
    add_line(doc, (0, 30000), (2000, 30000))
    add_text(doc, "%%c25", (1000, 31000))
    ensure_layer(doc, PIPE_LAYER)
    mesh = doc.modelspace().add_polyface(dxfattribs={"layer": PIPE_LAYER})
    mesh.append_face([(0, 40000, 0), (1000, 40000, 0), (1000, 41000, 0)])
    minsert = add_insert(doc, "Радиатор 500", (0, 60000), layer=EQUIPMENT_LAYER)
    minsert.dxf.row_count = 2
    minsert.dxf.column_count = 3
    minsert.dxf.row_spacing = 1000
    minsert.dxf.column_spacing = 1000
    return reload(doc)


def test_every_difference_is_attributed(validation):
    """Bulge identity, OCS matching, new notation, mesh exclusion and MINSERT are attributed; renames are not differences."""
    result = compare(_drawing(), load_baseline(BASELINE_DIR))
    rules = sorted({row["Rule"] for row in result["entity_differences"]})
    counts = {row["Category"]: (row["Delta"], row["Rule"]) for row in result["counts"]}
    validation.equal(
        "CMP-01",
        "V0 -> V1 differences attributed to documented rules",
        expected=(
            ["V1-DIA-02", "V1-DIA-05", "V1-DUP-01", "V1-ENT-02"],
            2,
            1,
            (5, "V1-BLK-02"),
            0,
            "ALL DIFFERENCES EXPLAINED",
            True,
            round(math.pi + 2.0, 6),
        ),
        actual=(
            rules,
            sum(1 for row in result["entity_differences"] if row["Rule"] == "V1-DUP-01"),
            result["notation"]["label_renamed_only"],
            counts["EQUIPMENT"],
            result["verdict"]["unexplained"],
            result["verdict"]["status"],
            result["drawing"]["total_reconciled_with_entity_differences"],
            round(sum(row["Length delta"] for row in result["entity_differences"] if row["Rule"] == "V1-DUP-01"), 6),
        ),
        basis="ø16 rename; bulge pairs in both orders (V0 dropped a pi m arc and a 2 m straight); mirrored ARC + DN20; %%c25 marker; polyface; MINSERT 2x3",
        kind="EQUIVALENCE",
    )
