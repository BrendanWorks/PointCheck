"""
WCAG 2.1 Color & Contrast Test — Fully Programmatic
Maps to: 1.4.1 (Use of Color), 1.4.3 (Contrast Minimum)

Applies Deuteranopia CSS filter, then calculates WCAG contrast ratios
for all visible text elements via computed styles in the DOM.
No VLM required.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

# SVG-based Deuteranopia color matrix
DEUTERANOPIA_CSS = """
html {
  filter: url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'><filter id='d'><feColorMatrix type='matrix' values='0.367 0.861 -0.228 0 0  0.280 0.673 0.047 0 0  -0.012 0.043 0.969 0 0  0 0 0 1 0'/></filter></svg>#d") !important;
}
"""

CONTRAST_JS = """
() => {
    function luminance(r, g, b) {
        return [r, g, b].reduce((sum, v, i) => {
            v /= 255;
            const lin = v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
            return sum + lin * [0.2126, 0.7152, 0.0722][i];
        }, 0);
    }
    function parseRGB(color) {
        const m = color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
        if (!m) return null;
        return { rgb: [+m[1], +m[2], +m[3]], alpha: m[4] !== undefined ? parseFloat(m[4]) : 1 };
    }
    function contrast(fg, bg) {
        const l1 = luminance(...fg), l2 = luminance(...bg);
        return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    }
    // Walk up the DOM to find the actual rendered background color,
    // compositing alpha layers. Transparent elements inherit from parents.
    function getEffectiveBg(el) {
        let node = el;
        let r = 255, g = 255, b = 255; // default white page bg
        const stack = [];
        while (node && node.tagName !== 'HTML') {
            const p = parseRGB(window.getComputedStyle(node).backgroundColor);
            if (p && p.alpha > 0.01) { stack.push(p); }
            node = node.parentElement;
        }
        // Composite from bottom up
        for (let i = stack.length - 1; i >= 0; i--) {
            const { rgb, alpha } = stack[i];
            r = Math.round(rgb[0] * alpha + r * (1 - alpha));
            g = Math.round(rgb[1] * alpha + g * (1 - alpha));
            b = Math.round(rgb[2] * alpha + b * (1 - alpha));
        }
        return [r, g, b];
    }

    const els = Array.from(document.querySelectorAll(
        'p, h1, h2, h3, h4, h5, h6, a, button, label, li, td, th, span, div'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        const text = (el.innerText || '').trim();
        // Only leaf-ish nodes with actual visible text
        return r.width > 0 && r.height > 0 && text.length > 1 && text.length < 200;
    }).slice(0, 60);

    const failures = [], checked = [];
    const seen = new Set();
    for (const el of els) {
        const s = window.getComputedStyle(el);
        const fgParsed = parseRGB(s.color);
        if (!fgParsed) continue;
        const fg = fgParsed.rgb;
        const bg = getEffectiveBg(el);
        const ratio = contrast(fg, bg);
        const size = parseFloat(s.fontSize);
        const weight = parseInt(s.fontWeight) || 400;
        const large = size >= 24 || (size >= 18.67 && weight >= 700);
        const threshold = large ? 3.0 : 4.5;
        const text = (el.innerText || '').trim().slice(0, 60);
        const key = text + fg.join(',') + bg.join(',');
        if (seen.has(key)) continue;
        seen.add(key);
        const entry = { tag: el.tagName, text, ratio: Math.round(ratio*100)/100,
                        threshold, passes: ratio >= threshold,
                        fg: 'rgb('+fg+')', bg: 'rgb('+bg+')' };
        checked.push(entry);
        if (!entry.passes) failures.push(entry);
    }
    return { failures: failures.slice(0, 8), checked: checked.length };
}
"""


class ColorBlindnessTest(BaseWCAGTest):
    TEST_ID = "color_blindness"
    TEST_NAME = "Color-Blindness & Contrast Check"
    WCAG_CRITERIA = ["1.4.1", "1.4.3"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        yield self._progress("Capturing baseline screenshot...")
        baseline = await self.agent.screenshot_to_image(page)
        self.agent.save_screenshot(baseline, self.run_dir, "color_baseline")

        yield self._progress("Checking baseline contrast ratios...")
        baseline_result = await page.evaluate(CONTRAST_JS)

        yield self._progress("Injecting Deuteranopia (red-green) filter...")
        await page.evaluate(f"""() => {{
            const s = document.createElement('style');
            s.id = '__wcag_deuteranopia__';
            s.textContent = `{DEUTERANOPIA_CSS}`;
            document.head.appendChild(s);
        }}""")
        await asyncio.sleep(0.5)

        yield self._progress("Checking contrast ratios under color-blindness filter...")
        cb_result = await page.evaluate(CONTRAST_JS)

        yield self._progress("Taking color-filtered screenshot...")
        cb_shot = await self.agent.screenshot_to_image(page)
        screenshot_path = self.agent.save_screenshot(
            cb_shot, self.run_dir, "color_deuteranopia"
        )
        screenshot_b64 = self.agent.image_to_base64(cb_shot)

        await page.evaluate("""() => {
            const el = document.getElementById('__wcag_deuteranopia__');
            if (el) el.remove();
        }""")

        # Merge failures from both passes (deduplicated by text)
        seen = set()
        all_failures = []
        for f in baseline_result.get("failures", []) + cb_result.get("failures", []):
            key = f["text"]
            if key not in seen:
                seen.add(key)
                all_failures.append(f)

        total_checked = max(
            baseline_result.get("checked", 0), cb_result.get("checked", 0)
        )

        if all_failures:
            parts = [
                f"<{f['tag']}> \"{f['text']}\": {f['ratio']}:1 (needs {f['threshold']}:1)"
                for f in all_failures[:3]
            ]
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=["1.4.3"],
                severity="major",
                failure_reason=f"Insufficient contrast: {'; '.join(parts)}",
                recommendation=(
                    "Ensure text meets WCAG AA: 4.5:1 for normal text, 3:1 for large text "
                    "(≥24px, or ≥18.67px bold). Use a contrast checker tool. "
                    "Never rely on color alone — add icons, patterns, or text labels."
                ),
                screenshot_path=screenshot_path,
                screenshot_b64=screenshot_b64,
                details={
                    "contrast_failures": all_failures,
                    "elements_checked": total_checked,
                },
            )
        else:
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="pass",
                wcag_criteria=self.WCAG_CRITERIA,
                severity="minor",
                failure_reason="",
                recommendation="",
                screenshot_path=screenshot_path,
                screenshot_b64=screenshot_b64,
                details={
                    "elements_checked": total_checked,
                    "contrast_failures": [],
                },
            )

        yield self._result(result)
