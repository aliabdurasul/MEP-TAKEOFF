"""Create synthetic demo DXF drawings for trying the UI without a project drawing.

    .venv\\Scripts\\python.exe tools\\make_demo_drawings.py

Writes to data/demo/ (git-ignored). Existing files are left untouched. These are
synthetic drawings with hand-checkable totals, not project data.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"
PIPE = "П_Трубы"
MARKERS = "П_Марки труб"


def _doc(insunits: int):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    for name in (PIPE, MARKERS, "Оборудование", "Соединительные детали трубопроводов", "Арматура трубопроводов"):
        doc.layers.add(name)
    return doc


def _mixed_plan():
    doc = _doc(4)
    msp = doc.modelspace()
    msp.add_line((0, 0), (3000, 4000), dxfattribs={"layer": PIPE})
    msp.add_text("ø16", height=250, dxfattribs={"layer": MARKERS, "insert": (1500, 2500)})
    msp.add_line((0, 20000), (2000, 20000), dxfattribs={"layer": PIPE})
    msp.add_text("DN20", height=250, dxfattribs={"layer": MARKERS, "insert": (1000, 21000)})
    msp.add_arc((20000, 0), 1000, 0, 90, dxfattribs={"layer": PIPE})
    msp.add_line((40000, 0), (43000, 0), dxfattribs={"layer": PIPE})
    msp.add_lwpolyline([(0, 60000), (1000, 60000), (1000, 61000), (0, 61000)], close=True, dxfattribs={"layer": PIPE})
    msp.add_spline(fit_points=[(0, 80000), (1000, 80500), (2000, 80000)], dxfattribs={"layer": PIPE})
    for index, (block, layer) in enumerate((("Радиатор 500", "Оборудование"), ("Отвод 90", "Соединительные детали трубопроводов"), ("Кран шаровой", "Арматура трубопроводов"))):
        doc.blocks.new(name=block).add_circle((0, 0), 100)
        msp.add_blockref(block, (index * 2000, 100000), dxfattribs={"layer": layer})
    return doc


def _replacement_plan():
    doc = _doc(4)
    doc.modelspace().add_line((0, 0), (10000, 0), dxfattribs={"layer": PIPE})
    doc.modelspace().add_text("ø25", height=250, dxfattribs={"layer": MARKERS, "insert": (5000, 500)})
    return doc


def _unknown_units_plan():
    doc = _doc(0)
    doc.modelspace().add_line((0, 0), (3000, 4000), dxfattribs={"layer": PIPE})
    return doc


DRAWINGS = {
    "plan_v1/plan.dxf": (_mixed_plan, "15.57 m total (Ø16 5.00, DN20 2.00, UNKNOWN 8.57 incl. 4.00 closed polyline); 1 SPLINE unmeasured; 1 radiator, 1 elbow, 1 valve"),
    "plan_v2/plan.dxf": (_replacement_plan, "same file name, different content: 10.00 m total (Ø25)"),
    "unknown_units.dxf": (_unknown_units_plan, "$INSUNITS=0: 5,000.00 drawing units, UNKNOWN_UNITS warning"),
}


def main() -> int:
    for relative, (builder, expected) in DRAWINGS.items():
        path = DEMO / relative
        if path.exists():
            print(f"exists, kept: {path}  -> expected {expected}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        builder().saveas(path)
        print(f"created: {path}  -> expected {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
