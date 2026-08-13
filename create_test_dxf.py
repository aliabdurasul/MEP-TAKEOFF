from __future__ import annotations

from pathlib import Path

import ezdxf

from dxf_reader import open_dxf
from geometry import measure_entity


EXPECTED_TOTAL_METERS = 60.0


def create_test_dxf(output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()

    doc.layers.new("TEST-PIPE")

    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "TEST-PIPE"})
    msp.add_lwpolyline([(10, 0), (20, 0), (30, 0)], dxfattribs={"layer": "TEST-PIPE"})
    msp.add_line((30, 0), (60, 0), dxfattribs={"layer": "TEST-PIPE"})
    msp.add_circle((75, 0), 2, dxfattribs={"layer": "TEST-PIPE"})

    doc.saveas(output_path)
    return output_path


def verify_test_dxf(file_path: str | Path) -> float:
    doc = open_dxf(file_path)
    msp = doc.modelspace()
    total = 0.0
    for entity in msp:
        raw_length, measurable, ignored = measure_entity(entity)
        if measurable and not ignored:
            total += raw_length
    assert abs(total - EXPECTED_TOTAL_METERS) < 1e-6, f"Expected {EXPECTED_TOTAL_METERS}, got {total}"
    return total


if __name__ == "__main__":
    target = create_test_dxf(Path("data/input/test_pipe.dxf"))
    total = verify_test_dxf(target)
    print(f"Created {target}")
    print(f"Verified total = {total:.2f} m")