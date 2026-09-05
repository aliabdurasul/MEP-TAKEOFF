#!/usr/bin/env python3
"""Debug script to inspect actual diameter marker TEXT values."""

import ezdxf
import re

DXF_DIAMETER_LAYER = "П_Марки труб"
DIAMETER_LABEL_RE = re.compile(r"(?i)(?:DN|Ø|ø)\s*([0-9]+(?:[.,][0-9]+)?)")

doc = ezdxf.readfile("data/input/MIR_OT_ANTP_R22_K2_8.dxf")

print("DIAMETER MARKER TEXT VALUES IN DXF:")
print("=" * 80)

marker_texts = {}
for entity in doc.modelspace().query('*'):
    if entity.dxf.layer != DXF_DIAMETER_LAYER:
        continue
    
    entity_type = entity.dxftype()
    handle = entity.dxf.handle
    
    if entity_type == "TEXT":
        text_content = entity.dxf.text
        x, y, z = entity.dxf.insert
        marker_texts[handle] = (text_content, x, y, entity_type)
    elif entity_type == "MTEXT":
        text_content = entity.text
        x, y, z = entity.dxf.insert
        marker_texts[handle] = (text_content, x, y, entity_type)

print(f"Total marker sources: {len(marker_texts)}")
print()

# Group by text content
text_groups = {}
for handle, (text, x, y, etype) in marker_texts.items():
    if text not in text_groups:
        text_groups[text] = []
    text_groups[text].append((handle, x, y, etype))

# Show unique texts
print("UNIQUE MARKER TEXTS (with count):")
for text in sorted(text_groups.keys()):
    count = len(text_groups[text])
    
    # Try to extract diameter
    match = DIAMETER_LABEL_RE.search(text.replace(" ", ""))
    if match:
        extracted = f"DN{match.group(1)}"
        print(f"  '{text}' ({count} instances) → {extracted}")
    else:
        print(f"  '{text}' ({count} instances) → NO MATCH")

print()
print("SAMPLE MARKERS (first 10):")
for i, (handle, (text, x, y, etype)) in enumerate(list(marker_texts.items())[:10]):
    match = DIAMETER_LABEL_RE.search(text.replace(" ", ""))
    extracted = f"DN{match.group(1)}" if match else "NO MATCH"
    print(f"  {handle}: '{text}' @ ({x:.1f}, {y:.1f}) → {extracted}")
