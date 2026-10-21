# MEP Takeoff V1 — Change Log

Base: `main` @ `71d4762`. All work is on feature branches; nothing is merged or deployed.

## Stage 1 — upload reliability (`fix/upload-cache-and-validation-tests`)

| Commit | Change | Effect |
|---|---|---|
| `4dba68c` | Content-addressed upload storage, SHA-256 cache keys, state reset on new upload and errors; synthetic validation tests; CI | Fixes stale results after a same-name re-upload (reproduced against `main` in CI) |
| `511c782`, `978619b` | CI validation report published as a public check run; UTF-8 output | Reporting only |

## Stage 2A — warnings (`fix/upload-cache-and-validation-tests`)

| Commit | Change | Effect |
|---|---|---|
| `b58d908` | Tests first | — |
| `8a5a336` | Unknown-unit labels, no placeholder row, unmeasured entities and XREFs reported | Placeholder `UNKNOWN 0.0` row removed; no quantity change |

## Stage 2B — impact analysis (`fix/upload-cache-and-validation-tests`)

| Commit | Change | Effect |
|---|---|---|
| `500beb3` | Read-only `tools/impact_analysis.py` | No quantity change |

## V1 hardening (`v1-hardening`)

| Commit | Change | Effect on quantities / classification / counts |
|---|---|---|
| `ae616ce` | Tests first: contract, loading, workflow, equivalence redesign; known-issue strict-xfail tests replaced by contract tests | — |
| `52bd37b` | Geometry: bulge-aware polyline identity; mesh POLYLINE unsupported; `measure_entity_3d` | **Q**: polylines that differ only in arcs are no longer removed as duplicates; mesh polylines no longer measured |
| `a9c1149` | Loading: DXF validation, explicit recovery mode | Invalid files rejected; damaged files marked recovered |
| `de21087` | Diagnostics: overlaps, block content, layer findings, warnings | None (reporting) |
| `f1048fc` | Takeoff/UI/Excel: Ø vs DN, `%%c`/`⌀`/`Ду`, 3 m marker distance in any unit, OCS→WCS, candidates, MINSERT, unrecognised blocks, review flags, summary fields, Excel sheets, export-failure handling, error details | **C**: outside-diameter labels `Ø<n>` instead of `DN<n>`; new notations recognised; metre/inch drawings use 3 m physical distance; mirrored arcs/polylines matched at world position. **N**: MINSERT counted per instance. **Q**: none |
| `64b1326` | Impact tool shares V1 diagnostics | — |
| `51644db` | Equivalence tests bind `main`'s app to `main`'s geometry/dxf_reader/excel_export; collection errors reported | Test harness correctness |
| `567f8ee` | Diameter rows sorted DN by size, Ø by size, UNKNOWN last | Row order only |
| `161ec62` | Baseline modules registered before execution | Test harness correctness |

## Intended changes versus `main` (synthetic evidence, EQ-INTENDED-*)

| Fixture | Rule | `main` | V1 |
|---|---|---|---|
| Straight + semicircle polyline on same vertices | V1-DUP-01 | total 2.000000 m, 1 duplicate removed | total 5.141593 m, 0 removed |
| MINSERT 2×3 radiator | V1-BLK-02 | equipment 1 | equipment 6 |
| Mirrored ARC + `DN20` near its world centre | V1-DIA-05 | UNKNOWN | DN20 |
| `%%c16` and `Ду15` markers | V1-DIA-02 | UNKNOWN, UNKNOWN | Ø16, DN15 |
| Metre drawing, `ø20` 100 m away | V1-DIA-04 | DN20 | UNKNOWN |
| Polyface mesh + 1000 mm LINE | V1-ENT-02 | total > 1 m (mesh measured), 2 pipe entities | 1.000000 m, 1 pipe entity |
| Empty drawing / no pipe geometry | V1-OUT-01 | `UNKNOWN 0.0` row | no rows + `NO_PIPE_GEOMETRY` |
| Any `ø` marker | V1-DIA-01 | `DN<n>` | `Ø<n>` (same length) |

All other synthetic fixtures (mixed millimetre drawing, unknown units, inch drawing with
bulges, unsupported entities, XREF) produce exactly `main`'s quantities and
classifications (EQ-*), with duplicate removal on and off.
