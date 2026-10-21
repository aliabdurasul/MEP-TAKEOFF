# MEP Takeoff V1 — Known Limitations and Open Engineering Decisions

Every item below is visible to the user (warning, flag, table or Excel sheet) unless stated
otherwise. None of them was resolved by choosing an engineering or procurement convention
in code.

## Open engineering decisions (ENG)

| ID | Question | Options | V1 behaviour until decided | User sees |
|---|---|---|---|---|
| ENG-01 | Is the takeoff quantity the plan (XY) length or the true 3D length? | (a) plan length; (b) 3D length; (c) both, 3D for sloped/vertical runs only | (a) plan length reported; 3D shown | `Length 3D` column, 3D total, `Z_VARIATION` flag, warning `Z_VARIATION_PLAN_LENGTH_REPORTED` |
| ENG-02 | Where do vertical riser/drop lengths come from? | storey heights, sections, axonometric drawings, manual entry | Not measured; symbol arcs counted as drawn | `FULL_CIRCLE_ARCS_COUNTED`; limitation LIM-01 |
| ENG-03 | Should same-layer collinear overlaps (incl. a LINE and an identical polyline) be merged? | keep both; merge to union length; merge only identical geometry | Keep both (V0 quantity) | `OVERLAP_SAME_LAYER` flag, warning with overlap length |
| ENG-04 | Is identical/overlapping geometry on two pipe layers one pipe? | count both; count once; layer priority rule | Count both (V0 quantity) | `OVERLAP_ACROSS_LAYERS` flag, warning with overlap length |
| ENG-05 | How are outside diameters (Ø) related to nominal sizes (DN)? | material-specific tables (steel, PEX, PP-R, copper …) | No conversion; Ø and DN reported separately | `Diameter Type`, `MIXED_DIAMETER_NOTATION` |
| ENG-06 | May a diameter be assigned from a marker that is near the pipe but not near its reference point? | keep V0 reference-point rule; nearest marker to geometry; leader/arrow analysis | V0 rule; nearby markers listed as candidates, not assigned | `Diameter Candidates`, `DIAMETER_CANDIDATES_UNRESOLVED` |
| ENG-07 | Is 3 m the right marker search distance? | 3 m (V0 intent for mm drawings), other value, text-height based | 3 m in any unit (3000 drawing units if units unknown) | `Marker Threshold` per pipe |
| ENG-08 | Is `Ду` notation equivalent to `DN`? | yes (GOST "условный проход"); treat separately | Read as `DN` | Diameter label `DN<n>` |
| ENG-09 | Is pipe-layer geometry inside blocks real pipe or symbol graphics? | count; ignore; per-block decision list | Not counted; reported per block with length | `PIPE_GEOMETRY_IN_BLOCKS_NOT_MEASURED`, sheet `БЛОКИ С ТРУБАМИ` |
| ENG-10 | Are blocks on `Марки оборудования` equipment or tags? | equipment; tags (exclude); per block name | Counted as equipment (V0) | `EQUIPMENT_TAG_LAYER_COUNTED` |
| ENG-11 | How should unrecognised valve-layer and fitting symbols be categorised? | keyword list extension; block attribute mapping; manual table | Listed, not counted | `UNRECOGNIZED_SYMBOLS_ON_MEP_LAYERS`, sheet `НЕ РАСПОЗНАНО` |
| ENG-12 | What is the project layer standard (pipe layers, centrelines, variants)? | per-project rule profile | V0 single-project rule (prefix `П_Трубы`, exact centreline name) | `PIPE_LAYER_NAME_REVIEW` with length |
| ENG-13 | Are closed polylines and full-circle arcs on pipe layers pipe? | count; exclude; per-layer rule | Counted (V0), flagged for review | `CLOSED_POLYLINE`, `FULL_CIRCLE_ARC` flags, review length |
| ENG-14 | Should frozen/off pipe layers be counted? | count; exclude | Counted (V0) | `HIDDEN_PIPE_LAYER_COUNTED` |
| ENG-15 | Are quantities from a recovered (damaged) drawing acceptable? | accept with review; reject | Calculated, marked recovered | `DRAWING_RECOVERED`, `Load Mode` |

## Technical limitations (LIM)

| ID | Limitation | Visible to user |
|---|---|---|
| LIM-01 | Vertical pipe length that exists only as symbols in plan drawings cannot be measured. | Warning text, ENG-02 |
| LIM-02 | XREF content is not loaded or measured. | `XREF_NOT_PROCESSED` |
| LIM-03 | Only model space is analysed; paper-space geometry is ignored. | This document only |
| LIM-04 | SPLINE, ELLIPSE, MLINE, HATCH, solids, text and other non-linear types on pipe layers are not measured. | `UNSUPPORTED_PIPE_ENTITIES`, sheet `НЕ ИЗМЕРЕНО` |
| LIM-05 | Dynamic block effective names are not resolved; anonymous blocks are classified by layer only. | `ANONYMOUS_BLOCKS_CLASSIFIED_BY_LAYER` |
| LIM-06 | Overlap detection covers straight segments (LINE and straight polyline segments) and identical ARCs across layers; overlapping bulged polyline segments are not detected. Tolerances: angle 1e-7 rad, offset 1e-3 drawing units. | This document only |
| LIM-07 | Duplicate identity does not treat a closed polyline that starts at a different vertex as identical. | This document only |
| LIM-08 | Layer rules, marker layer and symbol layers are hard-coded for one project standard (`П_Трубы`, `П_Марки труб`, …). | ENG-12 warning for variants |
| LIM-09 | The legacy `Category` (X/Z) column is a plan-direction heuristic, not an axis classification. | Column retained for compatibility only |
| LIM-10 | DWG files cannot be uploaded; the experimental DWG code path (ezdwg) is not part of V1 and still labels diameters as DN. | Uploader accepts `.dxf` only |
| LIM-11 | Recovery mode can lose damaged entities; counts of fixes/errors come from ezdxf's auditor. | `DRAWING_RECOVERED` |
| LIM-12 | Up to 20 handles are listed per unsupported-entity group; counts are always complete. | Table text "… (+n)" |
| LIM-13 | Stored uploads are kept indefinitely in `data/input/`; no retention policy. | Operations only |
| LIM-14 | The Streamlit configuration disables XSRF protection (V0 setting); acceptable only for a single-user local pilot. | Operations only |
| LIM-15 | Results on the private project drawing have not been verified in this release (the drawing was not available to CI). | Release checklist |
