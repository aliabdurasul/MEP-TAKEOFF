"""Session reset, content-hash cache keys and the same-name re-upload scenario."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import app
from mep_takeoff.session_state import (
    ANALYSIS_STATE_KEYS,
    invalidate_report,
    register_upload,
    report_cache_key,
    reset_analysis_state,
)
from mep_takeoff.uploads import HASH_DIR_LENGTH, EmptyUploadError, UploadIntegrityError
from synthetic_dxf import INSUNITS_MM, MM_TO_M, add_line, new_doc, to_bytes


def _populated_state() -> dict:
    state = {key: f"old-{key}" for key in ANALYSIS_STATE_KEYS}
    state.update({"unit_override": "mm", "remove_duplicate_geometry": False, "upload_signature": "old-signature"})
    return state


def test_reset_clears_all_cached_analysis(validation):
    """Reset clears every cached drawing/report key, including source_path and both report caches."""
    state = _populated_state()
    reset_analysis_state(state)
    required = {"source_path", "dxf_report", "dxf_report_key", "dwg_report", "dwg_report_key", "dxf_layer_calculation"}
    validation.equal(
        "UP-SESSION-01",
        "reset clears analysis keys, keeps user settings",
        expected=(True, set(), ("mm", False)),
        actual=(
            required <= set(ANALYSIS_STATE_KEYS),
            {key for key in ANALYSIS_STATE_KEYS if state[key] is not None},
            (state["unit_override"], state["remove_duplicate_geometry"]),
        ),
        basis="session dict with every analysis key populated",
        kind="UPLOAD",
    )


def test_report_cache_key_uses_content_hash(validation):
    """Cache keys differ when only the content hash differs, and a hash is mandatory."""
    key_a = report_cache_key("a" * 64, "Auto", 4, True)
    key_b = report_cache_key("b" * 64, "Auto", 4, True)
    with pytest.raises(ValueError):
        report_cache_key(None, "Auto", 4, True)
    validation.equal(
        "UP-SESSION-02",
        "cache key = (sha256, settings...)",
        expected=(("a" * 64, "Auto", 4, True), True),
        actual=(key_a, key_a != key_b),
        basis="same settings, two different hashes",
        kind="UPLOAD",
    )


def test_invalidate_report_clears_value_and_key(validation):
    """A failed calculation leaves neither a stale report nor its key behind."""
    state = {"dxf_report": {"total": 1}, "dxf_report_key": ("x",)}
    invalidate_report(state, "dxf_report")
    validation.equal(
        "UP-SESSION-03",
        "invalidate on error",
        expected=(None, None),
        actual=(state["dxf_report"], state["dxf_report_key"]),
        basis="cached DXF report",
        kind="UPLOAD",
    )


def test_same_name_new_content_resets_cache(tmp_path, validation):
    """Re-uploading a different file under the same name resets the cache and points to the new bytes."""
    state: dict = {}
    first = register_upload(state, b"revision A", "plan.dxf", tmp_path)
    key_a = report_cache_key(state["upload_signature"], "Auto", 4, True)
    state["dxf_report"] = "report for A"
    state["dxf_report_key"] = key_a

    second = register_upload(state, b"revision B", "plan.dxf", tmp_path)
    key_b = report_cache_key(state["upload_signature"], "Auto", 4, True)
    validation.equal(
        "UP-SESSION-04",
        "stale-upload fix: same name, new content",
        expected=(True, True, None, None, True, b"revision B", hashlib.sha256(b"revision B").hexdigest()),
        actual=(
            first.changed,
            second.changed,
            state["dxf_report"],
            state["dxf_report_key"],
            key_a != key_b,
            Path(state["source_path"]).read_bytes(),
            state["upload_signature"],
        ),
        basis="two uploads named plan.dxf",
        kind="UPLOAD",
    )


def test_same_content_keeps_cache(tmp_path, validation):
    """Re-running with identical content keeps the cached report."""
    state: dict = {}
    register_upload(state, b"revision A", "plan.dxf", tmp_path)
    state["dxf_report"] = "report for A"
    again = register_upload(state, b"revision A", "plan.dxf", tmp_path)
    validation.equal(
        "UP-SESSION-05",
        "same content -> cache reused",
        expected=(False, "report for A"),
        actual=(again.changed, state["dxf_report"]),
        basis="identical bytes uploaded twice",
        kind="UPLOAD",
    )


def test_empty_upload_clears_previous_results(tmp_path, validation):
    """An empty upload raises and leaves no previous analysis visible."""
    state: dict = {}
    register_upload(state, b"revision A", "plan.dxf", tmp_path)
    state["dxf_report"] = "report for A"
    with pytest.raises(EmptyUploadError):
        register_upload(state, b"", "plan.dxf", tmp_path)
    validation.equal(
        "UP-SESSION-06",
        "empty upload -> state cleared",
        expected=(None, None, None),
        actual=(state["upload_signature"], state["dxf_report"], state["source_path"]),
        basis="valid upload followed by 0-byte upload",
        kind="UPLOAD",
    )


def test_storage_error_clears_previous_results(tmp_path, validation):
    """If the upload cannot be stored, previous analysis results are cleared."""
    state: dict = {}
    register_upload(state, b"revision A", "plan.dxf", tmp_path)
    state["dxf_report"] = "report for A"
    data = b"revision B"
    blocked = tmp_path / hashlib.sha256(data).hexdigest()[:HASH_DIR_LENGTH] / "plan.dxf"
    blocked.parent.mkdir(parents=True)
    blocked.write_bytes(b"tampered")
    with pytest.raises(UploadIntegrityError):
        register_upload(state, data, "plan.dxf", tmp_path)
    validation.equal(
        "UP-SESSION-07",
        "storage error -> state cleared",
        expected=(None, None, None),
        actual=(state["upload_signature"], state["dxf_report"], state["source_path"]),
        basis="target path occupied by different bytes",
        kind="UPLOAD",
    )


def test_same_content_after_reset_restores_source(tmp_path, validation):
    """After an error reset, the same upload is re-registered without creating a second file."""
    state: dict = {}
    register_upload(state, b"revision A", "plan.dxf", tmp_path)
    path_before = state["source_path"]
    reset_analysis_state(state)
    again = register_upload(state, b"revision A", "plan.dxf", tmp_path)
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    validation.equal(
        "UP-SESSION-08",
        "re-register after reset",
        expected=(path_before, False, 1),
        actual=(state["source_path"], again.stored.created, len(files)),
        basis="reset between two identical uploads",
        kind="UPLOAD",
    )


def _drawing_with_pipe(length_mm: float) -> bytes:
    doc = new_doc(INSUNITS_MM)
    add_line(doc, (0, 0), (length_mm, 0))
    return to_bytes(doc)


def test_same_name_reupload_recalculates_from_new_drawing(tmp_path, validation):
    """End to end: the second same-name drawing is measured from its own content."""
    state: dict = {}
    totals = []
    for length_mm in (5000.0, 10000.0):
        register_upload(state, _drawing_with_pipe(length_mm), "plan.dxf", tmp_path)
        doc = app.open_dxf(state["source_path"])
        report = app.calculate_dxf_quantities(doc, "m", app.read_insunits(doc)["meters_per_unit"])
        totals.append(report["summary"]["total_pipe_length"])
    validation.equal(
        "UP-SESSION-09",
        "re-upload uses new geometry",
        expected=[5000.0 * MM_TO_M, 10000.0 * MM_TO_M],
        actual=totals,
        basis="LINE 5000 mm then LINE 10000 mm on П_Трубы, both named plan.dxf, INSUNITS=4",
        kind="UPLOAD",
    )
