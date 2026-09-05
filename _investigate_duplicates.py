#!/usr/bin/env python3
"""Deep investigation of detected duplicate pairs."""

import ezdxf
import math

DXF_PIPE_LAYER_PREFIX = "П_Трубы"
DXF_PIPE_LAYER_EXCLUDES = {"П_Трубы_ Осевая линия"}

def distance_2d(x1, y1, x2, y2):
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def get_entity_geometry(entity):
    """Get geometry bounds of entity."""
    entity_type = entity.dxftype()
    
    if entity_type == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        return {
            "type": "LINE",
            "start": (start[0], start[1]),
            "end": (end[0], end[1]),
            "length": distance_2d(start[0], start[1], end[0], end[1]),
        }
    
    elif entity_type in ("LWPOLYLINE", "POLYLINE"):
        points = list(entity.get_points()) if hasattr(entity, 'get_points') else []
        if points:
            return {
                "type": entity_type,
                "start": (points[0][0], points[0][1]),
                "end": (points[-1][0], points[-1][1]),
                "point_count": len(points),
            }
    
    elif entity_type == "ARC":
        center = entity.dxf.center
        radius = entity.dxf.radius
        return {
            "type": "ARC",
            "center": (center[0], center[1]),
            "radius": radius,
        }
    
    return {"type": entity_type}

doc = ezdxf.readfile("data/input/MIR_OT_ANTP_R22_K2_8.dxf")

# Build entity map
entity_map = {}
for entity in doc.modelspace().query('*'):
    layer = entity.dxf.layer
    if not layer.startswith(DXF_PIPE_LAYER_PREFIX):
        continue
    if layer in DXF_PIPE_LAYER_EXCLUDES:
        continue
    
    entity_type = entity.dxftype()
    if entity_type not in {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}:
        continue
    
    handle = entity.dxf.handle
    entity_map[int(handle, 16)] = {
        "handle": handle,
        "layer": layer,
        "type": entity_type,
        "geometry": get_entity_geometry(entity),
        "entity": entity,
    }

# Find consecutive handle pairs
suspicious_pairs = []
sorted_handles = sorted(entity_map.keys())
for i in range(len(sorted_handles) - 1):
    h1 = sorted_handles[i]
    h2 = sorted_handles[i + 1]
    
    if abs(h2 - h1) != 1:
        continue  # Not consecutive
    
    e1 = entity_map[h1]
    e2 = entity_map[h2]
    
    # Same layer?
    if e1["layer"] != e2["layer"]:
        continue
    
    # Check geometry similarity
    g1 = e1["geometry"]
    g2 = e2["geometry"]
    
    # Exact same geometry?
    if (g1.get("type") == g2.get("type") == "LINE"):
        if g1.get("start") and g2.get("start"):
            dist_start = distance_2d(
                g1["start"][0], g1["start"][1],
                g2["start"][0], g2["start"][1]
            )
            dist_end = distance_2d(
                g1["end"][0], g1["end"][1],
                g2["end"][0], g2["end"][1]
            )
            
            if dist_start < 0.01 and dist_end < 0.01:
                suspicious_pairs.append((e1, e2, "EXACT_DUPLICATE"))
            elif (abs(g1["length"] - g2["length"]) < 0.001 and
                  distance_2d(g1["start"][0], g1["start"][1], g2["end"][0], g2["end"][1]) < 0.01 and
                  distance_2d(g1["end"][0], g1["end"][1], g2["start"][0], g2["start"][1]) < 0.01):
                suspicious_pairs.append((e1, e2, "REVERSED_DUPLICATE"))

print("DETAILED DUPLICATE INVESTIGATION")
print("=" * 100)
print(f"\nFound {len(suspicious_pairs)} suspicious pairs\n")

# Show first 15 in detail
for i, (e1, e2, class_type) in enumerate(suspicious_pairs[:15]):
    print(f"Pair {i+1}: {class_type}")
    print(f"  Entity 1: {e1['handle']} ({e1['type']}) on {e1['layer']}")
    if e1["geometry"].get("start"):
        g1 = e1["geometry"]
        print(f"    ({g1['start'][0]:.1f}, {g1['start'][1]:.1f}) → ({g1['end'][0]:.1f}, {g1['end'][1]:.1f})")
    print(f"  Entity 2: {e2['handle']} ({e2['type']}) on {e2['layer']}")
    if e2["geometry"].get("start"):
        g2 = e2["geometry"]
        print(f"    ({g2['start'][0]:.1f}, {g2['start'][1]:.1f}) → ({g2['end'][0]:.1f}, {g2['end'][1]:.1f})")
    print()

# Question: Are they REALLY duplicates or just geometrically coincident?
print(f"\nCRITICAL QUESTION:")
print(f"Are these {len(suspicious_pairs)} pairs genuine duplicates (should be excluded)")
print(f"or legitimate geometry features (both should be counted)?")
print(f"\nIf they are genuine duplicates that should be excluded:")
print(f"  - Excluded length: {sum(entity_map[h]['geometry'].get('length', 0) for h, _ in [(int(e['handle'], 16), _) for e, _, _ in suspicious_pairs])} m")
print(f"  - This would affect the total")
print(f"\nBut current test shows total is CORRECT (2016.964818 m)")
print(f"Which means EITHER:")
print(f"  1. These duplicates are NOT actually counted twice (one is excluded somewhere)")
print(f"  2. These are NOT duplicates but legitimate parallel geometry")
