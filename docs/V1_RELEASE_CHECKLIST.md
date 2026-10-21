# MEP Takeoff V1 — Release Checklist (`v1.0.0-rc1`, proposed)

Do not tag, merge or deploy until every blocking item is checked and approved.

## Automated (done in CI)

- [x] All blocking automated tests pass on Ubuntu and Windows (Python 3.11): 230 PASS / 0 FAIL / 7 NOT RUN.
- [x] V0 stale-upload defect reproduced against `main` and fixed on the branch.
- [x] Quantities and classifications equal `main` for all fixtures without an intended change (duplicate removal on and off).
- [x] Every intended change alters only its documented report paths, with documented before/after values.
- [x] Units: unknown units never labelled as metres in report, UI or Excel.
- [x] UI and Excel agree on diameter rows and warning codes.
- [x] Excel export failure is visible and recoverable; previous results cleared when a new analysis fails.
- [x] No CAD drawings committed (CI guard).

## Blocking before a controlled pilot (not done)

- [ ] **Run the private suite locally** in an authorised environment with Python 3.11:
      `python -m pytest -m private_data` (7 tests). Expected: all pass. If a numeric
      assertion fails, explain the difference with the impact tool before changing any baseline.
- [ ] **Run the impact tool** on the private drawing:
      `python tools/impact_analysis.py data/input/MIR_OT_ANTP_R22_K2_8.dxf --output data/output/impact_v1.md`
      and record: bulge-differing polylines kept, MINSERT instances, OCS entities,
      unit-aware threshold (3 m), overlaps, block pipe length, unrecognised blocks.
- [ ] **Compare V1 with V0 on the private drawing** with `tools/compare_v0_v1.py`
      (procedure: `V1_PRIVATE_VERIFICATION.md`). The verdict must be
      "ALL DIFFERENCES EXPLAINED"; every difference maps to a rule in `V1_CHANGELOG.md`.
- [ ] **Pilot safeguards** applied on the pilot machine (local-only address, XSRF/CORS on,
      upload retention procedure) — `V1_PRIVATE_VERIFICATION.md` §5.
- [ ] **Engineering sign-off** recorded for the decisions needed for the pilot scope
      (at least ENG-01, ENG-05, ENG-12, ENG-13; see `V1_KNOWN_LIMITATIONS.md`).
- [ ] Manual UI check in a browser with the private drawing (warnings readable, Excel opens).

## Release steps (after approval only)

- [ ] Review and approve the pull request from `v1-hardening`.
- [ ] Tag `v1.0.0-rc1` on the approved commit.
- [ ] Merge according to the repository policy; deploy only to a controlled, single-user pilot environment (LIM-13, LIM-14).
