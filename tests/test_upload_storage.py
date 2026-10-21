"""Upload storage: content addressing, safe names, no overwrite, no deletion."""

from __future__ import annotations

import hashlib

import pytest

from mep_takeoff.uploads import (
    HASH_DIR_LENGTH,
    MAX_FILENAME_LENGTH,
    EmptyUploadError,
    UploadIntegrityError,
    safe_filename,
    store_upload,
)


def _files(root):
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


@pytest.mark.parametrize(
    ("case_id", "raw_name", "expected"),
    [
        ("UP-NAME-01", "plan.dxf", "plan.dxf"),
        ("UP-NAME-02", "../../etc/passwd", "passwd"),
        ("UP-NAME-03", "..\\..\\evil.dxf", "evil.dxf"),
        ("UP-NAME-04", "C:\\Users\\x\\plan.dxf", "plan.dxf"),
        ("UP-NAME-05", "", "upload"),
        ("UP-NAME-06", "..", "upload"),
        ("UP-NAME-07", "a<b>|c?.dxf", "a_b__c_.dxf"),
        ("UP-NAME-08", "CON.dxf", "_CON.dxf"),
        ("UP-NAME-09", "МИР_ОТ_АНТП.dxf", "МИР_ОТ_АНТП.dxf"),
        ("UP-NAME-10", "name\x00.dxf", "name_.dxf"),
        ("UP-NAME-11", "  .hidden.dxf ", "hidden.dxf"),
    ],
)
def test_safe_filename(validation, case_id, raw_name, expected):
    """Uploaded names are reduced to one safe path component."""
    validation.equal(
        case_id,
        "safe file name / path traversal",
        expected=expected,
        actual=safe_filename(raw_name),
        basis=f"input {raw_name!r}",
        kind="UPLOAD",
    )


def test_safe_filename_length_limit(validation):
    """Long names are truncated but keep their extension."""
    result = safe_filename("a" * 300 + ".dxf")
    validation.equal(
        "UP-NAME-12",
        "file name length <= 120 and extension kept",
        expected=(MAX_FILENAME_LENGTH, ".dxf"),
        actual=(len(result), result[-4:]),
        basis="300-character stem + .dxf",
        kind="UPLOAD",
    )


def test_store_creates_content_addressed_file(tmp_path, validation):
    """A new upload is written under <root>/<sha256[:16]>/<name> with identical bytes."""
    data = b"0\nSECTION\n"
    digest = hashlib.sha256(data).hexdigest()
    stored = store_upload(data, "plan.dxf", tmp_path)
    validation.equal(
        "UP-STORE-01",
        "content-addressed path and identical bytes",
        expected=(tmp_path / digest[:HASH_DIR_LENGTH] / "plan.dxf", data, digest, True),
        actual=(stored.path, stored.path.read_bytes(), stored.sha256, stored.created),
        basis="10-byte payload",
        kind="UPLOAD",
    )


def test_store_same_content_reuses_file(tmp_path, validation):
    """Storing identical content twice creates no second file."""
    first = store_upload(b"same", "plan.dxf", tmp_path)
    second = store_upload(b"same", "plan.dxf", tmp_path)
    validation.equal(
        "UP-STORE-02",
        "same content -> same file, not rewritten",
        expected=(first.path, False, [f"{first.sha256[:HASH_DIR_LENGTH]}/plan.dxf"]),
        actual=(second.path, second.created, _files(tmp_path)),
        basis="two identical uploads named plan.dxf",
        kind="UPLOAD",
    )


def test_store_same_name_different_content_keeps_both(tmp_path, validation):
    """Same file name with different content never overwrites the earlier upload."""
    first = store_upload(b"revision A", "plan.dxf", tmp_path)
    second = store_upload(b"revision B", "plan.dxf", tmp_path)
    validation.equal(
        "UP-STORE-03",
        "same name, different content -> separate files",
        expected=(True, b"revision A", b"revision B", 2),
        actual=(first.path != second.path, first.path.read_bytes(), second.path.read_bytes(), len(_files(tmp_path))),
        basis="two uploads named plan.dxf with different bytes",
        kind="UPLOAD",
    )


def test_store_path_traversal_stays_inside_root(tmp_path, validation):
    """A traversal name is stored inside the storage root and nothing is written outside it."""
    root = tmp_path / "input"
    stored = store_upload(b"payload", "../../escape.dxf", root)
    outside = [path.name for path in tmp_path.rglob("escape.dxf") if root not in path.parents]
    validation.equal(
        "UP-STORE-04",
        "path traversal blocked",
        expected=(True, "escape.dxf", []),
        actual=(root.resolve() in stored.path.resolve().parents, stored.path.name, outside),
        basis="name '../../escape.dxf'",
        kind="UPLOAD",
    )


def test_store_rejects_empty_upload(tmp_path, validation):
    """An empty upload raises EmptyUploadError and creates nothing."""
    with pytest.raises(EmptyUploadError) as error:
        store_upload(b"", "empty.dxf", tmp_path)
    validation.equal(
        "UP-STORE-05",
        "empty file rejected, nothing written",
        expected=("EmptyUploadError", []),
        actual=(type(error.value).__name__, _files(tmp_path)),
        basis="0-byte upload",
        kind="UPLOAD",
    )


def test_store_preserves_existing_legacy_file(tmp_path, validation):
    """A file at the legacy location <root>/<name> is left byte-identical."""
    legacy = tmp_path / "plan.dxf"
    legacy.write_bytes(b"legacy content")
    before = (legacy.read_bytes(), legacy.stat().st_mtime_ns)
    store_upload(b"new content", "plan.dxf", tmp_path)
    validation.equal(
        "UP-STORE-06",
        "existing files are not modified",
        expected=before,
        actual=(legacy.read_bytes(), legacy.stat().st_mtime_ns),
        basis="pre-existing data/input/plan.dxf",
        kind="UPLOAD",
    )


def test_store_refuses_to_overwrite_mismatching_file(tmp_path, validation):
    """If the target path holds different bytes, storing fails and the file is untouched."""
    data = b"expected content"
    target = tmp_path / hashlib.sha256(data).hexdigest()[:HASH_DIR_LENGTH] / "plan.dxf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"tampered")
    with pytest.raises(UploadIntegrityError):
        store_upload(data, "plan.dxf", tmp_path)
    validation.equal(
        "UP-STORE-07",
        "hash mismatch -> error, no overwrite",
        expected=b"tampered",
        actual=target.read_bytes(),
        basis="pre-existing file with different bytes at target path",
        kind="UPLOAD",
    )
