# V1 Final Gate — Private Drawing Verification Procedure

Run only on an authorised local machine that holds `MIR_OT_ANTP_R22_K2_8.dxf`.
Never commit, upload or copy the drawing to a cloud service (Codespaces, Streamlit
Community Cloud, CI). Everything below is read-only with respect to the drawing; reports
are written to `data/output/` (git-ignored) and never overwrite existing files.

## 1. Prepare (Windows PowerShell, repository root)

```powershell
$git = "C:\Program Files\Git\cmd\git.exe"
& $git fetch origin
& $git switch v1-hardening
& $git rev-parse HEAD            # must equal the commit under review
& $git status --short            # must be empty

py -3.11 --version               # Python 3.11 required (python.org installer)
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

New-Item -ItemType Directory -Force data\input, data\output, data\baseline | Out-Null
Copy-Item "<authorised location>\MIR_OT_ANTP_R22_K2_8.dxf" data\input\
Get-FileHash data\input\MIR_OT_ANTP_R22_K2_8.dxf -Algorithm SHA256   # record in the acceptance report
& $git check-ignore data/input/MIR_OT_ANTP_R22_K2_8.dxf              # must print the path (ignored)

# main's modules for the V0 comparison (raw bytes; do not use PowerShell '>' redirection, it writes UTF-16)
python -c "from pathlib import Path; from tools.compare_v0_v1 import export_baseline; export_baseline('main', Path('data/baseline'), r'C:\Program Files\Git\cmd\git.exe')"
```

## 2. Run

```powershell
$env:MEP_BASELINE_DIR = "data\baseline"
$env:MEP_VALIDATION_REPORT = "data\output\v1_validation.md"

# a) full suite, including the 7 private-drawing tests and the equivalence tests
python -m pytest
# b) private tests only, verbose
python -m pytest -m private_data -v

# c) impact analysis of the known-issue groups on the real drawing
python tools\impact_analysis.py data\input\MIR_OT_ANTP_R22_K2_8.dxf --output data\output\impact_v1.md

# d) V0 (main) versus V1 on the real drawing; exit code 0 = every difference explained
python tools\compare_v0_v1.py data\input\MIR_OT_ANTP_R22_K2_8.dxf --baseline-dir data\baseline --output data\output\v0_v1.md
$LASTEXITCODE
```

## 3. Read the results

`data\output\v0_v1.md` contains: V0/V1 totals and their reconciliation, duplicates
removed, length per diameter (V0 label ↔ V1 label), Ø/DN row counts, unknown/candidate/
review/3D lengths, equipment/fitting/valve counts, every entity-level difference with the
V1 rule that causes it, and the V1 warnings (unsupported entities, block pipe length, XREFs,
unrecognised blocks).

Possible, explained differences on this drawing:

| Rule | What can change | Expected direction |
|---|---|---|
| V1-DIA-01 | Labels `DN15…DN76` become `Ø15…Ø76` if the markers are written `ø` | Labels only |
| V1-DUP-01 | Polylines that V0 removed as duplicates although their arcs differ | Total and entity count up; duplicates down |
| V1-ENT-02 | Mesh POLYLINEs on pipe layers | Total down |
| V1-DIA-05 | Mirrored arcs/polylines matched at their world position | UNKNOWN length changes |
| V1-DIA-02 | `%%c`, `⌀`, `Ду` markers now read | UNKNOWN length down |
| V1-DIA-04 | Only if text height × 8 exceeds 5 m (mm drawing) | Rare |
| V1-BLK-02 | MINSERT arrays | Equipment/fitting/valve counts up |

## 4. Acceptance rules

* `tools\compare_v0_v1.py` must report **ALL DIFFERENCES EXPLAINED** (exit code 0) and the
  total must reconcile with the entity-level differences.
* If a private test fails, **do not edit its expected values to make it pass.** Use
  `v0_v1.md` to show which documented rule causes each difference; record an engineering
  decision for each; only then update the baseline in a separate, reviewed commit.
* Any `UNEXPLAINED` row blocks the pilot.
* Record in the acceptance report: drawing SHA-256, commit, pytest summary line, the
  comparison verdict, and the warning list.

## 5. Pilot safeguards (LIM-13 upload retention, LIM-14 XSRF)

Current state: `.streamlit/config.toml` sets `enableXsrfProtection = false`; the dev
container starts Streamlit with `--server.enableCORS false --server.enableXsrfProtection false`;
uploads stay in `data/input/` indefinitely.

Minimum safe configuration for a controlled pilot (not applied in the repository; apply on
the pilot machine after approval):

```toml
# .streamlit/config.toml on the pilot machine
[server]
headless = true
address = "127.0.0.1"          # local only, not reachable from the network
port = 8501
enableXsrfProtection = true    # Streamlit default
enableCORS = true              # Streamlit default
maxUploadSize = 200            # MB

[client]
showErrorDetails = false

[browser]
gatherUsageStats = false
```

* Run `python -m streamlit run app.py` on a single-user Windows account with disk encryption;
  do not use the dev container, Codespaces or Streamlit Community Cloud with project drawings.
* Retention: review and purge uploads at the end of the pilot or monthly (operator action):

```powershell
Get-ChildItem data\input -Recurse -File | Where-Object LastWriteTime -lt (Get-Date).AddDays(-30)   # review list
# after approval only:
Get-ChildItem data\input -Recurse -File | Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) | Remove-Item
```

* Excel exports downloaded by users are outside the application's control; store them in the
  project's access-controlled folder.
