# MEP Takeoff V1 — Behaviour Contract

Status: release candidate `v1.0.0-rc1` (proposed, not tagged). Branch `v1-hardening`.

This document states what the application does for every rule that affects quantities,
classification, counts, the UI or the Excel export. Each rule names the regression tests
that lock it (test IDs appear in the CI validation report). Rules marked **ENG-xx** depend
on an engineering decision that has not been made; V1 keeps the V0 quantity and shows an
explicit warning until the decision is recorded (see `V1_KNOWN_LIMITATIONS.md`).

Affects: **Q** quantity (length), **C** classification (diameter/category), **N** counts
(equipment, fittings, valves), **UI** screen, **X** Excel export.

## 1. Upload, identity and cache

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-UP-01 Storage | Upload written to `data/input/<name>`, overwriting older uploads | Stored at `data/input/<sha256[:16]>/<safe name>`; never overwritten or deleted; a different file at the target path stops the upload | UI | UP-STORE-01…07, UP-NAME-01…12 | No |
| V1-UP-02 Same name, new content | Previous drawing's results shown | New content always re-read and recalculated; all cached results keyed by SHA-256 | Q C N UI X | UP-SESSION-04, UP-SESSION-09, UP-APP-01 (+ CI job reproducing the V0 defect) | No |
| V1-UP-03 Same content, new name | Re-stored under new name | Same stored file and cached result reused | UI | UP-SESSION-05, WF-02 | No |
| V1-UP-04 New analysis fails | Previous results could remain cached | Analysis state and report caches cleared on any upload, load or calculation failure | UI X | UP-SESSION-06/07, UP-SESSION-03, WF-03 | No |
| V1-UP-05 Empty upload | Stored and failed later | Rejected with "Загруженный файл пуст." | UI | UP-STORE-05, UP-SESSION-06, WF-04 | No |

## 2. Drawing loading

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-ERR-01 Valid DXF | Strict read | Strict read (`load mode = strict`); 999 comment headers accepted | — | LD-01, LD-05 | No |
| V1-ERR-02 Empty / non-DXF file | Generic error | Rejected as not a DXF; error shows the reason | UI | LD-02…04, BEH-ERR-01/02, WF-03, WF-04 | No |
| V1-ERR-03 Damaged / truncated DXF | Generic error or silent partial read | Opened with ezdxf recovery, `load mode = recovered`, warning `DRAWING_RECOVERED` with fix/error counts; rejected if unrecoverable. Never a silent partial result | Q UI X | LD-06, LD-07, WF-05 | ENG-15 (accept recovered results?) |
| V1-ERR-04 Error messages | Generic text | Error type and message shown (≤300 chars) for load, calculation and layer-analysis failures | UI | WF-03 | No |

## 3. Entities

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-ENT-01 Measured types | LINE, LWPOLYLINE, POLYLINE, ARC on included pipe layers | Unchanged | Q | GEO-LINE/ARC/PL-*, GEO-PIPE-01, BEH-CIRCLE-01 | No |
| V1-ENT-02 Mesh POLYLINE | Measured along its vertex list | Polyface/polygon-mesh POLYLINEs are unsupported (not measured, listed) | Q | KI-POL-03, EQ-INTENDED-mesh | No |
| V1-ENT-03 Unsupported entities on pipe layers | Silently ignored | Never measured or estimated; listed by layer, type, count and handles; warning `UNSUPPORTED_PIPE_ENTITIES` | UI X | W-UNS-01…05, UI-W-03, XLS-W-04 | No |
| V1-ENT-04 Paper space | Ignored | Ignored (model space only) — limitation LIM-03 | Q | — | No |

## 4. Units

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-UNIT-01 Known `$INSUNITS` | SI factors (mm, cm, m, in, ft, …) | Unchanged; manual override replaces the header factor | Q | UNIT-01…05, UNIT-0x-PIPE, UNIT-OVR-01…06 | No |
| V1-UNIT-02 Unknown units | Raw values labelled "Length (m)" | Raw values kept (no guessed conversion), labelled "drawing units" in report, UI and Excel; warning `UNKNOWN_UNITS` | UI X | UNIT-06, BEH-UNIT-01, W-UNIT-01/02, XLS-W-01/02, UI-W-01 | No |

## 5. Length basis (XY versus 3D)

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-3D-01 Reported length | Plan (XY) length; Z ignored silently | Reported quantity stays plan length (`length_basis = plan (XY projection)`). True 3D length is shown per entity (`Length 3D`) and in total; entities with Z variation are flagged `Z_VARIATION`; warning `Z_VARIATION_PLAN_LENGTH_REPORTED` gives the difference | Q(UI) UI X | KI-3D-01…04 | **ENG-01** |
| V1-3D-02 Vertical runs drawn as symbols | Symbol arcs counted, vertical length missing | Unchanged; full-circle arcs flagged (V1-POL-02). Vertical lengths are not derivable from plan symbols | Q | BEH-RISER-01, KI-POL-02 | **ENG-02** |

## 6. Pipe layers

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-LAYER-01 Inclusion | Name starts with `П_Трубы`, except exactly `П_Трубы_ Осевая линия` | Unchanged | Q | BEH-LAYER-01 | ENG-12 |
| V1-LAYER-02 Suspicious names | Silent | Counted/excluded as before; warning `PIPE_LAYER_NAME_REVIEW` for included centreline-like names, excluded case variants and XREF-dependent pipe layers (with length) | UI X | KI-LAYER-01/02 | **ENG-12** |
| V1-LAYER-03 Frozen/off pipe layers | Counted silently | Counted; warning `HIDDEN_PIPE_LAYER_COUNTED` | UI X | KI-LAYER-03 | **ENG-14** |
| V1-LAYER-04 User-selected pipe layers | — | Multiselect "Трубные слои в метраже"; default = V1-LAYER-01 rule (quantities identical). Any other selection includes exactly the chosen layers (`Pipe Layer Mode = manual`); no layer is added automatically. Selection is tied to the upload's SHA-256, so new content starts from the default | Q (manual only) UI X | PLS-01…03, PLS-UI-01/02 | No |
| V1-LAYER-05 Pipe-like layers outside the rule | Silent | Not counted; layers named like pipe (`pipe`, `труб`, any case) with measurable geometry get `PIPE_LIKE_LAYER_NOT_INCLUDED` (entities, measurable entities, raw length). Centreline, marker, equipment, fitting and valve layers are not reported. A name match is a hint, not a classification | UI X | PLW-01/02 | ENG-16 |
| V1-LAYER-06 Possible double-line pipes | Silent | Straight segments on included pipe layers with a parallel neighbour on the same layer (≤ 0.3 m apart; 300 drawing units if units unknown; side by side over ≥ 50 % of the shorter segment; segment ≥ 2× the distance) get `DOUBLE_LINE_PIPE`. Nothing is removed, merged or corrected; no centreline is derived | UI X | DL-01…06 | **ENG-17** |

## 7. Diameters

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-DIA-01 Notation | Every label written as `DN<n>` (outside diameter `ø16` became `DN16`) | `Ø<n>` for outside-diameter notation, `DN<n>` for nominal size; `Diameter Type` = OUTSIDE_DIAMETER / NOMINAL_DN / UNKNOWN; **no Ø↔DN conversion**; drawings using both get `MIXED_DIAMETER_NOTATION`; rows sorted DN by size, then Ø by size, then UNKNOWN | C UI X | BEH-DIA-01…13, KI-DIA-07, XLS-01 | **ENG-05** (material tables) |
| V1-DIA-02 Recognised notations | `DN`, `Ø`, `ø` | Adds AutoCAD `%%c` (→ Ø), `⌀` (→ Ø) and `Ду` (→ DN) | C | KI-DIA-02/03, BEH-DIA-08/09/13, EQ-INTENDED-new_label_notations | ENG-08 (`Ду`=DN) |
| V1-DIA-03 Matching | Nearest marker on `П_Марки труб` to the pipe reference point (LINE midpoint, polyline vertex centroid, ARC centre) within max(threshold, 8×text height) | Unchanged | C | BEH-DIA-20…26 | ENG-06 |
| V1-DIA-04 Search distance | 3000 drawing units (3 m only in mm drawings) | 3 m converted to drawing units when units are known; 3000 drawing units when unknown; marker grid always covers the search distance | C | KI-DIA-01, EQ-INTENDED-metres_far_marker | ENG-07 (confirm 3 m) |
| V1-DIA-05 Mirrored/tilted entities | Reference point taken in OCS | Reference point converted to world coordinates | C | KI-DIA-04, EQ-INTENDED-ocs_marker | No |
| V1-DIA-06 Markers beside the pipe but far from its reference point | UNKNOWN, no hint | Still UNKNOWN; markers within the search distance of the geometry are listed as `Diameter Candidates`; warning `DIAMETER_CANDIDATES_UNRESOLVED` | C(UI) UI X | KI-DIA-05/06/06b, WF-08 | **ENG-06** |
| V1-DIA-07 Unknown diameter | UNKNOWN rows | Unchanged; summary `unknown_diameter_length` | UI X | V1-OUT-02, W-EMPTY-03 | No |

## 8. Duplicates and overlaps

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-DUP-01 Exact duplicates | Same-layer, same type, same vertices (direction ignored) removed; **bulges ignored** | Same rule, identity now includes segment bulges (direction-independent, reversed bulge sign handled, closed polylines included) | Q | BEH-DUP-01…05, KI-DUP-01/01b/01c, EQ-INTENDED-bulge_pair | No |
| V1-DUP-02 Same-layer overlaps (incl. LINE = identical polyline) | Counted silently | Counted; rows flagged `OVERLAP_SAME_LAYER`; warning `OVERLAP_SAME_LAYER_COUNTED` with overlap length | Q(UI) UI X | KI-DUP-02, KI-DUP-04 | **ENG-03** |
| V1-DUP-03 Cross-layer overlaps / identical arcs | Counted silently | Counted; rows flagged `OVERLAP_ACROSS_LAYERS`; warning `OVERLAP_ACROSS_LAYERS_COUNTED` with overlap length | Q(UI) UI X | KI-DUP-03, KI-DUP-05 | **ENG-04** |

## 9. Blocks, symbols and XREFs

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-BLK-01 Pipe geometry inside blocks | Not measured, not reported | Not measured; reported per block (placed instances, nested blocks followed once per placement, MINSERT expanded); warning `PIPE_GEOMETRY_IN_BLOCKS_NOT_MEASURED`; sheet `БЛОКИ С ТРУБАМИ` | UI X | KI-BLK-01/01b, IMP-BLK-01 | **ENG-09** |
| V1-BLK-02 MINSERT arrays | Counted once | Counted rows × columns | N | KI-BLK-02, EQ-INTENDED-minsert | No |
| V1-BLK-03 Equipment tag layer | Counted as equipment silently | Counted; warning `EQUIPMENT_TAG_LAYER_COUNTED` | N(UI) | KI-BLK-03 | **ENG-10** |
| V1-BLK-04 Unrecognised blocks | Silently dropped | Listed (layer, block, count, MEP-layer flag) in UI and sheet `НЕ РАСПОЗНАНО`; warning `UNRECOGNIZED_SYMBOLS_ON_MEP_LAYERS` when on valve/fitting/equipment/pipe layers | UI X | KI-BLK-04, KI-BLK-06 | **ENG-11** |
| V1-BLK-05 Anonymous (dynamic) blocks | Classified by layer silently | Unchanged; warning `ANONYMOUS_BLOCKS_CLASSIFIED_BY_LAYER` | UI | KI-BLK-05 | No |
| V1-BLK-06 Classification keywords | Layer + block-name keywords | Unchanged | N | BEH-BLK-01 | No |
| V1-XREF-01 External references | Ignored silently | Not processed; listed (name, path, inserts); warning `XREF_NOT_PROCESSED` | UI X | W-XREF-01…04, UI-W-04 | No |

## 10. Closed and ambiguous geometry

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-POL-01 Closed polylines | Counted; debug note wrongly said "excluded" | Counted; flagged `CLOSED_POLYLINE`, `Geometry Status = REVIEW`; warning `CLOSED_POLYLINES_COUNTED`; note corrected | Q(UI) UI X | KI-POL-01, BEH-POL-01, WF-09 | **ENG-13** |
| V1-POL-02 Full-circle ARC (start = end) | Counted as full circle silently | Counted; flagged `FULL_CIRCLE_ARC`; warning `FULL_CIRCLE_ARCS_COUNTED` | Q(UI) UI X | KI-POL-02 | **ENG-13** |
| V1-POL-03 Review length | — | Summary `ambiguous_pipe_length` = length of rows with any review flag | UI X | KI-POL-01 | No |

## 11. Output

| Rule | V0 behaviour | V1 behaviour | Affects | Locked by | Approval |
|---|---|---|---|---|---|
| V1-OUT-01 No pipe geometry | Fake `UNKNOWN 0.0` row | No diameter rows; warning `NO_PIPE_GEOMETRY` | UI X | W-EMPTY-01…03, XLS-W-03, UI-W-02 | No |
| V1-OUT-02 Summary | Total, counts | Adds length basis, 3D total, unknown-diameter length, review length, unmeasured entity count, block pipe length, unrecognised block count, warning count, load mode | UI X | V1-OUT-02, KI-POL-01, KI-3D-01 | No |
| V1-OUT-03 Excel compatibility | — | All V0 sheets and columns keep their values for known units; V1 adds columns (`Тип диаметра`, `Длина 3D`, summary fields incl. `Pipe Layer Mode`, `Pipe Layers`) and sheets `ПРЕДУПРЕЖДЕНИЯ`, `НЕ ИЗМЕРЕНО`, `НЕ РАСПОЗНАНО`, `БЛОКИ С ТРУБАМИ`, `ТРУБНЫЕ СЛОИ` | X | XLS-01…17, XLS-W-01…04, EQ-XLS-01/02 | No |
| V1-OUT-04 UI = Excel | — | Diameter rows and warning codes in the UI equal the workbook | UI X | WF-07 | No |
| V1-OUT-05 Export failure | Uncaught exception | Error shown, on-screen results kept, download offered again on the next successful run | UI X | WF-06 | No |
| V1-OUT-06 Warnings visible | Partial | Every warning shown in the UI ("Предупреждения") and in sheet `ПРЕДУПРЕЖДЕНИЯ` with code, count, length and message | UI X | UI-W-01…05, WF-07…09 | No |

## 12. Invariants checked on every run

* Sum of per-diameter lengths equals the total (raises otherwise).
* Raw prefixed length − excluded centreline − removed duplicates − final = 0 (BEH-LAYER-01).
* Measured + listed-unsupported entities = all entities on included pipe layers (W-UNS-04).
* For fixtures without an intended change, quantities and classifications equal `main`
  exactly (EQ-*); every intended change alters only its documented report paths (EQ-INTENDED-*).
