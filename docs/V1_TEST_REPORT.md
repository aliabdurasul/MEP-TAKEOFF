# MEP Takeoff V1 — Test Report

Branch `v1-hardening`, code under test `161ec62`. Python 3.11, pytest 9.1.1, GitHub Actions.
No test was run on a local machine (no Python interpreter is installed there).

## Results

| Run | Commit | Ubuntu | Windows | Notes |
|---|---|---|---|---|
| Baseline before V1 | `500beb3` | 176 PASS / 20 FAIL / 7 NOT RUN | identical | 20 FAIL = known issues tracked as strict xfail |
| V1 tests first | `ae616ce` | collection error (exit 2) | collection error (exit 2) | Tests import V1 APIs (`load_dxf`, `measure_entity_3d`) that did not exist yet |
| V1 fixes, first run | `64b1326` | 224 PASS / 5 FAIL / 7 NOT RUN | identical | 5 equivalence failures: harness bound `main`'s app to this branch's geometry; row order after label rename |
| Harness fix | `567f8ee` | 207 PASS / 23 FAIL / 7 NOT RUN | — | Baseline loader could not import `main`'s dataclass module |
| **Release candidate** | **`161ec62`** | **230 PASS / 0 FAIL / 7 NOT RUN** | **230 PASS / 0 FAIL / 7 NOT RUN** | [run 39574292762](https://github.com/aliabdurasul/MEP-TAKEOFF/actions/runs/39574292762) |

Per-check status is identical on Ubuntu and Windows. Full tables (ID, rule, geometry/units,
expected, actual, differences, status):
[Ubuntu](https://github.com/aliabdurasul/MEP-TAKEOFF/runs/119136134315),
[Windows](https://github.com/aliabdurasul/MEP-TAKEOFF/runs/119136438837).
The job "stale-upload bug reproduces with app.py from main" passed: `main` shows
`['5.00 m', '5.00 m']` after a same-name re-upload of a 10 m drawing (the V0 defect);
V1 shows `['5.00 m', '10.00 m']`.

## Release-candidate checks by category

| Category | Checks | PASS | FAIL | NOT RUN |
|---|---|---|---|---|
| MATH (closed-form references) | 52 | 52 | 0 | 0 |
| BEHAVIOR (V0 rules kept) | 38 | 38 | 0 | 0 |
| UPLOAD (storage, session, cache) | 29 | 29 | 0 | 0 |
| WARNING (Stage 2A visibility) | 24 | 24 | 0 | 0 |
| CONTRACT (V1 rules incl. former known issues, loading) | 40 | 40 | 0 | 0 |
| WORKFLOW (Streamlit end to end) | 8 | 8 | 0 | 0 |
| EQUIVALENCE (vs `main`) | 23 | 23 | 0 | 0 |
| IMPACT (analysis tool) | 16 | 16 | 0 | 0 |
| Private drawing | 7 | 0 | 0 | 7 |
| **Total** | **237** | **230** | **0** | **7** |

No strict-xfail tests remain. Open engineering decisions are locked as contract behaviour
(V0 quantity plus mandatory warning) and tracked in `V1_KNOWN_LIMITATIONS.md`.

## Not run

The 7 private-drawing tests (`test_real_dxf_hardening.py` ×6, `test_impact_private.py` ×1)
need `data/input/MIR_OT_ANTP_R22_K2_8.dxf`, which is not in Git or CI by design. They were
**not run** and the real drawing is **not verified** for V1. The diameter keys in the
private test were changed from `DN15…DN76` to `Ø15…Ø76` (V1-DIA-01, audit evidence that
the markers are written `ø`); the numeric expectations are unchanged.

## Defects found while hardening

* The first equivalence harness loaded `main`'s `app.py` against the branch's `geometry.py`,
  so geometry changes were invisible to the comparison. Fixed in `51644db`, proven by
  EQ-BASE-01 and by the intended-change fixtures now showing `main`'s values.
* Collection errors were not visible in the validation report. Fixed in `51644db`.
