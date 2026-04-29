#!/usr/bin/env python3
"""
PointCheck Regression Suite
============================
Runs a fixed set of test cases against the staging (or prod) backend and
asserts known expected outcomes. All cases run sequentially (GPU constraint).

Test cases
----------
  GDS Accessibility Audit   — ground-truth broken page; per-check recall + severity
  discord.com               — must NOT be blocked by robots.txt false positive
  medium.com                — must return page_error (bot block / robots.txt)
  GOV.UK Design System      — known-good page; false-positive rate check
  GDS consistency run       — second lightweight run; result stability check (--consistency)

Eval layers
-----------
  Regression assertions  — per-case pass/fail checked every run
  LLM-as-judge           — Claude grades OLMo-3 narrative accuracy/completeness/actionability
  Axe cross-tool check   — axe-core 4.9.1 run locally; PointCheck must not PASS where Axe finds violations
  Consistency eval        — opt-in via --consistency; doubles GDS scan to test variance

Usage
-----
  python regression_suite.py                       # staging (default)
  python regression_suite.py --prod                # production
  python regression_suite.py --consistency         # also run consistency eval (~+150s)
  python regression_suite.py --skip-judge          # skip LLM-as-judge (no API key)
  python regression_suite.py --skip-axe            # skip Axe cross-tool check
  python regression_suite.py --axe-python PATH     # path to python with playwright (default: backend/venv/bin/python3)

Exit codes
----------
  0  all assertions passed
  1  one or more assertions failed
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

import websockets

# ── Environment ───────────────────────────────────────────────────────────────

STAGING_URL = "https://brendanworks-staging--wcag-tester-web.modal.run"
PROD_URL    = "https://brendanworks--wcag-tester-web.modal.run"

# ── Test case definitions ─────────────────────────────────────────────────────

CASES = [
    {
        # W3C WAI BAD site returns 403 to Modal's datacenter IPs.
        # GDS Audit page (GitHub Pages) has no IP blocking and contains
        # every common accessibility failure by design — used as ground truth.
        "label":   "GDS Accessibility Audit page (ground-truth broken page)",
        "url":     "https://alphagov.github.io/accessibility-tool-audit/test-cases.html",
        "tests":   ["keyboard_nav", "color_blindness", "focus_indicator",
                    "form_errors", "page_structure"],
        "wcag":    "2.1",
        "assertions": [
            # ── Smoke assertions ────────────────────────────────────────────
            ("no_page_error",          "page_error event must NOT fire"),
            ("pages_scanned",          "pages_scanned must be >= 1"),
            ("has_narrative",          "OLMo-3 narrative must be present"),
            # ── Per-check recall (precision/recall eval) ───────────────────
            # These assert that specific known violations are actually caught.
            # A regression here means the check has lost recall on a known-bad page.
            ("check_page_structure_fails",
             "page_structure check must FAIL (GDS page has broken headings/landmarks)"),
            # form_errors correctly returns warning (partial detection) on this page;
            # accept fail OR warning — either means the check is firing on known issues.
            ("check_form_errors_detected",
             "form_errors check must FAIL or WARN (GDS page has missing error associations)"),
            # At least 2/5 checks must produce a hard failure — this catches a
            # regression where the model stops flagging clear violations as fails.
            ("check_recall_rate",
             "at least 2/5 checks must FAIL — minimum recall floor"),
            # ── Severity calibration ───────────────────────────────────────
            # GDS page violations top out at 'serious' in the current severity scale.
            # If this regresses the scale has drifted toward under-reporting.
            ("check_serious_severity",
             "at least one failure must be severity=serious or critical on known-broken page"),
        ],
    },
    {
        # discord.com has a publicly accessible robots.txt that does not
        # explicitly disallow our crawl path.  The old stdlib RobotFileParser
        # was falsely blocking it (disallow_all on a non-200 response).  This
        # case verifies that fix: the scan must NOT be blocked by a robots.txt
        # false positive.  A CAPTCHA block mid-scan is still fine (page_error
        # may or may not fire depending on their bot-detection), but the key
        # assertion is that pages_scanned >= 1 — we got past robots.txt.
        "label":   "discord.com (robots.txt false-positive regression)",
        "url":     "https://discord.com",
        "tests":   ["page_structure"],
        "wcag":    "2.1",
        "assertions": [
            ("pages_scanned",
             "pages_scanned must be >= 1 (no false-positive robots.txt block)"),
        ],
    },
    {
        "label":   "medium.com (bot-blocked / robots.txt)",
        "url":     "https://medium.com",
        "tests":   ["page_structure"],
        "wcag":    "2.1",
        "assertions": [
            ("page_error_fired", "page_error event must fire"),
            ("zero_pages",       "pages_scanned must be 0"),
        ],
    },
    {
        # GOV.UK Design System is one of the most rigorously accessibility-tested
        # sites on the web, maintained to WCAG 2.1 AA by the UK government.
        # This case checks the false-positive rate: the tool must NOT report
        # critical failures on a known-good page.  Minor/moderate warnings
        # are acceptable — no real-world page is perfect.
        "label":   "GOV.UK Design System (known-good page — false-positive check)",
        "url":     "https://design-system.service.gov.uk/components/button/",
        "tests":   ["keyboard_nav", "focus_indicator", "form_errors", "page_structure"],
        "wcag":    "2.1",
        "assertions": [
            ("no_page_error",         "page_error event must NOT fire"),
            ("pages_scanned",         "pages_scanned must be >= 1"),
            ("no_critical_failures",  "no critical-severity failures on known-good page"),
        ],
    },
]

# Consistency case — run separately under --consistency flag to avoid
# ballooning default suite runtime past ~12 min (GPU OOM risk).
CONSISTENCY_CASE = {
    "label":   "GDS consistency run (page_structure only — variance check)",
    "url":     "https://alphagov.github.io/accessibility-tool-audit/test-cases.html",
    "tests":   ["page_structure"],
    "wcag":    "2.1",
    "assertions": [
        ("no_page_error", "page_error event must NOT fire (consistency run)"),
        ("pages_scanned", "pages_scanned must be >= 1 (consistency run)"),
    ],
    # result compared against GDS case in main() after both complete
    "_consistency_ref_label": "GDS Accessibility Audit page (ground-truth broken page)",
    "_consistency_check_id":  "page_structure",
}

# ── HTTP helper ───────────────────────────────────────────────────────────────

def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

# ── Single-case runner ────────────────────────────────────────────────────────

async def run_case(base_url: str, case: dict) -> dict:
    """Run one test case, collect events, return result dict."""
    label  = case["label"]
    ws_base = base_url.replace("https://", "wss://")

    resp = post_json(
        f"{base_url}/api/run",
        {
            "url":          case["url"],
            "tests":        case["tests"],
            "task":         "Navigate and use the main features of this website",
            "wcag_version": case["wcag"],
        },
    )
    run_id = resp.get("run_id") or resp.get("job_id")
    if not run_id:
        return {"label": label, "error": f"No run_id in response: {resp}", "events": []}

    ws_url = f"{ws_base}/ws/{run_id}"
    events      = []
    page_errors = []
    report      = {}
    terminal_event = None
    t0 = time.time()

    try:
        async with websockets.connect(ws_url, open_timeout=30, ping_timeout=60) as ws:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=480)
                except asyncio.TimeoutError:
                    events.append({"type": "timeout"})
                    terminal_event = {"type": "timeout"}
                    break
                msg = json.loads(raw)
                events.append(msg)

                if msg.get("type") == "page_error":
                    page_errors.append(msg.get("error") or msg.get("message", ""))

                if msg.get("type") in ("done", "error"):
                    report = msg.get("report", {})
                    terminal_event = msg
                    break
    except Exception as exc:
        return {"label": label, "error": str(exc), "events": events}

    return {
        "label":          label,
        "elapsed":        round(time.time() - t0),
        "events":         events,
        "page_errors":    page_errors,
        "report":         report,
        "terminal_event": terminal_event,
    }

# ── Assertion evaluator ───────────────────────────────────────────────────────

def _test_summary(report: dict, test_id: str) -> dict | None:
    """Return the aggregated test_summary entry for a given test_id, or None."""
    return next(
        (ts for ts in report.get("test_summaries", []) if ts.get("test_id") == test_id),
        None,
    )


def evaluate(case: dict, result: dict) -> list[dict]:
    """Return list of {assertion, description, passed, detail}."""
    outcomes    = []
    report      = result.get("report", {})
    page_errors = result.get("page_errors", [])
    summary     = report.get("summary", {})
    pages_scanned = report.get("pages_scanned", 0)
    narrative   = report.get("narrative", "") or ""
    test_summaries = report.get("test_summaries", [])
    failed      = summary.get("failed", 0)
    passed      = summary.get("passed", 0)

    for assertion, description in case["assertions"]:
        detail = ""

        # ── Smoke ──────────────────────────────────────────────────────────
        if assertion == "no_page_error":
            ok = len(page_errors) == 0
            detail = f"got page_error: {page_errors[0][:80]}" if page_errors else ""

        elif assertion == "page_error_fired":
            ok = len(page_errors) > 0
            detail = page_errors[0][:80] if page_errors else "no page_error received"

        elif assertion == "pages_scanned":
            ok = pages_scanned >= 1
            detail = f"pages_scanned={pages_scanned}"

        elif assertion == "zero_pages":
            ok = pages_scanned == 0
            detail = f"pages_scanned={pages_scanned}"

        elif assertion == "has_failures":
            ok = failed >= 1
            detail = f"passed={passed} failed={failed}"

        elif assertion == "has_narrative":
            ok = len(narrative) > 50
            detail = f"narrative length={len(narrative)}"

        # ── Per-check recall (precision/recall eval) ───────────────────────
        elif assertion.startswith("check_") and assertion.endswith("_fails"):
            # e.g. "check_page_structure_fails" → test_id = "page_structure"
            test_id = assertion[len("check_"):-len("_fails")]
            ts = _test_summary(report, test_id)
            if ts is None:
                ok = False
                detail = f"{test_id}: not present in test_summaries"
            else:
                ok = ts.get("result") == "fail"
                detail = f"{test_id}: result={ts.get('result')} severity={ts.get('severity')}"

        elif assertion.startswith("check_") and assertion.endswith("_detected"):
            # Accept fail OR warning — check is firing on a known issue.
            test_id = assertion[len("check_"):-len("_detected")]
            ts = _test_summary(report, test_id)
            if ts is None:
                ok = False
                detail = f"{test_id}: not present in test_summaries"
            else:
                ok = ts.get("result") in ("fail", "warning")
                detail = f"{test_id}: result={ts.get('result')} severity={ts.get('severity')}"

        elif assertion == "check_recall_rate":
            fails = sum(1 for ts in test_summaries if ts.get("result") == "fail")
            total = len(test_summaries)
            ok = fails >= 2
            detail = f"{fails}/{total} checks failed (need ≥2)"

        # ── Severity calibration ───────────────────────────────────────────
        elif assertion == "check_serious_severity":
            # Accept serious OR critical — critical is the ceiling, but GDS page
            # violations currently top out at serious in the current severity scale.
            serious_ts = [
                ts for ts in test_summaries
                if ts.get("result") == "fail"
                and ts.get("severity") in ("serious", "critical")
            ]
            serious_raw = [
                r for r in report.get("all_failures", [])
                if r.get("severity") in ("serious", "critical")
            ]
            ok = len(serious_ts) > 0 or len(serious_raw) > 0
            detail = (
                f"serious/critical in test_summaries: {len(serious_ts)}, "
                f"in all_failures: {len(serious_raw)}"
            )

        elif assertion == "check_critical_severity":
            critical_ts = [
                ts for ts in test_summaries
                if ts.get("result") == "fail" and ts.get("severity") == "critical"
            ]
            critical_raw = [
                r for r in report.get("all_failures", [])
                if r.get("severity") == "critical"
            ]
            ok = len(critical_ts) > 0 or len(critical_raw) > 0
            detail = (
                f"critical in test_summaries: {len(critical_ts)}, "
                f"critical in all_failures: {len(critical_raw)}"
            )

        elif assertion == "no_critical_failures":
            critical_ts = [
                ts for ts in test_summaries
                if ts.get("result") == "fail" and ts.get("severity") == "critical"
            ]
            critical_raw = [
                r for r in report.get("all_failures", [])
                if r.get("severity") == "critical"
            ]
            ok = len(critical_ts) == 0 and len(critical_raw) == 0
            if not ok:
                reasons = [
                    r.get("failure_reason", r.get("test_id", "?"))[:60]
                    for r in (critical_ts + critical_raw)[:3]
                ]
                detail = f"critical failures: {reasons}"

        else:
            ok = False
            detail = f"unknown assertion: {assertion}"

        outcomes.append({
            "assertion":   assertion,
            "description": description,
            "passed":      ok,
            "detail":      detail,
        })

    return outcomes

# ── LLM-as-judge ─────────────────────────────────────────────────────────────

def judge_narrative(narrative: str, violations: list[str]) -> dict:
    """
    Use Claude to grade the OLMo-3 narrative on three dimensions (1-5 each):
      accuracy      — does it correctly describe the violations found?
      completeness  — does it cover the most significant issues?
      actionability — does it give clear remediation guidance?

    Returns {"accuracy": N, "completeness": N, "actionability": N, "summary": str}
    or {"error": str} if the call fails.
    """
    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic SDK not installed — pip install anthropic"}

    violations_text = "\n".join(f"- {v}" for v in violations[:20]) or "(none reported)"

    prompt = (
        "You are a WCAG accessibility expert evaluating an AI-generated audit narrative.\n\n"
        f"Detected violations (from automated checks):\n{violations_text}\n\n"
        f"Narrative to evaluate:\n{narrative}\n\n"
        "Rate this narrative on three dimensions, each 1–5:\n"
        "  accuracy      — correctly describes actual violations; no hallucinations (1=wrong, 5=accurate)\n"
        "  completeness  — covers the most critical issues present (1=misses key issues, 5=thorough)\n"
        "  actionability — gives specific, useful remediation guidance (1=vague, 5=actionable)\n\n"
        'Respond ONLY with valid JSON: {"accuracy": N, "completeness": N, "actionability": N, '
        '"summary": "one sentence critique"}'
    )

    try:
        # Let the SDK find the key via its own lookup chain (env var, config file, etc.)
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        scores = json.loads(raw)
        return scores
    except Exception as exc:
        return {"error": str(exc)}


def _extract_violations(report: dict) -> list[str]:
    """Pull a concise violation list from the report for the LLM judge."""
    violations = []
    for ts in report.get("test_summaries", []):
        if ts.get("result") == "fail":
            reason = ts.get("failure_reason", "")
            name   = ts.get("test_name", ts.get("test_id", ""))
            violations.append(f"{name}: {reason[:80]}" if reason else name)
    return violations

# ── Axe cross-tool baseline ───────────────────────────────────────────────────

def run_axe_baseline(url: str, axe_python: str) -> dict:
    """
    Run axe_runner.py as a subprocess using the specified Python binary
    (which must have playwright installed).  Returns the parsed JSON result,
    or {"error": str} on failure.
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "axe_runner.py")
    if not os.path.exists(script):
        return {"error": f"axe_runner.py not found at {script}"}

    try:
        proc = subprocess.run(
            [axe_python, script, url, "--json"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 and not proc.stdout.strip():
            return {"error": proc.stderr.strip()[:200] or "axe_runner exited non-zero"}
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "axe_runner timed out after 60s"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Consistency check ─────────────────────────────────────────────────────────

def check_consistency(
    ref_result: dict,
    consistency_result: dict,
    check_id: str,
) -> dict:
    """
    Compare the result of `check_id` between two independent runs of the same URL.
    Returns {"passed": bool, "detail": str}.
    """
    ref_ts   = _test_summary(ref_result.get("report", {}), check_id)
    cons_ts  = _test_summary(consistency_result.get("report", {}), check_id)

    if ref_ts is None or cons_ts is None:
        return {
            "passed": False,
            "detail": (
                f"check_id={check_id} missing from one result "
                f"(ref={ref_ts is not None}, cons={cons_ts is not None})"
            ),
        }

    ref_result_val  = ref_ts.get("result")
    cons_result_val = cons_ts.get("result")
    match = ref_result_val == cons_result_val

    return {
        "passed": match,
        "detail": f"run1={ref_result_val} run2={cons_result_val}",
    }

# ── Print helpers ─────────────────────────────────────────────────────────────

def print_case_result(case: dict, result, all_passed_ref: list[bool]) -> None:
    label = case["label"]
    print(f"\n── {label}")

    if isinstance(result, Exception):
        print(f"   ✗ EXCEPTION: {result}")
        all_passed_ref[0] = False
        return

    if result.get("error"):
        print(f"   ✗ ERROR: {result['error']}")
        all_passed_ref[0] = False
        return

    print(f"   elapsed: {result.get('elapsed', '?')}s")

    te      = result.get("terminal_event") or {}
    te_type = te.get("type", "none")
    if te_type == "error":
        print(f"   ⚠️  TERMINAL EVENT: error — {te.get('message','')[:100]}")
    elif te_type == "timeout":
        print(f"   ⚠️  TERMINAL EVENT: timeout (>480s between messages)")
    elif te_type == "done":
        print(f"   ✓  TERMINAL EVENT: done")
    else:
        print(f"   ?  TERMINAL EVENT: {te_type}")

    type_counts: dict[str, int] = {}
    for ev in result.get("events", []):
        t = ev.get("type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"   events: {dict(sorted(type_counts.items()))}")

    outcomes = evaluate(case, result)
    for o in outcomes:
        icon = "✓" if o["passed"] else "✗"
        line = f"   {icon} {o['description']}"
        if o["detail"]:
            line += f"  [{o['detail']}]"
        print(line)
        if not o["passed"]:
            all_passed_ref[0] = False

# ── Main ──────────────────────────────────────────────────────────────────────

async def main(
    base_url: str,
    run_consistency: bool,
    skip_judge: bool,
    skip_axe: bool,
    axe_python: str,
) -> int:
    cases = list(CASES)
    if run_consistency:
        cases.append(CONSISTENCY_CASE)

    print(f"\n{'═'*64}")
    print(f"  PointCheck Regression Suite")
    print(f"  Backend     : {base_url}")
    print(f"  Cases       : {len(cases)}")
    print(f"  LLM judge   : {'disabled (--skip-judge)' if skip_judge else 'enabled'}")
    print(f"  Axe cross-tool : {'disabled (--skip-axe)' if skip_axe else 'enabled'}")
    print(f"  Consistency : {'enabled (--consistency)' if run_consistency else 'disabled'}")
    print(f"{'═'*64}\n")

    # ── Axe baseline (runs locally, fast; kick off before GPU cases) ───────────
    axe_gds: dict = {}
    if not skip_axe:
        gds_url = CASES[0]["url"]
        print(f"── Axe cross-tool baseline (axe-core 4.9.1 local, GDS page)")
        axe_gds = run_axe_baseline(gds_url, axe_python)
        if axe_gds.get("error"):
            print(f"   ⚠️  axe baseline error: {axe_gds['error']} (non-blocking)")
        else:
            mapped = sum(len(v) for v in axe_gds.get("by_pointcheck", {}).values())
            print(
                f"   axe found {axe_gds['total_violations']} violations, "
                f"{mapped} mapped to PointCheck checks: "
                f"{list(axe_gds.get('by_pointcheck', {}).keys())}"
            )
        print()

    # Run cases SEQUENTIALLY — each scan needs the full A100 (40 GB VRAM) to
    # itself.  Running concurrently causes 3 × 16 GB model loads → OOM on the
    # 40 GB GPU, producing silent "error" events instead of real scan results.
    results = []
    for case in cases:
        try:
            result = await run_case(base_url, case)
        except Exception as exc:
            result = exc
        results.append(result)

    all_passed = [True]  # list so print_case_result can mutate it

    for case, result in zip(cases, results):
        print_case_result(case, result, all_passed)

    # ── LLM-as-judge (GDS narrative) ──────────────────────────────────────
    print(f"\n── LLM-as-judge: OLMo-3 narrative quality (Claude grades GDS run)")
    if skip_judge:
        print("   skipped (--skip-judge)")
    else:
        gds_result = next(
            (r for r in results if isinstance(r, dict) and "GDS Accessibility Audit" in r.get("label", "")),
            None,
        )
        if gds_result and not gds_result.get("error"):
            narrative  = gds_result.get("report", {}).get("narrative", "")
            violations = _extract_violations(gds_result.get("report", {}))
            if len(narrative) > 50:
                scores = judge_narrative(narrative, violations)
                if "error" in scores:
                    # Judge errors are non-blocking — API key may not be configured
                    # in all environments.  Scores are advisory, not a gate.
                    print(f"   ⚠️  judge unavailable: {scores['error']} (non-blocking)")
                else:
                    avg = round(
                        (scores.get("accuracy", 0) + scores.get("completeness", 0)
                         + scores.get("actionability", 0)) / 3, 1
                    )
                    # Advisory threshold: avg < 2.0 is a blocking failure (narrative
                    # is actively misleading); 2.0–3.0 is a warning; ≥3.0 is a pass.
                    if avg >= 3.0:
                        icon = "✓"
                    elif avg >= 2.0:
                        icon = "⚠️ "
                    else:
                        icon = "✗"
                        all_passed[0] = False
                    print(
                        f"   {icon} accuracy={scores.get('accuracy')}/5  "
                        f"completeness={scores.get('completeness')}/5  "
                        f"actionability={scores.get('actionability')}/5  "
                        f"avg={avg}/5"
                    )
                    if scores.get("summary"):
                        print(f"      \"{scores['summary']}\"")
            else:
                print(f"   ⚠️  narrative too short to judge (len={len(narrative)})")
        else:
            print("   skipped — GDS case failed or did not run")

    # ── Axe cross-tool comparison ──────────────────────────────────────────
    print(f"\n── Axe cross-tool: PointCheck recall vs axe-core baseline (GDS page)")
    if skip_axe:
        print("   skipped (--skip-axe)")
    elif axe_gds.get("error"):
        print(f"   skipped — axe baseline failed: {axe_gds['error']}")
    else:
        gds_result = next(
            (r for r in results
             if isinstance(r, dict) and "GDS Accessibility Audit" in r.get("label", "")),
            None,
        )
        if not gds_result or gds_result.get("error"):
            print("   skipped — GDS PointCheck case failed or did not run")
        else:
            by_pc = axe_gds.get("by_pointcheck", {})
            if not by_pc:
                print("   ⚠️  axe found no violations that map to PointCheck checks")
            else:
                for check_id, axe_rules in sorted(by_pc.items()):
                    ts = _test_summary(gds_result["report"], check_id)
                    pc_result = ts.get("result") if ts else "not_run"
                    if pc_result == "pass":
                        # PointCheck passed a check where Axe found violations —
                        # this is a false negative worth flagging.
                        icon = "✗"
                        all_passed[0] = False
                        print(
                            f"   {icon} {check_id}: PointCheck={pc_result} but "
                            f"axe found {len(axe_rules)} violation(s): {axe_rules}"
                        )
                    else:
                        icon = "✓"
                        print(
                            f"   {icon} {check_id}: PointCheck={pc_result} "
                            f"(axe rules: {axe_rules})"
                        )

    # ── Consistency eval ───────────────────────────────────────────────────
    if run_consistency:
        print(f"\n── Consistency eval: page_structure result stability")
        ref_case  = CASES[0]
        cons_case = CONSISTENCY_CASE
        ref_label  = ref_case["label"]
        cons_label = cons_case["label"]

        ref_result  = next(
            (r for r in results if isinstance(r, dict) and r.get("label") == ref_label),
            None,
        )
        cons_result = next(
            (r for r in results if isinstance(r, dict) and r.get("label") == cons_label),
            None,
        )

        if ref_result and cons_result and not ref_result.get("error") and not cons_result.get("error"):
            check_id = CONSISTENCY_CASE["_consistency_check_id"]
            outcome  = check_consistency(ref_result, cons_result, check_id)
            icon     = "✓" if outcome["passed"] else "✗"
            print(
                f"   {icon} page_structure result is stable across two independent runs"
                f"  [{outcome['detail']}]"
            )
            if not outcome["passed"]:
                all_passed[0] = False
        else:
            print("   skipped — one or both runs failed")

    print(f"\n{'═'*64}")
    if all_passed[0]:
        print("  ✓  ALL ASSERTIONS PASSED")
    else:
        print("  ✗  ONE OR MORE ASSERTIONS FAILED")
    print(f"{'═'*64}\n")

    return 0 if all_passed[0] else 1


if __name__ == "__main__":
    _default_axe_python = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "backend", "venv", "bin", "python3",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod",        action="store_true", help="Run against production")
    parser.add_argument("--consistency", action="store_true",
                        help="Also run consistency eval (~+150s, doubles GDS scan)")
    parser.add_argument("--skip-judge",  action="store_true",
                        help="Skip LLM-as-judge (use when ANTHROPIC_API_KEY is unavailable)")
    parser.add_argument("--skip-axe",    action="store_true",
                        help="Skip Axe cross-tool check")
    parser.add_argument("--axe-python",  default=_default_axe_python,
                        help="Path to Python binary with playwright installed "
                             f"(default: {_default_axe_python})")
    args = parser.parse_args()
    base = PROD_URL if args.prod else STAGING_URL
    sys.exit(asyncio.run(main(
        base, args.consistency, args.skip_judge, args.skip_axe, args.axe_python,
    )))
