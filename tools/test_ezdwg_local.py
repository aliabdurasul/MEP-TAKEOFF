from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ezdwg_reader import get_entities, get_layers, open_dwg, read_arc, read_circle, read_line, read_polyline, resolve_layer_name


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python tools/test_ezdwg_local.py "data/input/MIR_OT_ANTP_R22_K2_8.dwg"')
        return 1

    dwg_path = (PROJECT_ROOT / Path(sys.argv[1])).resolve() if not Path(sys.argv[1]).is_absolute() else Path(sys.argv[1])
    print("================================")
    print("EZDWG LOCAL DWG TEST")
    print("================================")
    print(f"File: {dwg_path}")

    try:
        dwg = open_dwg(dwg_path)
        open_pass = True
    except Exception as exc:
        open_pass = False
        print(f"DWG OPEN: FAIL ({exc})")
        return 1

    print(f"DWG version: {getattr(dwg, 'version', None)}")
    print(f"Units: {getattr(dwg, 'units', None)}")

    layers = get_layers(dwg_path)
    entities = get_entities(dwg_path)
    entity_counts = Counter(entity['type'] for entity in entities)
    resolved = sum(1 for layer in layers if layer['name'])
    print("")
    print("Layers:")
    print(f"Total: {len(layers)}")
    print(f"Resolved layers: {resolved} / {len(layers)}")
    print("")
    print("Entities:")
    print(f"Total: {len(entities)}")
    for name in ["LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE"]:
        print(f"{name}: {entity_counts.get(name, 0)}")

    print("")
    print("Layer sample:")
    print("HANDLE | NAME")
    print("----------------")
    for layer in layers[:20]:
        print(f"{layer['handle']} | {layer['name']}")

    print("")
    print("Geometry sample:")
    sample_line = next((entity for entity in entities if entity['type'] == 'LINE'), None)
    sample_arc = next((entity for entity in entities if entity['type'] == 'ARC'), None)
    sample_circle = next((entity for entity in entities if entity['type'] == 'CIRCLE'), None)
    sample_polyline = next((entity for entity in entities if entity['type'] in {'LWPOLYLINE', 'POLYLINE'}), None)
    if sample_line:
        print("LINE:")
        print(f"layer: {sample_line['layer']}")
        print(f"length: {sample_line['geometry'].get('length')}")
    if sample_arc:
        print("ARC:")
        print(f"layer: {sample_arc['layer']}")
        print(f"length: {sample_arc['geometry'].get('length')}")
    if sample_circle:
        print("CIRCLE:")
        print(f"layer: {sample_circle['layer']}")
        print(f"radius: {sample_circle['geometry'].get('radius')}")
    if sample_polyline:
        print(f"{sample_polyline['type']}:")
        print(f"layer: {sample_polyline['layer']}")
        print(f"length: {sample_polyline['geometry'].get('length')}")

    unresolved_handles = sorted({entity['layer_handle'] for entity in entities if entity['layer_handle'] is not None and not entity['layer']})
    print("")
    print("Final:")
    layer_recovery_pass = resolved > 0 and len(unresolved_handles) < len({layer['handle'] for layer in layers})
    geometry_pass = all(sample is not None for sample in [sample_line, sample_arc, sample_circle, sample_polyline])
    print(f"DWG OPEN: {'PASS' if open_pass else 'FAIL'}")
    print(f"LAYER RECOVERY: {'PASS' if layer_recovery_pass else 'FAIL'}")
    print(f"GEOMETRY: {'PASS' if geometry_pass else 'FAIL'}")
    print(f"READY FOR APP INTEGRATION: {'YES' if open_pass and layer_recovery_pass and geometry_pass else 'NO'}")

    if not layer_recovery_pass:
        print("")
        print("Unresolved layer handles:")
        for handle in unresolved_handles[:20]:
            print(handle)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())