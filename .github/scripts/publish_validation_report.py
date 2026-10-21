"""Publish the pytest validation report as a GitHub check run.

Job logs, step summaries and artifacts need a signed-in user to read. A check run's
output is readable through the public checks API, so the full result table stays
inspectable. The check run is informational (conclusion "neutral"); the pytest step
decides whether the workflow passes.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

MAX_TEXT_CHARS = 65000


def main(report_markdown: str, label: str) -> int:
    markdown_path = Path(report_markdown)
    json_path = markdown_path.with_suffix(".json")
    if not markdown_path.is_file() or not json_path.is_file():
        print(f"::warning title=Validation report missing::{markdown_path} was not written")
        return 0

    rows = json.loads(json_path.read_text(encoding="utf-8"))
    statuses = Counter(row["status"] for row in rows)
    outcomes = Counter(row["pytest_outcome"] for row in rows)
    title = f"{label}: PASS {statuses['PASS']} / FAIL {statuses['FAIL']} / NOT RUN {statuses['NOT RUN']} of {len(rows)} checks"
    summary = f"{title}\n\npytest outcome per check: {dict(sorted(outcomes.items()))}"
    text = markdown_path.read_text(encoding="utf-8")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n(truncated; full report in the workflow artifact)"
    print(f"::notice title=Validation report::{title}")

    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    head_sha = os.environ.get("HEAD_SHA") or os.environ.get("GITHUB_SHA")
    if not (token and repository and head_sha):
        print("::warning title=Validation report::GITHUB_TOKEN, GITHUB_REPOSITORY or HEAD_SHA missing; check run not created")
        return 0

    body = {
        "name": f"validation-report ({label})",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "neutral",
        "output": {"title": title, "summary": summary, "text": text},
    }
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/check-runs",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            created = json.loads(response.read().decode("utf-8"))
        print(f"Validation report published: {created.get('html_url')}")
    except urllib.error.HTTPError as error:
        print(f"::warning title=Validation report::check run not created (HTTP {error.code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "validation"))
