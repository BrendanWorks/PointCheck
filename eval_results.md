# PointCheck Eval Results

**Backend:** `https://brendanworks-staging--wcag-tester-web.modal.run`
**Date:** 2026-04-25
**LLM judge:** enabled (claude-haiku-4-5)
**Consistency eval:** available via `--consistency` flag

---

## Regression Assertions

### GDS Accessibility Audit page — ground-truth broken page
> Deliberately broken page containing every common WCAG violation. Used as the recall ground truth.

| | Assertion | Detail |
|---|---|---|
| ✓ | page_error event must NOT fire | |
| ✓ | pages_scanned must be >= 1 | pages_scanned=1 |
| ✓ | OLMo-3 narrative must be present | narrative length=898 |
| ✓ | page_structure check must FAIL | result=fail severity=serious |
| ✓ | form_errors check must FAIL or WARN | result=warning severity=minor |
| ✓ | at least 2/5 checks must FAIL — minimum recall floor | 2/5 checks failed |
| ✓ | at least one failure must be severity=serious or critical | serious/critical in test_summaries: 2 |

**Elapsed:** 98s

---

### discord.com — robots.txt false-positive regression
> Verifies a prior fix: the scanner must not be falsely blocked at the robots.txt stage.

| | Assertion | Detail |
|---|---|---|
| ✓ | pages_scanned must be >= 1 (no false-positive robots.txt block) | pages_scanned=1 |

**Elapsed:** 128s

---

### medium.com — bot-blocked site
> Must be correctly identified as inaccessible to the scanner.

| | Assertion | Detail |
|---|---|---|
| ✓ | page_error event must fire | CAPTCHA detected |
| ✓ | pages_scanned must be 0 | pages_scanned=0 |

**Elapsed:** 44s

---

### GOV.UK Design System — known-good page (false-positive check)
> One of the most rigorously accessibility-tested sites on the web. The tool must not report critical failures here.

| | Assertion | Detail |
|---|---|---|
| ✓ | page_error event must NOT fire | |
| ✓ | pages_scanned must be >= 1 | pages_scanned=1 |
| ✓ | no critical-severity failures on known-good page | |

**Elapsed:** 189s

---

## LLM-as-Judge: OLMo-3 Narrative Quality

Claude (claude-haiku-4-5) grades the OLMo-3 executive summary on three dimensions after each run.

| Dimension | Score |
|---|---|
| Accuracy | 3/5 |
| Completeness | 2/5 |
| Actionability | 2/5 |
| **Average** | **2.3/5** ⚠️ |

> "The narrative correctly identifies the two main violations but contains vague remediation guidance, an incomplete contrast ratio statement ('ratio of :1'), and overstates the scope ('widespread and affect multiple users') without specific evidence from the audit data."

Blocking threshold: avg < 2.0. Current score is above threshold — advisory warning, not a failure.

---

## Result

```
✓  ALL ASSERTIONS PASSED
```

---

## Eval Architecture

| Layer | What it catches |
|---|---|
| Per-check recall | page_structure and form_errors must fire on a known-broken page |
| Recall floor | At least 2/5 checks must produce a hard failure |
| Severity calibration | At least one failure must be serious or critical severity |
| False-positive rate | No critical failures on a known-good, rigorously-tested page |
| LLM-as-judge | Claude grades OLMo-3 narrative on accuracy, completeness, actionability |
| Consistency (opt-in) | Runs page_structure twice, asserts stable result across independent runs |
