"""
Report generator — multi-page aware, backward-compatible with PointCheck v1.

Single-page scan:  returns the same structure as the original PointCheck report.
Multi-page crawl:  same top-level keys PLUS a `pages` list with per-page reports.

The frontend reads `test_summaries`, `compliance_percentage`, `overall_status`,
`critical_failures`, `narrative`, and `raw_results` — all preserved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

WCAG_CRITERIA_LABELS: dict[str, str] = {
    "1.1.1": "Non-text Content",
    "1.2.1": "Audio-only and Video-only",
    "1.2.2": "Captions (Prerecorded)",
    "1.2.3": "Audio Description (Prerecorded)",
    "1.3.1": "Info and Relationships",
    "1.4.1": "Use of Color",
    "1.4.3": "Contrast (Minimum)",
    "1.4.4": "Resize Text",
    "1.4.10": "Reflow",
    "2.1.1": "Keyboard",
    "2.1.2": "No Keyboard Trap",
    "2.2.2": "Pause, Stop, Hide",
    "2.3.1": "Three Flashes",
    "2.4.1": "Bypass Blocks",
    "2.4.2": "Page Titled",
    "2.4.3": "Focus Order",
    "2.4.4": "Link Purpose",
    "2.4.7": "Focus Visible",
    "2.5.8": "Target Size (Minimum)",
    "3.1.1": "Language of Page",
    "3.3.1": "Error Identification",
    "3.3.2": "Labels or Instructions",
    "3.3.3": "Error Suggestion",
    "3.3.4": "Error Prevention",
    "4.1.1": "Parsing",
    "4.1.2": "Name, Role, Value",
}

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "warning": 3}

TEST_LABELS: dict[str, str] = {
    "keyboard_nav":    "Keyboard-Only Navigation",
    "zoom":            "Resize Text & Reflow",
    "color_blindness": "Color-Blindness & Contrast",
    "focus_indicator": "Focus Visibility",
    "form_errors":     "Form Error Handling",
    "page_structure":  "Page Structure & Semantics",
    "video_motion":    "Video, Audio & Motion",
}


def _overall_status(results: list[dict]) -> str:
    failed = [r for r in results if r.get("result") == "fail"]
    if not failed:
        return "compliant"
    if any(r.get("severity") == "critical" for r in failed):
        return "critical_issues"
    return "issues_found"


def _compliance_pct(results: list[dict]) -> float:
    total = len(results)
    if not total:
        return 0.0
    passed   = sum(1 for r in results if r.get("result") == "pass")
    warnings = sum(1 for r in results if r.get("result") == "warning")
    return round((passed + warnings) / total * 100, 1)


def _top_criteria(results: list[dict], n: int = 5) -> list[dict]:
    counts: dict[str, int] = {}
    for r in results:
        if r.get("result") == "fail":
            for crit in r.get("wcag_criteria", []):
                counts[crit] = counts.get(crit, 0) + 1
    return [
        {
            "criterion": crit,
            "label": WCAG_CRITERIA_LABELS.get(crit, crit),
            "failure_count": count,
        }
        for crit, count in sorted(counts.items(), key=lambda x: -x[1])[:n]
    ]


def build_page_report(
    page_url: str,
    depth: int,
    results: list[dict],
    tests_run: list[str],
    screenshot_path: str | None = None,
) -> dict[str, Any]:
    """
    Build a single-page sub-report. Mirrors the existing PointCheck report
    shape so the frontend's existing rendering code works unchanged.
    """
    passed   = [r for r in results if r.get("result") == "pass"]
    failed   = [r for r in results if r.get("result") == "fail"]
    warnings = [r for r in results if r.get("result") == "warning"]
    errors   = [r for r in results if r.get("result") == "error"]

    sorted_failures = sorted(
        failed, key=lambda r: SEVERITY_ORDER.get(r.get("severity", "minor"), 3)
    )

    test_summaries = []
    for test_id in tests_run:
        r = next((x for x in results if x.get("test_id") == test_id), None)
        test_summaries.append({
            "test_id":        test_id,
            "test_name":      TEST_LABELS.get(test_id, test_id),
            "result":         r.get("result", "not_run") if r else "not_run",
            "severity":       r.get("severity", "") if r else "",
            "failure_reason": r.get("failure_reason", "") if r else "",
            "wcag_criteria":  r.get("wcag_criteria", []) if r else [],
            "recommendation": r.get("recommendation", "") if r else "",
            "screenshot_path": r.get("screenshot_path") if r else None,
            "screenshot_b64":  r.get("screenshot_b64") if r else None,
            "details":         r.get("details") if r else None,
            "molmo_analysis":  r.get("molmo_analysis", "") if r else "",
        })

    return {
        "page_url":            page_url,
        "depth":               depth,
        "overall_status":      _overall_status(results),
        "compliance_percentage": _compliance_pct(results),
        "summary": {
            "total_tests": len(results),
            "passed":    len(passed),
            "failed":    len(failed),
            "warnings":  len(warnings),
            "errors":    len(errors),
        },
        "top_criteria_failures": _top_criteria(results),
        "test_summaries":   test_summaries,
        "critical_failures": [r for r in sorted_failures if r.get("severity") == "critical"],
        "all_failures":     sorted_failures,
        "raw_results":      results,
        "screenshot_path":  screenshot_path,
    }


def build_site_report(
    job_id: str,
    site_url: str,
    wcag_version: str,
    narrative: str,
    page_reports: list[dict[str, Any]],
    tests_run: list[str],
) -> dict[str, Any]:
    """
    Aggregate per-page reports into a site-wide report.

    Top-level structure is backward-compatible with PointCheck v1 so the
    existing frontend renders correctly for single-page scans. Multi-page
    data is additive in the `pages` key.
    """
    # Flatten all results across pages
    all_results: list[dict] = []
    for pr in page_reports:
        for r in pr.get("raw_results", []):
            r_copy = dict(r)
            r_copy["page_url"] = pr["page_url"]
            all_results.append(r_copy)

    # Aggregate test summaries: worst result per test_id across all pages
    agg_by_test: dict[str, list[dict]] = {}
    for pr in page_reports:
        for ts in pr.get("test_summaries", []):
            tid = ts["test_id"]
            agg_by_test.setdefault(tid, []).append(ts)

    agg_summaries = []
    for test_id in tests_run:
        entries = agg_by_test.get(test_id, [])
        if not entries:
            agg_summaries.append({
                "test_id": test_id,
                "test_name": TEST_LABELS.get(test_id, test_id),
                "result": "not_run", "severity": "",
                "failure_reason": "", "wcag_criteria": [],
                "recommendation": "", "screenshot_path": None,
                "screenshot_b64": None, "details": None,
                "pages_failed": 0, "pages_total": len(page_reports),
            })
            continue

        # Result priority: fail > warning > error > pass
        priority = {"fail": 0, "warning": 1, "error": 2, "pass": 3, "not_run": 4}
        worst = min(entries, key=lambda e: priority.get(e.get("result", "not_run"), 5))
        pages_failed = sum(1 for e in entries if e.get("result") == "fail")

        agg_summaries.append({
            **worst,
            "pages_failed": pages_failed,
            "pages_total":  len(page_reports),
        })

    passed   = [r for r in all_results if r.get("result") == "pass"]
    failed   = [r for r in all_results if r.get("result") == "fail"]
    warnings = [r for r in all_results if r.get("result") == "warning"]
    errors   = [r for r in all_results if r.get("result") == "error"]
    sorted_failures = sorted(
        failed, key=lambda r: SEVERITY_ORDER.get(r.get("severity", "minor"), 3)
    )

    return {
        # ── Backward-compatible single-page fields ─────────────────────────
        "job_id":              job_id,
        "url":                 site_url,
        "wcag_version":        wcag_version,
        "generated_at":        datetime.utcnow().isoformat(),
        "narrative":           narrative,
        "overall_status":      _overall_status(all_results),
        "compliance_percentage": _compliance_pct(all_results),
        "pages_scanned":       len(page_reports),
        "summary": {
            "total_tests": len(all_results),
            "passed":    len(passed),
            "failed":    len(failed),
            "warnings":  len(warnings),
            "errors":    len(errors),
        },
        "top_criteria_failures": _top_criteria(all_results),
        "test_summaries":   agg_summaries,
        "critical_failures": [r for r in sorted_failures if r.get("severity") == "critical"],
        "all_failures":     sorted_failures,
        "raw_results":      all_results,
        # ── Additive multi-page field ──────────────────────────────────────
        "pages": page_reports,
    }


def strip_b64(obj: Any) -> Any:
    """
    Recursively remove screenshot_b64 keys from a report dict before
    sending over WebSocket — screenshots can push frames past the 1MB limit.
    Individual `result` events during the scan still include b64.
    """
    if isinstance(obj, dict):
        return {k: strip_b64(v) for k, v in obj.items() if k != "screenshot_b64"}
    if isinstance(obj, list):
        return [strip_b64(i) for i in obj]
    return obj
