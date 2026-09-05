from __future__ import annotations

from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import calculate_dwg_quantities
from ezdwg_reader import get_entities, open_dwg, read_insunits

DWG_PATH = PROJECT_ROOT / "data" / "input" / "MIR_OT_ANTP_R22_K2_8.dwg"


def main() -> int:
    doc = open_dwg(DWG_PATH)
    insunits = read_insunits(doc)
    entities = get_entities(doc)
    report = calculate_dwg_quantities(entities, insunits["label"], insunits["meters_per_unit"])

    print("ENTITY_COUNT", len(entities))
    print("SUMMARY", report["summary"])
    print("PIPES_ROWS", report["pipes_rows"][:20])
    print("EQUIPMENT_ROWS", report["equipment_rows"][:20])
    print("FITTINGS_ROWS", report["fittings_rows"][:20])
    print("VALVES_ROWS", report["valves_rows"][:20])
    print("LAYERS_ROWS", report["layers_rows"][:20])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())