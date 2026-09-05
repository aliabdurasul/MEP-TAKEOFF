from __future__ import annotations

from pathlib import Path

import ezdxf

import app
from dxf_reader import open_dxf


EXPECTED_TOTAL_METERS = 60.0


def create_test_dxf(output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()

    doc.layers.new("TEST-PIPE")
    doc.layers.new("TEST-PIPE-DUP")

    for layer_name in ("TEST-PIPE", "TEST-PIPE-DUP"):
        msp.add_line((0, 0), (10, 0), dxfattribs={"layer": layer_name})
        msp.add_lwpolyline([(10, 0), (20, 0), (30, 0)], dxfattribs={"layer": layer_name})
        msp.add_line((30, 0), (60, 0), dxfattribs={"layer": layer_name})

    msp.add_line((30, 0), (60, 0), dxfattribs={"layer": "TEST-PIPE-DUP"})
    msp.add_lwpolyline([(30, 0), (20, 0), (10, 0)], dxfattribs={"layer": "TEST-PIPE-DUP"})
    msp.add_circle((75, 0), 2, dxfattribs={"layer": "TEST-PIPE"})

    doc.saveas(output_path)
    return output_path


def verify_test_dxf(file_path: str | Path) -> tuple[dict, dict]:
    doc = open_dxf(file_path)
    test_pipe = app.calculate_layer(doc, "TEST-PIPE", "m", 1.0)
    test_pipe_dup = app.calculate_layer(doc, "TEST-PIPE-DUP", "m", 1.0)
    assert test_pipe["raw_total_length"] == 60.0
    assert test_pipe["duplicate_raw_length"] == 0.0
    assert test_pipe["final_total_length"] == 60.0
    assert test_pipe_dup["raw_total_length"] == 110.0
    assert test_pipe_dup["duplicate_raw_length"] == 50.0
    assert test_pipe_dup["final_total_length"] == 60.0
    print(f"TEST-PIPE:     raw={test_pipe['raw_total_length']:.1f}, duplicates_removed={test_pipe['duplicate_raw_length']:.1f}, final={test_pipe['final_total_length']:.1f}")
    print(f"TEST-PIPE-DUP: raw={test_pipe_dup['raw_total_length']:.1f}, duplicates_removed={test_pipe_dup['duplicate_raw_length']:.1f}, final={test_pipe_dup['final_total_length']:.1f}")
    return test_pipe, test_pipe_dup


if __name__ == "__main__":
    target = create_test_dxf(Path("data/input/test_pipe.dxf"))
    verify_test_dxf(target)
    print(f"Created {target}")