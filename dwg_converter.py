from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ODA_ENV_VAR = "ODA_FILE_CONVERTER_PATH"
DEFAULT_EXECUTABLE_NAMES = ("ODAFileConverter.exe", "ODAFileConverter")


def resolve_executable_path(configured_path: str | None) -> Path | None:
    """Resolve a local ODA File Converter executable path."""

    candidate = (configured_path or os.getenv(ODA_ENV_VAR) or "").strip().strip('"')
    if not candidate:
        return None

    path = Path(candidate)
    if path.is_file():
        return path

    if path.is_dir():
        for name in DEFAULT_EXECUTABLE_NAMES:
            exe = path / name
            if exe.is_file():
                return exe

    return None


def is_available(configured_path: str | None) -> bool:
    return resolve_executable_path(configured_path) is not None


def _find_converted_dxf(output_dir: Path, expected_stem: str) -> Path:
    matches = sorted(output_dir.rglob(f"{expected_stem}.dxf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if matches:
        return matches[0]

    all_dxf = sorted(output_dir.rglob("*.dxf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if all_dxf:
        return all_dxf[0]

    raise FileNotFoundError("ODA File Converter did not create a DXF file.")


def convert_dwg_to_dxf(
    dwg_path: str | Path,
    oda_executable_path: str | None,
    output_dir: str | Path,
    *,
    output_version: str = "ACAD2018",
) -> Path:
    """Convert a DWG file to DXF using a locally installed ODA File Converter."""

    executable = resolve_executable_path(oda_executable_path)
    if executable is None:
        raise FileNotFoundError("DWG converter not found. Please install ODA File Converter.")

    dwg_path = Path(dwg_path)
    if not dwg_path.is_file():
        raise FileNotFoundError(f"DWG file not found: {dwg_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="oda_input_") as input_tmp, tempfile.TemporaryDirectory(prefix="oda_output_") as output_tmp:
        input_dir = Path(input_tmp)
        temp_output_dir = Path(output_tmp)
        working_input = input_dir / dwg_path.name
        shutil.copy2(dwg_path, working_input)

        cmd = [
            str(executable),
            str(input_dir),
            str(temp_output_dir),
            output_version,
            "DXF",
            "0",
            "1",
            "*.dwg",
        ]

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "ODA File Converter failed."
            raise RuntimeError(f"DWG conversion failed. Error: {message}")

        converted = _find_converted_dxf(temp_output_dir, dwg_path.stem)
        final_output = output_dir / f"{dwg_path.stem}.dxf"
        shutil.copy2(converted, final_output)
        return final_output