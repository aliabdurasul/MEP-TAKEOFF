"""Content-addressed storage for uploaded drawings.

Each upload is stored at ``<root>/<first 16 hex chars of sha256>/<safe file name>``.
Existing files are never overwritten or deleted: storing identical content again
reuses the existing file, and a name collision with different content raises
``UploadIntegrityError``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

HASH_DIR_LENGTH = 16
MAX_FILENAME_LENGTH = 120
DEFAULT_FILENAME = "upload"

_UNSAFE_CHARS_RE = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class EmptyUploadError(ValueError):
    """The uploaded file has no content."""


class UploadIntegrityError(RuntimeError):
    """A stored file exists at the target path but its content hash differs."""


@dataclass(frozen=True)
class StoredUpload:
    sha256: str
    original_name: str
    stored_name: str
    path: Path
    size: int
    created: bool


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(name: str | None, default: str = DEFAULT_FILENAME) -> str:
    """Return a single path component that is safe on Windows and POSIX."""

    raw = str(name or "")
    base = PureWindowsPath(PurePosixPath(raw).name).name
    base = unicodedata.normalize("NFC", base)
    base = _UNSAFE_CHARS_RE.sub("_", base)
    base = base.strip().strip(".").strip()
    if not base:
        return default

    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    suffix = f".{suffix}" if suffix else ""
    max_stem = max(MAX_FILENAME_LENGTH - len(suffix), 1)
    stem = stem[:max_stem].rstrip(" .") or default
    return f"{stem}{suffix}"


def store_upload(data: bytes, original_name: str | None, root: str | Path) -> StoredUpload:
    if not data:
        raise EmptyUploadError("Uploaded file is empty.")

    digest = sha256_bytes(data)
    stored_name = safe_filename(original_name)
    root_path = Path(root)
    target_dir = root_path / digest[:HASH_DIR_LENGTH]
    target = target_dir / stored_name

    resolved_root = root_path.resolve()
    if resolved_root not in target.resolve().parents:
        raise ValueError(f"Refusing to store upload outside {resolved_root}")

    if target.exists():
        return _existing_upload(target, digest, original_name, stored_name, len(data))

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(target, "xb")
    except FileExistsError:
        return _existing_upload(target, digest, original_name, stored_name, len(data))

    try:
        with handle:
            handle.write(data)
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    return StoredUpload(
        sha256=digest,
        original_name=str(original_name or ""),
        stored_name=stored_name,
        path=target,
        size=len(data),
        created=True,
    )


def _existing_upload(target: Path, digest: str, original_name: str | None, stored_name: str, size: int) -> StoredUpload:
    if sha256_file(target) != digest:
        raise UploadIntegrityError(f"Existing file {target} does not match sha256 {digest}; not overwriting.")
    return StoredUpload(
        sha256=digest,
        original_name=str(original_name or ""),
        stored_name=stored_name,
        path=target,
        size=size,
        created=False,
    )
