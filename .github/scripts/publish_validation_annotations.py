"""Publish the pytest validation report as GitHub check-run annotations.

Job logs and step summaries need a signed-in user to read; annotations are
readable through the public checks API, so the full result table stays
inspectable for anyone with access to the repository.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

MAX_MESSAGE_CHARS = 30000
MAX_ANNOTATIONS = 9


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(report_path: str, label: str) -> int:
    path = Path(report_path)
    if not path.is_file():
        print(f"::warning title=Validation report missing::{_escape(str(path))} was not written")
        return 0

    rows = json.loads(path.read_text(encoding="utf-8"))
    statuses = Counter(row["status"] for row in rows)
    outcomes = Counter(row["pytest_outcome"] for row in rows)
    header = (
        f"{label}: checks={len(rows)} PASS={statuses['PASS']} FAIL={statuses['FAIL']} NOT RUN={statuses['NOT RUN']}; "
        f"pytest outcomes per check: {dict(sorted(outcomes.items()))}"
    )
    lines = [
        " | ".join(
            str(row[key])
            for key in ("case_id", "status", "kind", "rule", "basis", "expected", "actual", "abs_diff", "pct_diff", "pytest_outcome", "note")
        )
        for row in rows
    ]

    chunks: list[list[str]] = [[]]
    size = 0
    for line in lines:
        if chunks[-1] and size + len(line) + 1 > MAX_MESSAGE_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append(line)
        size += len(line) + 1

    if len(chunks) > MAX_ANNOTATIONS:
        print(f"::warning title=Validation report truncated::{len(chunks)} parts, only {MAX_ANNOTATIONS} published")
    for index, chunk in enumerate(chunks[:MAX_ANNOTATIONS], start=1):
        message = "\n".join([header, "id | status | kind | rule | basis | expected | actual | abs diff | % diff | pytest | note", *chunk])
        print(f"::notice title=Validation report part {index} of {len(chunks)}::{_escape(message)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "validation"))
