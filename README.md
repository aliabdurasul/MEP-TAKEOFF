# MEP Quantity Takeoff V0

A lightweight pilot application for DXF-based MEP pipe quantity takeoff. It reads a DXF drawing, filters relevant pipe geometry, removes obvious duplicates, summarizes total length by diameter, lists unknown entries, and exports a workbook for review.

## Supported input

- DXF: primary workflow for deployment and pilot use
- DWG: optional and environment-dependent; not required for the DXF-first deployment path

## Local installation

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally

```bash
python -m streamlit run app.py
```

## Streamlit Community Cloud deployment

1. Push this repository to GitHub.
2. Create a new app on Streamlit Community Cloud.
3. Set the app entry file to `app.py`.
4. Use the repository root as the project root.
5. Let Streamlit install dependencies from `requirements.txt`.

## User workflow

1. Upload a DXF file.
2. Review the detected layer summary and drawing units.
3. Inspect the total pipe length, diameter breakdown, and unknown entries.
4. Download the Excel workbook for project review.

## Known limitations

- This is a V0 pilot helper, not a purchase-grade quantity system.
- Unknown diameter cases may still require engineering review.
- Centerline and auxiliary-layer semantics require project validation.
- ARC-based pipe semantics may require domain review.
- Partial overlap / near-duplicate geometry remains a review item.

## Deployment notes

- Real project DXF/DWG and generated output files are excluded from Git.
- Secrets and environment files are not committed.
- The app is designed to run in the browser without requiring local CAD tooling.
- The DWG reader is optional; DXF remains the primary supported workflow for deployment.

## Important baseline

The V0 calculation baseline must remain stable for regression testing:

- Raw accepted: 2016.964818224039 m
- Duplicate: 1.829030895583 m
- Final: 2015.135787328415 m
- Unknown: 290.710181 m

Do not modify the calculation logic without explicit engineering review and regression revalidation.
