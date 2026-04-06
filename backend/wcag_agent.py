#!/usr/bin/env python3
"""
WCAG Testing Agent — OLMo2 Report Narrator
Uses allenai/OLMo-2-1124-7B-Instruct to generate professional
accessibility narratives from programmatic test findings.

All 5 WCAG tests are fully programmatic (Playwright DOM/CSS inspection).
OLMo2 is called once at the end to produce the executive summary.
"""

import asyncio
import json
from io import BytesIO
from pathlib import Path
import base64

from playwright.async_api import Page
from PIL import Image
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class WCAGAgent:
    MODEL_NAME = "allenai/OLMo-2-1124-7B-Instruct"

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        use_quantization: bool = False,
    ):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Initializing WCAG agent on {self.device}")
        print(f"Loading {model_name}...")

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        model_kwargs: dict = {
            "torch_dtype": torch.bfloat16 if self.device == "cuda" else torch.float32,
            "device_map": "auto" if self.device == "cuda" else None,
        }

        if use_quantization and self.device == "cuda":
            from transformers import BitsAndBytesConfig
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )

        self.model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.model.eval()
        print("WCAG OLMo2 agent ready")

    # ── Narrative generation ───────────────────────────────────────────────────

    async def generate_narrative(self, results: list, url: str) -> str:
        """
        Produces a professional executive summary from structured test results.
        Runs OLMo2 inference in a thread to avoid blocking the async event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._narrative_sync, results, url)

    def _narrative_sync(self, results: list, url: str) -> str:
        """Synchronous OLMo2 text generation."""
        try:
            findings = [
                {
                    "test": r.get("test_name"),
                    "result": r.get("result"),
                    "wcag_criteria": r.get("wcag_criteria", []),
                    "severity": r.get("severity", ""),
                    "issue": r.get("failure_reason", ""),
                    "recommendation": r.get("recommendation", ""),
                }
                for r in results
            ]

            failed = [f for f in findings if f["result"] == "fail"]
            passed = [f for f in findings if f["result"] == "pass"]

            prompt = (
                f"You are a professional web accessibility auditor. "
                f"You have just completed a WCAG 2.1 Level AA automated audit of: {url}\n\n"
                f"Test findings:\n{json.dumps(findings, indent=2)}\n\n"
                f"Write a concise executive summary (3–4 paragraphs) that:\n"
                f"1. States overall compliance status ({len(passed)}/{len(findings)} tests passed)\n"
                f"2. Highlights the most critical issues with specific WCAG criteria references\n"
                f"3. Provides prioritized, actionable remediation steps for developers\n"
                f"4. Notes what is working well\n\n"
                f"Be specific, professional, and address the development team directly."
            )

            messages = [{"role": "user", "content": prompt}]
            formatted = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.tokenizer(formatted, return_tensors="pt").to(self.device)

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=600,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.9,
                )

            new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
            narrative = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
            print(f"[OLMo2] Narrative generated ({len(narrative)} chars)")
            return narrative

        except Exception as e:
            print(f"[OLMo2] Narrative generation error: {e}")
            import traceback
            traceback.print_exc()
            return ""

    # ── Screenshot utilities (used by all tests) ──────────────────────────────

    @staticmethod
    async def screenshot_to_image(page: Page) -> Image.Image:
        """Capture current page as PIL Image."""
        raw = await page.screenshot(full_page=False)
        return Image.open(BytesIO(raw))

    @staticmethod
    def image_to_base64(img: Image.Image) -> str:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def save_screenshot(img: Image.Image, run_dir: Path, name: str) -> str:
        path = run_dir / f"{name}.png"
        img.save(path)
        return str(path)
