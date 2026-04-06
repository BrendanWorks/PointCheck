"""
WCAG 2.1 Focus Indicator Test
Maps to: 2.4.7 (Focus Visible)

DOM-only test: tabs through each interactive element and inspects
computed CSS to determine whether a visible focus indicator exists.
No MolmoWeb inference — pure CSS property analysis for speed.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

MAX_TABS = 15


class FocusIndicatorTest(BaseWCAGTest):
    TEST_ID = "focus_indicator"
    TEST_NAME = "Focus Visibility Check"
    WCAG_CRITERIA = ["2.4.7"]
    DEFAULT_SEVERITY = "major"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        steps = []

        yield self._progress("Starting focus indicator test (DOM-based)...")
        await page.evaluate("document.activeElement && document.activeElement.blur()")
        await asyncio.sleep(0.3)

        for tab_num in range(1, MAX_TABS + 1):
            yield self._progress(f"Checking focus indicator on Tab {tab_num}/{MAX_TABS}...")

            await page.keyboard.press("Tab")
            await asyncio.sleep(0.3)

            focus_info = await page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 60),
                    role: el.getAttribute('role') || '',
                    outlineWidth: style.outlineWidth,
                    outlineStyle: style.outlineStyle,
                    outlineColor: style.outlineColor,
                    boxShadow: style.boxShadow,
                    backgroundColor: style.backgroundColor,
                    border: style.border,
                    visible: rect.width > 0 && rect.height > 0,
                    x: rect.x,
                    y: rect.y,
                }
            }""")

            if not focus_info or not focus_info.get("visible"):
                continue

            # Check CSS properties for a visible focus indicator
            has_outline = (
                focus_info.get("outlineStyle", "none") not in ("none", "")
                and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
            )
            has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")

            element_desc = (
                f"<{focus_info['tag']}> '{focus_info['text']}'"
                if focus_info.get("text")
                else f"<{focus_info['tag']}>"
            )

            if has_outline or has_shadow:
                indicator = []
                if has_outline:
                    indicator.append(
                        f"outline: {focus_info['outlineWidth']} "
                        f"{focus_info['outlineStyle']} {focus_info['outlineColor']}"
                    )
                if has_shadow:
                    indicator.append(f"box-shadow: {focus_info['boxShadow'][:60]}")
                analysis = {
                    "result": "pass",
                    "focus_indicator_visible": True,
                    "indicator": "; ".join(indicator),
                    "focused_element": element_desc,
                    "failure_reason": "",
                    "recommendation": "",
                    "wcag_criteria": ["2.4.7"],
                    "severity": "minor",
                }
            else:
                analysis = {
                    "result": "fail",
                    "focus_indicator_visible": False,
                    "focused_element": element_desc,
                    "failure_reason": (
                        f"No visible focus indicator on {element_desc} "
                        f"(outline: {focus_info.get('outlineStyle', 'none')}, "
                        f"box-shadow: {focus_info.get('boxShadow', 'none')[:30]})"
                    ),
                    "wcag_criteria": ["2.4.7"],
                    "severity": "major",
                    "recommendation": (
                        "Add :focus { outline: 2px solid #005fcc; outline-offset: 2px; } "
                        "or a visible box-shadow. Never use outline: none without an alternative."
                    ),
                }

            # Only take a screenshot if there's a failure (saves time)
            screenshot_path = None
            screenshot_b64 = None
            if analysis["result"] == "fail":
                screenshot = await self.agent.screenshot_to_image(page)
                screenshot_path = self.agent.save_screenshot(
                    screenshot, self.run_dir, f"focus_tab{tab_num}"
                )
                screenshot_b64 = self.agent.image_to_base64(screenshot)

            step = {
                "tab": tab_num,
                "focus_info": focus_info,
                "analysis": analysis,
                "screenshot_path": screenshot_path,
            }
            steps.append(step)

            if analysis["result"] == "fail":
                failures.append({**step, "screenshot_b64": screenshot_b64})

            # If focus cycled back to top, we're done
            if tab_num > 5 and focus_info and focus_info.get("y", 999) < 50:
                yield self._progress("Focus cycled back to top — done.")
                break

        # Take one summary screenshot at end for the report
        summary_screenshot = await self.agent.screenshot_to_image(page)
        summary_path = self.agent.save_screenshot(
            summary_screenshot, self.run_dir, "focus_summary"
        )
        summary_b64 = self.agent.image_to_base64(summary_screenshot)

        if failures:
            worst = failures[0]
            a = worst["analysis"]
            result = TestResult(
                test_id=self.TEST_ID,
                test_name=self.TEST_NAME,
                result="fail",
                wcag_criteria=a.get("wcag_criteria", self.WCAG_CRITERIA),
                severity=a.get("severity", self.DEFAULT_SEVERITY),
                failure_reason=a.get("failure_reason", ""),
                recommendation=a.get("recommendation", ""),
                screenshot_path=worst.get("screenshot_path") or summary_path,
                screenshot_b64=worst.get("screenshot_b64") or summary_b64,
                details={
                    "steps": steps,
                    "failure_count": len(failures),
                    "elements_checked": len(steps),
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
                screenshot_path=summary_path,
                screenshot_b64=summary_b64,
                details={
                    "steps": steps,
                    "tabs_tested": len(steps),
                    "elements_checked": len(steps),
                },
            )

        yield self._result(result)
