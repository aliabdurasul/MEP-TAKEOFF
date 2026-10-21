"""Upload identity and analysis-cache rules, independent of Streamlit.

``state`` is any mutable mapping; in the app it is ``st.session_state``.
Cached analysis results are keyed by the SHA-256 of the uploaded content,
never by the file name.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mep_takeoff.uploads import EmptyUploadError, StoredUpload, sha256_bytes, store_upload

ANALYSIS_STATE_KEYS = (
    "drawing_kind",
    "drawing_doc",
    "dwg_entities",
    "dxf_doc",
    "insunits",
    "layers_table",
    "calculation",
    "calculation_key",
    "dxf_layer_calculation",
    "dxf_layer_calculation_key",
    "selected_layer",
    "converted_path",
    "source_path",
    "dxf_report",
    "dxf_report_key",
    "dwg_report",
    "dwg_report_key",
    "load_info",
)

REPORT_STATE_KEYS = {
    "dxf_report": "dxf_report_key",
    "dwg_report": "dwg_report_key",
    "dxf_layer_calculation": "dxf_layer_calculation_key",
}


@dataclass(frozen=True)
class UploadRegistration:
    sha256: str
    changed: bool
    stored: StoredUpload | None


def reset_analysis_state(state: MutableMapping[str, Any]) -> None:
    for key in ANALYSIS_STATE_KEYS:
        state[key] = None


def invalidate_report(state: MutableMapping[str, Any], report_key: str) -> None:
    state[report_key] = None
    state[REPORT_STATE_KEYS[report_key]] = None


def report_cache_key(upload_sha256: str | None, *parts: Any) -> tuple:
    if not upload_sha256:
        raise ValueError("A content hash is required to build a report cache key.")
    return (upload_sha256, *parts)


def register_upload(
    state: MutableMapping[str, Any],
    data: bytes,
    original_name: str | None,
    input_dir: str | Path,
) -> UploadRegistration:
    """Record the current upload, resetting cached analysis when content changes.

    On any failure the analysis state and upload identity are cleared so that
    results from a previous drawing cannot be shown for the new upload.
    """

    if not data:
        reset_analysis_state(state)
        state["upload_signature"] = None
        raise EmptyUploadError("Uploaded file is empty.")

    digest = sha256_bytes(data)
    changed = state.get("upload_signature") != digest
    if changed:
        reset_analysis_state(state)
        state["upload_signature"] = None

    source_path = state.get("source_path")
    if not changed and source_path and Path(source_path).is_file():
        state["upload_name"] = original_name
        return UploadRegistration(sha256=digest, changed=False, stored=None)

    try:
        stored = store_upload(data, original_name, input_dir)
    except Exception:
        reset_analysis_state(state)
        state["upload_signature"] = None
        raise

    state["upload_signature"] = digest
    state["upload_name"] = original_name
    state["source_path"] = str(stored.path)
    return UploadRegistration(sha256=digest, changed=changed, stored=stored)
