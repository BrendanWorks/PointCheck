#!/usr/bin/env python3
"""
axe_runner.py — Run axe-core against a URL using the project's Playwright browser.

Injects axe-core 4.9.1 from cdnjs, runs axe.run(), and returns structured
violation data mapped to PointCheck check categories.

Usage (standalone):
    python3 axe_runner.py <url> [--json]

Output (--json):
    {
      "url": "...",
      "total_violations": N,
      "violations": [
        {"id": "...", "impact": "...", "description": "...", "nodes": N}
      ],
      "by_pointcheck": {
        "page_structure": ["image-alt", "heading-order", ...],
        "form_errors":    ["label", ...]
      }
    }

Used by regression_suite.py for cross-tool recall validation.
Requires: backend/venv with playwright installed, chromium browser available.
"""

import json
import sys

# ── Axe rule → PointCheck check mapping ──────────────────────────────────────
# Only maps rules that have genuine overlap with PointCheck's DOM/programmatic
# layer. Rules for visual-only checks (focus ring appearance, color blindness
# simulation) are deliberately excluded — Axe can't detect these.

AXE_TO_POINTCHECK: dict[str, str] = {
    # page_structure (1.1.1, 1.3.1, 2.4.2, 2.4.4, 3.1.1, 4.1.1, 4.1.2)
    "image-alt":                "page_structure",
    "image-redundant-alt":      "page_structure",
    "heading-order":            "page_structure",
    "page-has-heading-one":     "page_structure",
    "landmark-one-main":        "page_structure",
    "landmark-unique":          "page_structure",
    "region":                   "page_structure",
    "html-has-lang":            "page_structure",
    "html-lang-valid":          "page_structure",
    "document-title":           "page_structure",
    "link-name":                "page_structure",
    "link-in-text-block":       "page_structure",
    "button-name":              "page_structure",
    "frame-title":              "page_structure",
    "frame-title-unique":       "page_structure",
    "list":                     "page_structure",
    "listitem":                 "page_structure",
    "duplicate-id":             "page_structure",
    "duplicate-id-active":      "page_structure",
    "aria-required-attr":       "page_structure",
    "aria-required-children":   "page_structure",
    "aria-required-parent":     "page_structure",
    "aria-valid-attr":          "page_structure",
    "aria-valid-attr-value":    "page_structure",
    "aria-allowed-attr":        "page_structure",
    "aria-hidden-body":         "page_structure",
    "aria-hidden-focus":        "page_structure",
    "aria-roles":               "page_structure",
    "role-img-alt":             "page_structure",
    "td-headers-attr":          "page_structure",
    "th-has-data-cells":        "page_structure",
    # form_errors (3.3.1, 3.3.2, 3.3.3)
    "label":                    "form_errors",
    "label-content-name-mismatch": "form_errors",
    "form-field-multiple-labels":  "form_errors",
    "autocomplete-valid":          "form_errors",
    "select-name":                 "form_errors",
    "input-button-name":           "form_errors",
    # keyboard_nav (2.1.1, 2.1.2, 2.4.3)
    "scrollable-region-focusable": "keyboard_nav",
    "tabindex":                    "keyboard_nav",
    "focus-trap":                  "keyboard_nav",
    # page_structure — additional rules seen in the wild
    "input-image-alt":             "page_structure",
    "dlitem":                      "page_structure",
    "definition-list":             "page_structure",
    "object-alt":                  "page_structure",
    "svg-img-alt":                 "page_structure",
    "area-alt":                    "page_structure",
    "meta-refresh":                "page_structure",
    "skip-link":                   "keyboard_nav",
}

AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"


def run_axe(url: str, timeout_ms: int = 30_000) -> dict:
    """
    Load `url` in a headless Chromium browser, inject axe-core, run axe.run(),
    and return a structured result dict.

    Returns:
        {
            "url":             str,
            "total_violations": int,
            "violations":      list[{id, impact, description, nodes}],
            "by_pointcheck":   dict[check_id → list[rule_id]],
            "error":           str | None,
        }
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"url": url, "error": "playwright not installed", "violations": [],
                "by_pointcheck": {}, "total_violations": 0}

    violations = []
    error = None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)

            # Inject axe-core from CDN
            page.add_script_tag(url=AXE_CDN)
            page.wait_for_function("typeof axe !== 'undefined'", timeout=10_000)

            # Run axe and collect violations
            raw = page.evaluate("""async () => {
                const results = await axe.run(document, {
                    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] }
                });
                return {
                    violations: results.violations.map(v => ({
                        id:          v.id,
                        impact:      v.impact,
                        description: v.description,
                        help:        v.help,
                        nodes:       v.nodes.length,
                    }))
                };
            }""")

            violations = raw.get("violations", [])
            browser.close()

    except Exception as exc:
        error = str(exc)

    # Map violations to PointCheck check categories
    by_pointcheck: dict[str, list[str]] = {}
    for v in violations:
        check_id = AXE_TO_POINTCHECK.get(v["id"])
        if check_id:
            by_pointcheck.setdefault(check_id, []).append(v["id"])

    return {
        "url":              url,
        "total_violations": len(violations),
        "violations":       violations,
        "by_pointcheck":    by_pointcheck,
        "error":            error,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run axe-core against a URL")
    parser.add_argument("url", help="URL to scan")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output raw JSON")
    args = parser.parse_args()

    result = run_axe(args.url)

    if args.as_json:
        print(json.dumps(result, indent=2))
        sys.exit(0 if not result.get("error") else 1)

    # Human-readable output
    if result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"\nAxe-core 4.9.1 results for {result['url']}")
    print(f"Total violations: {result['total_violations']}\n")

    for v in sorted(result["violations"], key=lambda x: x["id"]):
        pc = AXE_TO_POINTCHECK.get(v["id"], "(no mapping)")
        print(f"  {v['id']:50s} impact={v['impact']:8s} nodes={v['nodes']}  → {pc}")

    print(f"\nMapped to PointCheck checks:")
    for check_id, rules in result["by_pointcheck"].items():
        print(f"  {check_id}: {rules}")
