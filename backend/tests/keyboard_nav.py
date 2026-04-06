"""
WCAG 2.1 Keyboard Navigation Test — Fully Programmatic
Maps to: 2.1.1 (Keyboard), 2.1.2 (No Keyboard Trap), 2.4.3 (Focus Order)

Drives Tab through the page, inspects computed CSS for each focused element.
No VLM — DOM is the sole authority for pass/fail.
"""

import asyncio
from typing import AsyncGenerator

from tests.base_test import BaseWCAGTest, TestResult

MAX_TABS = 10


class KeyboardNavTest(BaseWCAGTest):
    TEST_ID = "keyboard_nav"
    TEST_NAME = "Keyboard-Only Navigation"
    WCAG_CRITERIA = ["2.1.1", "2.1.2", "2.4.3"]
    DEFAULT_SEVERITY = "critical"

    async def run(self, page, task: str) -> AsyncGenerator[dict, None]:
        failures = []
        steps = []
        prev_element = None
        stuck_count = 0

        yield self._progress("Starting keyboard navigation test...")
        await page.evaluate("document.activeElement && document.activeElement.blur()")
        await asyncio.sleep(0.3)

        for tab_num in range(1, MAX_TABS + 1):
            yield self._progress(f"Tab press {tab_num}/{MAX_TABS}...")
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.4)

            focus_info = await page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return {
                    tag: el.tagName,
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80),
                    role: el.getAttribute('role') || '',
                    type: el.getAttribute('type') || '',
                    outlineWidth: style.outlineWidth,
                    outlineColor: style.outlineColor,
                    outlineStyle: style.outlineStyle,
                    boxShadow: style.boxShadow,
                    visible: rect.width > 0 && rect.height > 0,
                    x: rect.x,
                    y: rect.y,
                }
            }""")

            # Trap detection: same element 3+ tabs in a row
            element_key = str(focus_info)
            if element_key == prev_element:
                stuck_count += 1
            else:
                stuck_count = 0
            prev_element = element_key

            if stuck_count >= 3:
                screenshot = await self.agent.screenshot_to_image(page)
                sp = self.agent.save_screenshot(screenshot, self.run_dir, f"keyboard_trap_{tab_num}")
                sb64 = self.agent.image_to_base64(screenshot)
                yield self._result(TestResult(
                    test_id=self.TEST_ID,
                    test_name=self.TEST_NAME,
                    result="fail",
                    wcag_criteria=["2.1.2"],
                    severity="critical",
                    failure_reason="Keyboard trap: focus did not move after 3 consecutive Tab presses.",
                    recommendation=(
                        "Ensure all custom widgets, modals, and date pickers "
                        "allow Tab/Shift+Tab to exit."
                    ),
                    screenshot_path=sp,
                    screenshot_b64=sb64,
                ))
                return

            if not focus_info or not focus_info.get("visible"):
                continue

            has_outline = (
                focus_info.get("outlineStyle", "none") not in ("none", "")
                and focus_info.get("outlineWidth", "0px") not in ("0px", "0")
            )
            has_shadow = focus_info.get("boxShadow", "none") not in ("none", "")
            el_desc = (
                f"<{focus_info['tag']}> '{focus_info['text']}'"
                if focus_info.get("text")
                else f"<{focus_info['tag']}>"
            )

            if not has_outline and not has_shadow:
                screenshot = await self.agent.screenshot_to_image(page)
                sp = self.agent.save_screenshot(screenshot, self.run_dir, f"keyboard_tab{tab_num}")
                sb64 = self.agent.image_to_base64(screenshot)
                analysis = {
                    "result": "fail",
                    "failure_reason": f"No visible focus indicator on {el_desc}",
                    "wcag_criteria": ["2.4.7"],
                    "severity": "major",
                    "recommendation": (
                        "Add :focus { outline: 2px solid #005fcc; outline-offset: 2px; } "
                        "or equivalent box-shadow. Never remove focus styles without an alternative."
                    ),
                }
                failures.append({
                    "tab": tab_num, "focus_info": focus_info,
                    "analysis": analysis, "screenshot_path": sp, "screenshot_b64": sb64,
                })
            else:
                analysis = {"result": "pass", "focused_element": el_desc}

            steps.append({"tab": tab_num, "focus_info": focus_info, "analysis": analysis})

            if tab_num > 5 and focus_info.get("y", 999) < 100:
                yield self._progress("Focus cycled back to top — done.")
                break

        summary = await self.agent.screenshot_to_image(page)
        summary_path = self.agent.save_screenshot(summary, self.run_dir, "keyboard_summary")
        summary_b64 = self.agent.image_to_base64(summary)

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
                details={"steps": steps, "failure_count": len(failures)},
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
                details={"steps": steps, "tabs_tested": len(steps)},
            )

        yield self._result(result)
