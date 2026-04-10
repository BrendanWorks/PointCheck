"""
WCAG 2.1 Page Structure & Semantics — Fully Programmatic
Maps to:
  1.1.1  Non-text Content      (alt text on images)
  1.3.1  Info and Relationships (heading hierarchy, landmark regions, table headers)
  1.4.1  Use of Color          (inline links indistinguishable without color)
  2.2.2  Pause, Stop, Hide     (blink and marquee elements)
  2.4.2  Page Titled           (descriptive page title)
  2.4.4  Link Purpose          (vague link text)
  2.5.5  Touch Target Size     (minimum 24×24px interactive targets)
  3.1.1  Language of Page      (lang attribute on <html>)
  4.1.1  Parsing               (duplicate IDs)
  4.1.2  Name, Role, Value     (ARIA misuse, unlabelled iframes, interactive elements)

All checks run as a single JS evaluation — no VLM, no network, ~100ms.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

STRUCTURE_JS = """
() => {
    const issues = [];

    // ── 3.1.1  Language of Page ─────────────────────────────────────────
    const lang = document.documentElement.getAttribute('lang') || '';
    if (!lang.trim()) {
        issues.push({
            criterion: '3.1.1',
            severity: 'major',
            description: 'Missing lang attribute on <html> element. Screen readers cannot determine the page language.',
            fix: 'Add lang="en" (or appropriate language code) to the <html> tag.',
        });
    }

    // ── 2.4.2  Page Titled ──────────────────────────────────────────────
    const title = (document.title || '').trim();
    if (!title) {
        issues.push({
            criterion: '2.4.2',
            severity: 'major',
            description: 'Page has no <title> element. Users cannot identify the page from browser tabs or history.',
            fix: 'Add a descriptive <title> to the <head>.',
        });
    } else if (title.length < 5 || /^(untitled|page|home|index)$/i.test(title)) {
        issues.push({
            criterion: '2.4.2',
            severity: 'minor',
            description: `Page title "${title}" is not descriptive. Titles should identify the page purpose.`,
            fix: 'Use a title that describes the page content, e.g. "Contact Us — Acme Corp".',
        });
    }

    // ── 1.1.1  Non-text Content (alt text) ─────────────────────────────
    const images = Array.from(document.querySelectorAll('img'));
    const missingAlt = images.filter(img => !img.hasAttribute('alt'));
    const emptyAltOnMeaningful = images.filter(img => {
        if (!img.hasAttribute('alt') || img.getAttribute('alt') !== '') return false;
        // Likely decorative if tiny, in a <figure> with figcaption, or role=presentation
        const r = img.getBoundingClientRect();
        const role = img.getAttribute('role') || '';
        const isDecorative = role === 'presentation' || role === 'none' ||
                             img.getAttribute('aria-hidden') === 'true' ||
                             r.width < 10 || r.height < 10;
        // Flag if it appears to be a meaningful image (large, linked, or in main content)
        const isLinked = !!img.closest('a');
        const isLarge = r.width > 100 && r.height > 100;
        return !isDecorative && (isLinked || isLarge);
    });
    const filenameAlt = images.filter(img => {
        const alt = img.getAttribute('alt') || '';
        return /\\.(png|jpg|jpeg|gif|svg|webp)$/i.test(alt) || /^img_?\\d+/i.test(alt);
    });

    if (missingAlt.length > 0) {
        const examples = missingAlt.slice(0, 3).map(img =>
            img.getAttribute('src') ? img.getAttribute('src').split('/').pop().slice(0, 40) : '<img>'
        );
        issues.push({
            criterion: '1.1.1',
            severity: 'critical',
            description: `${missingAlt.length} image(s) missing alt attribute entirely.`,
            examples,
            fix: 'Add alt="" for decorative images, or descriptive alt text for meaningful images.',
        });
    }
    if (emptyAltOnMeaningful.length > 0) {
        const examples = emptyAltOnMeaningful.slice(0, 3).map(img =>
            (img.getAttribute('src') || '').split('/').pop().slice(0, 40)
        );
        issues.push({
            criterion: '1.1.1',
            severity: 'major',
            description: `${emptyAltOnMeaningful.length} large or linked image(s) have empty alt text (alt="") but appear meaningful.`,
            examples,
            fix: 'Provide descriptive alt text for images that convey information or are used as links.',
        });
    }
    if (filenameAlt.length > 0) {
        issues.push({
            criterion: '1.1.1',
            severity: 'minor',
            description: `${filenameAlt.length} image(s) have filename-style alt text (e.g. "img_001.jpg").`,
            examples: filenameAlt.slice(0, 2).map(img => img.getAttribute('alt')),
            fix: 'Replace filename alt text with a description of what the image shows.',
        });
    }

    // ── 1.3.1  Heading Hierarchy ────────────────────────────────────────
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
        .filter(h => {
            const r = h.getBoundingClientRect();
            return r.width > 0 || r.height > 0;
        });
    const h1s = headings.filter(h => h.tagName === 'H1');
    if (h1s.length === 0 && document.body) {
        issues.push({
            criterion: '1.3.1',
            severity: 'major',
            description: 'No <h1> found on the page. Every page should have a single main heading.',
            fix: 'Add one <h1> that describes the main topic of the page.',
        });
    } else if (h1s.length > 1) {
        issues.push({
            criterion: '1.3.1',
            severity: 'minor',
            description: `${h1s.length} <h1> elements found. Pages should have exactly one <h1>.`,
            examples: h1s.slice(0, 3).map(h => (h.innerText || '').trim().slice(0, 50)),
            fix: 'Use one <h1> per page; use <h2>–<h6> for subsections.',
        });
    }
    // Skipped heading levels (e.g. h1 → h3 skipping h2)
    const skips = [];
    let prevLevel = 0;
    for (const h of headings) {
        const level = parseInt(h.tagName[1]);
        if (prevLevel > 0 && level > prevLevel + 1) {
            skips.push(`<h${prevLevel}> → <h${level}> "${(h.innerText||'').trim().slice(0,40)}"`);
        }
        prevLevel = level;
    }
    if (skips.length > 0) {
        issues.push({
            criterion: '1.3.1',
            severity: 'minor',
            description: `Heading levels skipped ${skips.length} time(s). Screen reader users rely on a logical heading outline.`,
            examples: skips.slice(0, 3),
            fix: 'Do not skip heading levels. Use h1→h2→h3 in order.',
        });
    }

    // ── 1.3.1  Landmark Regions ─────────────────────────────────────────
    const mainLandmarks = Array.from(document.querySelectorAll('main, [role="main"]'))
        .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 || r.height > 0; });
    if (mainLandmarks.length === 0) {
        issues.push({
            criterion: '1.3.1',
            severity: 'major',
            description: 'No <main> landmark found. Screen reader users cannot skip directly to the main content.',
            fix: 'Wrap the primary page content in a <main> element.',
        });
    } else if (mainLandmarks.length > 1) {
        issues.push({
            criterion: '1.3.1',
            severity: 'major',
            description: `${mainLandmarks.length} <main> landmarks found. A page should have exactly one <main>.`,
            fix: 'Consolidate page content into a single <main> element.',
        });
    }
    const navLandmarks = Array.from(document.querySelectorAll('nav, [role="navigation"]'));
    const totalLinks = document.querySelectorAll('a[href]').length;
    if (navLandmarks.length === 0 && totalLinks >= 5) {
        issues.push({
            criterion: '1.3.1',
            severity: 'minor',
            description: `No <nav> landmark found, but the page has ${totalLinks} links. Navigation groups should be labelled with <nav>.`,
            fix: 'Wrap groups of navigation links in <nav> elements so screen reader users can find and skip them.',
        });
    }

    // ── 4.1.1  Duplicate IDs ────────────────────────────────────────────
    const idCounts = {};
    Array.from(document.querySelectorAll('[id]')).forEach(el => {
        const id = el.id.trim();
        if (id) idCounts[id] = (idCounts[id] || 0) + 1;
    });
    const dupIds = Object.entries(idCounts)
        .filter(([, count]) => count > 1)
        .map(([id]) => id);
    if (dupIds.length > 0) {
        issues.push({
            criterion: '4.1.1',
            severity: 'major',
            description: `${dupIds.length} duplicate ID value(s) found. Duplicate IDs break ARIA associations (aria-labelledby, aria-describedby) and <label for> bindings.`,
            examples: dupIds.slice(0, 5),
            fix: 'Every id attribute must be unique within the page. Use classes instead of IDs for repeated styling hooks.',
        });
    }

    // ── 2.2.2  Pause, Stop, Hide (blink / marquee) ──────────────────────
    const blinkEls   = Array.from(document.querySelectorAll('blink'));
    const marqueeEls = Array.from(document.querySelectorAll('marquee'));
    if (blinkEls.length > 0 || marqueeEls.length > 0) {
        const parts = [];
        if (blinkEls.length > 0)   parts.push(`${blinkEls.length} <blink> element(s)`);
        if (marqueeEls.length > 0) parts.push(`${marqueeEls.length} <marquee> element(s)`);
        issues.push({
            criterion: '2.2.2',
            severity: 'major',
            description: `${parts.join(' and ')} found. These deprecated elements cause automatic movement that users cannot pause or stop.`,
            examples: [
                ...blinkEls.slice(0, 2).map(el => `<blink> "${(el.innerText || '').trim().slice(0, 40)}"`),
                ...marqueeEls.slice(0, 2).map(el => `<marquee> "${(el.innerText || '').trim().slice(0, 40)}"`)
            ].slice(0, 3),
            fix: 'Remove <blink> and <marquee> entirely. If animation is needed, use CSS with a prefers-reduced-motion media query and provide a pause control.',
        });
    }

    // ── 2.4.4  Link Purpose (vague text) ───────────────────────────────
    const VAGUE = /^(click here|here|read more|more|learn more|details|link|this|continue|go|view|see more|info|information|download|click|tap)$/i;
    const vagueLinks = Array.from(document.querySelectorAll('a[href]')).filter(a => {
        const text = (a.innerText || a.getAttribute('aria-label') || '').trim();
        const title = a.getAttribute('title') || '';
        const ariaLabel = a.getAttribute('aria-label') || '';
        // Pass if aria-label or title provides context
        if (ariaLabel.trim().length > 10 || title.trim().length > 10) return false;
        return VAGUE.test(text) && text.length < 15;
    });
    if (vagueLinks.length > 0) {
        const examples = [...new Set(vagueLinks.map(a => (a.innerText||'').trim()))].slice(0, 5);
        issues.push({
            criterion: '2.4.4',
            severity: 'major',
            description: `${vagueLinks.length} link(s) have vague text that doesn't describe the destination.`,
            examples,
            fix: 'Use descriptive link text, or add aria-label="Read more about [topic]". Avoid generic text like "click here" or "read more".',
        });
    }

    // ── 2.5.8  Touch Target Size (WCAG 2.2 AA) ─────────────────────────
    // 2.5.5 is WCAG 2.1 AAA (44×44px). We test to the 2.2 AA threshold
    // instead: 2.5.8 requires 24×24px minimum (or adequate spacing).
    const MIN_TARGET_PX = 24;
    const interactiveTargets = Array.from(document.querySelectorAll(
        'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"]'
    )).filter(el => {
        const tab = el.getAttribute('tabindex');
        if (tab !== null && parseInt(tab) < 0) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    });
    const smallTargets = interactiveTargets.filter(el => {
        const r = el.getBoundingClientRect();
        return r.width < MIN_TARGET_PX || r.height < MIN_TARGET_PX;
    }).map(el => {
        const r = el.getBoundingClientRect();
        const label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('value') || el.getAttribute('placeholder') || '').trim().slice(0, 40);
        return `<${el.tagName.toLowerCase()}>${label ? ' "' + label + '"' : ''} (${Math.round(r.width)}×${Math.round(r.height)}px)`;
    }).slice(0, 5);
    if (smallTargets.length > 0) {
        issues.push({
            criterion: '2.5.8',
            severity: 'minor',
            description: `${smallTargets.length} interactive element(s) have touch targets smaller than 24×24px (WCAG 2.2 AA, criterion 2.5.8).`,
            examples: smallTargets,
            fix: 'Ensure all interactive elements have a minimum 24×24px clickable area. Use padding to grow the hit area without changing visual size.',
        });
    }

    // ── 1.3.1  Table Headers ────────────────────────────────────────────
    // Data cells (<td>) in tables that have no associated header (<th> or scope)
    const dataTables = Array.from(document.querySelectorAll('table')).filter(t => {
        // Skip layout tables (no th, no caption, role=presentation/none)
        const role = t.getAttribute('role') || '';
        if (role === 'presentation' || role === 'none') return false;
        return t.querySelector('th') !== null || t.querySelector('caption') !== null;
    });
    const tdsMissingHeader = [];
    for (const table of dataTables) {
        const rows = Array.from(table.querySelectorAll('tr'));
        const hasColHeaders = table.querySelector('th') !== null;
        if (!hasColHeaders) {
            // All tds in this table lack headers
            const tds = Array.from(table.querySelectorAll('td'));
            tds.slice(0, 2).forEach(td =>
                tdsMissingHeader.push((td.innerText || '').trim().slice(0, 40))
            );
        } else {
            // Check for tds that are not covered by any th in their row or column
            rows.forEach(row => {
                const ths = row.querySelectorAll('th');
                const tds = row.querySelectorAll('td');
                if (ths.length === 0 && tds.length > 0) {
                    // Row has only tds — check if a preceding row has th[scope=col]
                    const table = row.closest('table');
                    const hasColScope = table && table.querySelector('th[scope="col"]');
                    if (!hasColScope) {
                        tdsMissingHeader.push((tds[0].innerText || '').trim().slice(0, 40));
                    }
                }
            });
        }
    }
    if (tdsMissingHeader.length > 0) {
        issues.push({
            criterion: '1.3.1',
            severity: 'major',
            description: `Data table cell(s) have no associated header. Screen readers cannot convey the relationship between data and its label.`,
            examples: [...new Set(tdsMissingHeader)].slice(0, 3),
            fix: 'Add <th scope="col"> for column headers and <th scope="row"> for row headers. Use id/headers attributes for complex tables.',
        });
    }

    // ── 4.1.2  iframe title ──────────────────────────────────────────────
    const untitledFrames = Array.from(document.querySelectorAll('iframe, frame')).filter(f => {
        const title = (f.getAttribute('title') || '').trim();
        const ariaLabel = (f.getAttribute('aria-label') || '').trim();
        const ariaLabelledby = f.getAttribute('aria-labelledby') || '';
        return !title && !ariaLabel && !ariaLabelledby;
    });
    if (untitledFrames.length > 0) {
        issues.push({
            criterion: '4.1.2',
            severity: 'major',
            description: `${untitledFrames.length} iframe(s) have no title attribute. Screen reader users cannot identify the frame's purpose.`,
            examples: untitledFrames.slice(0, 3).map(f =>
                (f.getAttribute('src') || '<iframe>').split('/').pop().slice(0, 50)
            ),
            fix: 'Add a descriptive title attribute to every <iframe>, e.g. title="Payment form".',
        });
    }

    // ── 1.4.1  Links in Text (color-only distinction) ───────────────────
    // Inline links that share the same foreground color as surrounding text
    // and have no underline, border, or other non-color visual cue.
    const inlineLinks = Array.from(document.querySelectorAll('p a[href], li a[href], td a[href]'));
    const colorOnlyLinks = inlineLinks.filter(a => {
        const style = window.getComputedStyle(a);
        const parentStyle = window.getComputedStyle(a.parentElement);
        // Skip if underline is present (the most common non-color cue)
        if (style.textDecorationLine && style.textDecorationLine !== 'none') return false;
        // Skip if outline or border provides a visual cue
        if (style.outline !== 'none' && style.outlineWidth !== '0px') return false;
        if (style.borderBottom && style.borderBottomWidth !== '0px') return false;
        // Flag if link color matches parent text color (no color distinction either)
        const linkColor = style.color;
        const parentColor = parentStyle.color;
        return linkColor === parentColor;
    });
    if (colorOnlyLinks.length > 0) {
        issues.push({
            criterion: '1.4.1',
            severity: 'major',
            description: `${colorOnlyLinks.length} inline link(s) may be indistinguishable from surrounding text — no underline or non-color visual cue detected.`,
            examples: colorOnlyLinks.slice(0, 3).map(a => (a.innerText || '').trim().slice(0, 50)),
            fix: 'Ensure links within text are underlined, or use a non-color visual indicator (border, icon). Color alone is insufficient (WCAG 1.4.1).',
        });
    }

    // ── 4.1.2  Name, Role, Value (ARIA misuse) ─────────────────────────
    const ariaIssues = [];

    // Elements with role but missing required accessible name
    const roleNeedsName = ['button','link','checkbox','radio','textbox','combobox',
                           'listbox','option','menuitem','tab','treeitem'];
    const unnamedRoles = Array.from(document.querySelectorAll('[role]')).filter(el => {
        const role = el.getAttribute('role');
        if (!roleNeedsName.includes(role)) return false;
        const name = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') ||
                     (el.innerText || '').trim();
        return !name;
    });
    if (unnamedRoles.length > 0) {
        ariaIssues.push(`${unnamedRoles.length} element(s) with interactive role but no accessible name`);
    }

    // aria-required-children violations (simplified: role=list without role=listitem)
    const badLists = Array.from(document.querySelectorAll('[role="list"]')).filter(el => {
        const children = Array.from(el.children);
        return children.length > 0 && !children.some(c =>
            c.getAttribute('role') === 'listitem' || c.tagName === 'LI'
        );
    });
    if (badLists.length > 0) {
        ariaIssues.push(`${badLists.length} element(s) with role="list" missing role="listitem" children`);
    }

    // aria-hidden on focusable element (keyboard users get stranded)
    const hiddenFocusable = Array.from(document.querySelectorAll(
        '[aria-hidden="true"] a, [aria-hidden="true"] button, [aria-hidden="true"] input, [aria-hidden="true"] [tabindex]'
    )).filter(el => {
        const tab = el.getAttribute('tabindex');
        return tab === null || parseInt(tab) >= 0;
    });
    if (hiddenFocusable.length > 0) {
        ariaIssues.push(`${hiddenFocusable.length} focusable element(s) inside aria-hidden="true" — keyboard users can reach them but screen readers cannot`);
    }

    if (ariaIssues.length > 0) {
        issues.push({
            criterion: '4.1.2',
            severity: 'major',
            description: ariaIssues.join('; '),
            fix: 'Ensure all interactive elements have accessible names. Do not place focusable elements inside aria-hidden containers.',
        });
    }

    return issues;
}
"""

# Human-readable criterion labels for the failure summary
CRITERION_LABEL = {
    "1.1.1": "Non-text Content",
    "1.3.1": "Info and Relationships",
    "1.4.1": "Use of Color",
    "2.2.2": "Pause, Stop, Hide",
    "2.4.2": "Page Titled",
    "2.4.4": "Link Purpose",
    "2.5.8": "Target Size (Minimum)",  # WCAG 2.2 AA — replaces 2.5.5 (which is 2.1 AAA)
    "3.1.1": "Language of Page",
    "4.1.1": "Parsing",
    "4.1.2": "Name, Role, Value",
}

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


class PageStructureTest(BaseWCAGTest):
    TEST_ID = "page_structure"
    TEST_NAME = "Page Structure & Semantics"
    WCAG_CRITERIA = ["1.1.1", "1.3.1", "1.4.1", "2.2.2", "2.4.2", "2.4.4", "2.5.8", "3.1.1", "4.1.1", "4.1.2"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Running structural checks (alt text, headings, lang, links, ARIA)...")

        issues = await page.evaluate(STRUCTURE_JS)

        screenshot = await self.agent.screenshot_to_image(page)
        screenshot_path = self.agent.save_screenshot(screenshot, self.run_dir, "page_structure")
        screenshot_b64 = self.agent.image_to_base64(screenshot)

        if not issues:
            yield self._result(TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="pass",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                failure_reason="",
                recommendation="",
                screenshot_path=screenshot_path,
                screenshot_b64=screenshot_b64,
                details={"issues": []},
            ))
            return

        # Sort by severity, then criterion
        issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.get("severity", "minor"), 2), i.get("criterion", "")))

        criticals = [i for i in issues if i.get("severity") == "critical"]
        majors    = [i for i in issues if i.get("severity") == "major"]
        minors    = [i for i in issues if i.get("severity") == "minor"]

        overall_severity = "critical" if criticals else ("major" if majors else "minor")
        overall_result   = "fail" if (criticals or majors) else "warning"

        # Build failure reason from worst issues
        top = (criticals + majors + minors)[:3]
        parts = []
        for i in top:
            label = CRITERION_LABEL.get(i["criterion"], i["criterion"])
            desc = i["description"]
            if i.get("examples"):
                desc += f" (e.g. {', '.join(str(e) for e in i['examples'][:2])})"
            parts.append(f"[{i['criterion']} {label}] {desc}")
        failure_reason = " | ".join(parts)

        # Build recommendation from all issues
        recs = list(dict.fromkeys(i["fix"] for i in issues if i.get("fix")))
        recommendation = " ".join(recs[:3])

        # Affected criteria (deduplicated, sorted)
        wcag = sorted(set(i["criterion"] for i in issues))

        yield self._result(TestResult(
            test_id=self.TEST_ID,
            test_name=self.TEST_NAME,
            result=overall_result,
            wcag_criteria=wcag,
            severity=overall_severity,
            failure_reason=failure_reason,
            recommendation=recommendation,
            screenshot_path=screenshot_path,
            screenshot_b64=screenshot_b64,
            details={
                "issues": issues,
                "critical_count": len(criticals),
                "major_count": len(majors),
                "minor_count": len(minors),
            },
        ))
