# MEP Takeoff V1 — User Guide (controlled pilot)

V1 measures pipe lengths and counts MEP symbols in one DXF drawing that follows the
project layer standard (`П_Трубы*`, `П_Марки труб`, `Оборудование`,
`Соединительные детали трубопроводов`, `Арматура трубопроводов`). It is a review aid
for MEP engineers, not a purchase-grade takeoff: every result must be checked against
the warnings it shows.

## 1. Run

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Use a local or private machine only. Uploaded drawings are stored in `data/input/` and
are never sent anywhere.

## 2. Workflow

1. **Upload a DXF.** DWG is not accepted; export DXF from AutoCAD first.
   * A file with the same name but new content is always recalculated.
   * Empty or non-DXF files are rejected with the reason.
   * A damaged DXF is opened in recovery mode and marked `DRAWING_RECOVERED`; check the
     result against the original drawing.
2. **Check units.** "Единицы чертежа" shows `$INSUNITS`. If it is unknown, lengths stay in
   drawing units (never labelled as metres). Choose the unit in the sidebar to convert.
3. **Read "Общий результат".**
   * *Общая длина труб* — plan (XY) length of measured pipe geometry.
   * *3D-длина* — true length including height changes (differs only if Z varies).
   * *Без диаметра (UNKNOWN)* — length without an assigned diameter.
   * *Геометрия для проверки* — length of entities flagged for review.
   * *Неизмеренные объекты* — entities on pipe layers that were not measured.
4. **Read "Предупреждения".** Each warning has a code (table below). Tables list unmeasured
   entities, XREFs, pipe geometry inside blocks, unrecognised blocks and pipe layers to check.
5. **Review "Трубы по диаметрам".**
   * `Ø16` = outside diameter written on the drawing; `DN16` = nominal size. They are never
     converted into each other.
   * Order: DN by size, Ø by size, then UNKNOWN.
6. **Review the detail table.** `Geometry Flags` and `Geometry Status = REVIEW` mark
   entities whose length is counted but needs an engineering check. `Diameter Candidates`
   lists markers that are near a pipe but were not used to assign its diameter.
7. **Download Excel.** If the export fails, an error is shown and the on-screen results
   remain valid; run again to download.

## 3. Warning codes

| Code | Meaning | What to do |
|---|---|---|
| `UNKNOWN_UNITS` | `$INSUNITS` missing; lengths in drawing units | Select the unit in the sidebar |
| `NO_PIPE_GEOMETRY` | No measurable geometry on pipe layers | Check layer names / drawing content |
| `UNSUPPORTED_PIPE_ENTITIES` | SPLINE, ELLIPSE, text, blocks… on pipe layers not measured | Review the listed handles |
| `XREF_NOT_PROCESSED` | External references are not loaded | Bind XREFs or analyse them separately |
| `DRAWING_RECOVERED` | Damaged DXF opened in recovery mode | Verify against the source drawing |
| `Z_VARIATION_PLAN_LENGTH_REPORTED` | Some pipes are sloped/vertical; plan length reported | Decide the length basis (ENG-01) |
| `CLOSED_POLYLINES_COUNTED` | Closed polylines counted as pipe | Confirm they are pipes (ENG-13) |
| `FULL_CIRCLE_ARCS_COUNTED` | Full-circle arcs counted (often riser symbols) | Confirm (ENG-13) |
| `OVERLAP_SAME_LAYER_COUNTED` | Overlapping geometry on one layer counted twice | Clean the drawing or decide (ENG-03) |
| `OVERLAP_ACROSS_LAYERS_COUNTED` | Same/overlapping geometry on two pipe layers | Decide (ENG-04) |
| `DIAMETER_CANDIDATES_UNRESOLVED` | Markers near pipes without a diameter | Assign manually (ENG-06) |
| `MIXED_DIAMETER_NOTATION` | Drawing uses both Ø and DN | Do not add Ø and DN totals together |
| `PIPE_GEOMETRY_IN_BLOCKS_NOT_MEASURED` | Pipe-layer lines inside blocks not counted | Decide per block (ENG-09) |
| `UNRECOGNIZED_SYMBOLS_ON_MEP_LAYERS` | Blocks on MEP layers not counted | Review the list (ENG-11) |
| `EQUIPMENT_TAG_LAYER_COUNTED` | Blocks on the tag layer counted as equipment | Check for double counting (ENG-10) |
| `ANONYMOUS_BLOCKS_CLASSIFIED_BY_LAYER` | Dynamic blocks classified by layer only | Check equipment/fitting counts |
| `PIPE_LAYER_NAME_REVIEW` | Centreline-like layer included or pipe-layer variant excluded | Check the layer standard (ENG-12) |
| `HIDDEN_PIPE_LAYER_COUNTED` | Frozen/off pipe layer counted | Decide (ENG-14) |

## 4. Excel workbook

| Sheet | Content |
|---|---|
| СВОДКА | Totals, units, length basis, 3D total, unknown/review lengths, unmeasured/unrecognised counts, warnings, load mode |
| ПО ДИАМЕТРУ | Length per diameter with `Тип диаметра` and share |
| ТРУБЫ | Every measured pipe entity: handle, layer, plan and 3D length, diameter, evidence, candidates, flags |
| UNKNOWN_REVIEW | Pipes without diameter, with candidates |
| ОБОРУДОВАНИЕ / ФИТИНГИ / КЛАПАНЫ | Counts (MINSERT arrays counted per instance) |
| СЛОИ, ДЕТАЛИ, ТИПЫ ОБЪЕКТОВ, CATEGORY_DIAMETER | As in V0 |
| ПРЕДУПРЕЖДЕНИЯ | All warnings: code, count, length, message |
| НЕ ИЗМЕРЕНО | Unmeasured entities on pipe layers |
| НЕ РАСПОЗНАНО | Blocks not counted (with MEP-layer flag) |
| БЛОКИ С ТРУБАМИ | Pipe-layer geometry inside blocks (not counted) |

Length columns carry their unit (`м` or `ед. чертежа`).
