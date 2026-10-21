"""Shared pytest configuration.

* Tests that need the private project drawing are skipped (reported as NOT RUN)
  when the file is absent. Their assertions are not modified.
* The ``validation`` fixture records expected vs. actual values for every check.
  A table of all checks (PASS / FAIL / NOT RUN) is printed at the end of the run
  and, when ``MEP_VALIDATION_REPORT`` is set, written as Markdown and JSON.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from numbers import Real
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DXF = ROOT / "data" / "input" / "MIR_OT_ANTP_R22_K2_8.dxf"
PRIVATE_TEST_MODULES = {"test_real_dxf_hardening.py"}
PRIVATE_SKIP_REASON = (
    "NOT RUN: private drawing data/input/MIR_OT_ANTP_R22_K2_8.dxf is not available in this environment; "
    "real-drawing assertions are unchanged and must be run in an authorised local environment"
)

KINDS = {
    "MATH": "independent mathematical reference",
    "BEHAVIOR": "current V0 behaviour (not a correctness claim)",
    "KNOWN-ISSUE": "math/engineering expectation the program currently violates (strict xfail)",
    "UPLOAD": "upload storage and cache reliability",
    "WARNING": "user-visible warnings and unit labels (no quantity change)",
    "EQUIVALENCE": "quantities identical to the calculation on main",
    "IMPACT": "read-only known-issue impact analysis (no quantity change)",
    "CONTRACT": "V1 behaviour contract rule (docs/V1_BEHAVIOR_CONTRACT.md)",
    "WORKFLOW": "end-to-end Streamlit workflow (upload -> takeoff -> UI -> Excel)",
}


@dataclass
class Check:
    case_id: str
    rule: str
    kind: str
    basis: str
    expected: Any
    actual: Any
    abs_diff: float | None
    pct_diff: float | None
    matched: bool


@dataclass
class ResultRow:
    case_id: str
    rule: str
    kind: str
    basis: str
    expected: str
    actual: str
    abs_diff: str
    pct_diff: str
    status: str
    pytest_outcome: str
    nodeid: str
    note: str


_CHECKS: dict[str, list[Check]] = {}
_OUTCOMES: dict[str, dict[str, str]] = {}
_ITEMS: dict[str, pytest.Item] = {}


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


class Validation:
    def __init__(self, nodeid: str):
        self._checks = _CHECKS.setdefault(nodeid, [])

    def close(
        self,
        case_id: str,
        rule: str,
        *,
        expected: float | None,
        actual: Any,
        basis: str,
        kind: str = "MATH",
        rel_tol: float = 1e-9,
        abs_tol: float = 1e-9,
    ) -> None:
        if _is_number(expected) and _is_number(actual):
            abs_diff = abs(float(actual) - float(expected))
            pct_diff = abs_diff / abs(float(expected)) * 100.0 if expected else None
            matched = math.isclose(float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol)
        else:
            abs_diff = None
            pct_diff = None
            matched = expected == actual
        self._record(case_id, rule, kind, basis, expected, actual, abs_diff, pct_diff, matched)
        assert matched, f"{case_id}: expected {expected!r}, actual {actual!r} ({basis})"

    def equal(self, case_id: str, rule: str, *, expected: Any, actual: Any, basis: str, kind: str = "BEHAVIOR") -> None:
        abs_diff = pct_diff = None
        if _is_number(expected) and _is_number(actual):
            abs_diff = abs(float(actual) - float(expected))
            pct_diff = abs_diff / abs(float(expected)) * 100.0 if expected else None
        matched = expected == actual
        self._record(case_id, rule, kind, basis, expected, actual, abs_diff, pct_diff, matched)
        assert matched, f"{case_id}: expected {expected!r}, actual {actual!r} ({basis})"

    def _record(self, case_id, rule, kind, basis, expected, actual, abs_diff, pct_diff, matched) -> None:
        if kind not in KINDS:
            raise ValueError(f"Unknown check kind {kind!r}")
        self._checks.append(Check(case_id, rule, kind, basis, expected, actual, abs_diff, pct_diff, matched))


@pytest.fixture
def validation(request) -> Validation:
    return Validation(request.node.nodeid)


def pytest_collection_modifyitems(config, items):
    private_available = PRIVATE_DXF.is_file()
    for item in items:
        _ITEMS[item.nodeid] = item
        if item.path.name in PRIVATE_TEST_MODULES:
            item.add_marker(pytest.mark.private_data)
        if item.get_closest_marker("private_data") and not private_available:
            item.add_marker(pytest.mark.skip(reason=PRIVATE_SKIP_REASON))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    entry = _OUTCOMES.setdefault(item.nodeid, {"outcome": "", "note": ""})
    if report.when == "setup" and report.skipped:
        entry["outcome"] = "skipped"
        entry["note"] = _skip_reason(report)
    elif report.when == "call":
        if hasattr(report, "wasxfail"):
            entry["outcome"] = "xfailed" if report.skipped else "xpassed"
            entry["note"] = str(report.wasxfail)
        elif report.skipped:
            entry["outcome"] = "skipped"
            entry["note"] = _skip_reason(report)
        else:
            entry["outcome"] = report.outcome
            if report.failed:
                entry["note"] = _failure_message(report)
    elif report.failed:
        entry["outcome"] = f"error ({report.when})"
        entry["note"] = _failure_message(report)
    return report


def _failure_message(report) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None and getattr(crash, "message", None):
        return _first_line(crash.message)
    return _first_line(report.longreprtext)


def _skip_reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).removeprefix("Skipped: ")
    return _first_line(str(longrepr))


def _first_line(text: str) -> str:
    for line in str(text).splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def _format(value: Any) -> str:
    if value is None:
        return "None"
    if _is_number(value):
        return f"{float(value):.12g}"
    return repr(value)


def _rows() -> list[ResultRow]:
    rows: list[ResultRow] = []
    for nodeid, entry in _OUTCOMES.items():
        outcome = entry["outcome"] or "not executed"
        item = _ITEMS.get(nodeid)
        rule_doc = _first_line(item.obj.__doc__ or "") if item is not None and getattr(item, "obj", None) else ""
        checks = _CHECKS.get(nodeid, [])
        not_run = outcome == "skipped"
        if not checks:
            if not_run:
                status = "NOT RUN"
            elif outcome == "passed":
                status = "PASS"
            else:
                status = "FAIL"
            rows.append(ResultRow(nodeid.split("::")[-1], rule_doc, "-", "-", "-", "-", "-", "-", status, outcome, nodeid, entry["note"]))
            continue
        test_broken = outcome == "failed" or outcome.startswith("error")
        for index, check in enumerate(checks):
            status = "NOT RUN" if not_run else ("PASS" if check.matched else "FAIL")
            if test_broken and index == len(checks) - 1:
                status = "FAIL"
            rows.append(
                ResultRow(
                    case_id=check.case_id,
                    rule=check.rule,
                    kind=check.kind,
                    basis=check.basis,
                    expected=_format(check.expected),
                    actual=_format(check.actual),
                    abs_diff="-" if check.abs_diff is None else f"{check.abs_diff:.6g}",
                    pct_diff="-" if check.pct_diff is None else f"{check.pct_diff:.6g}%",
                    status=status,
                    pytest_outcome=outcome,
                    nodeid=nodeid,
                    note=entry["note"],
                )
            )
    return rows


def _markdown(rows: list[ResultRow]) -> str:
    def cell(text: str) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")

    counts = {status: sum(1 for row in rows if row.status == status) for status in ("PASS", "FAIL", "NOT RUN")}
    lines = [
        "## MEP takeoff validation report",
        "",
        f"Checks: {len(rows)} | PASS: {counts['PASS']} | FAIL: {counts['FAIL']} | NOT RUN: {counts['NOT RUN']}",
        "",
        "Kinds: " + "; ".join(f"`{kind}` = {text}" for kind, text in KINDS.items()),
        "",
        "| ID | Rule | Kind | Geometry / units | Expected | Actual | Abs diff | % diff | Status | pytest | Note |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    row.case_id, row.rule, row.kind, row.basis, row.expected, row.actual,
                    row.abs_diff, row.pct_diff, row.status, row.pytest_outcome, row.note,
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    rows = _rows()
    if not rows:
        return
    markdown = _markdown(rows)
    terminalreporter.section("MEP validation report")
    terminalreporter.write(markdown)

    report_path = os.environ.get("MEP_VALIDATION_REPORT")
    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        path.with_suffix(".json").write_text(
            json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown)
