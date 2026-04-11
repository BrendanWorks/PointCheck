"""
MolmoAccess-Eval dataset logger.

Writes a JSONL file (one record per check per page) capturing:
  - The page URL and check name
  - The screenshot path on disk
  - The MolmoWeb-8B prompt and raw response
  - The final pass/fail/warning result
  - WCAG criteria involved

This data becomes the MolmoAccess-Eval benchmark dataset (Phase 3).
Each record is a self-contained ground-truth annotation candidate.

Output location:  datasets/molmoaccess-eval/raw/<job_id>.jsonl
                  datasets/molmoaccess-eval/screenshots/<job_id>/<page_slug>/<check>.png
                  (screenshots are already saved by the checks themselves)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


_DATASET_ROOT = Path(__file__).parents[3] / "datasets" / "molmoaccess-eval"


def _slug(url: str) -> str:
    """Convert a URL to a filesystem-safe slug."""
    slug = re.sub(r'^https?://', '', url)
    slug = re.sub(r'[^\w\-]', '_', slug)
    return slug[:80]


class EvalLogger:
    """
    Append-only JSONL logger for building the MolmoAccess-Eval dataset.

    Usage:
        logger = EvalLogger(job_id="abc123")
        logger.log(page_url=..., check_id=..., result=..., ...)
        logger.close()
    """

    def __init__(self, job_id: str, dataset_root: Path = _DATASET_ROOT):
        self.job_id = job_id
        raw_dir = dataset_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        self._path = raw_dir / f"{job_id}.jsonl"
        self._fh = self._path.open("a", encoding="utf-8")
        self._count = 0

    def log(
        self,
        page_url: str,
        page_depth: int,
        check_id: str,
        check_name: str,
        wcag_criteria: list[str],
        result: str,          # pass | fail | warning | error
        severity: str,
        failure_reason: str,
        molmo_prompt: str,
        molmo_response: str,
        screenshot_path: Optional[str],
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        record = {
            "job_id": self.job_id,
            "timestamp": datetime.utcnow().isoformat(),
            "page_url": page_url,
            "page_depth": page_depth,
            "page_slug": _slug(page_url),
            "check_id": check_id,
            "check_name": check_name,
            "wcag_criteria": wcag_criteria,
            "result": result,
            "severity": severity,
            "failure_reason": failure_reason,
            "molmo_prompt": molmo_prompt,
            "molmo_response": molmo_response,
            "screenshot_path": screenshot_path,
            # Omit heavy detail fields to keep JSONL lean;
            # full details live in the parent report JSON.
            "details_summary": {
                k: v for k, v in (details or {}).items()
                if isinstance(v, (str, int, float, bool))
            },
        }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._count += 1

    def log_from_test_result(
        self,
        page_url: str,
        page_depth: int,
        check_id: str,
        check_name: str,
        result_dict: dict[str, Any],
    ) -> None:
        """Convenience wrapper: log directly from a TestResult.__dict__."""
        # Reconstruct the MolmoWeb prompt from the check's MOLMO_QUESTION
        # (stored in TestResult.molmo_analysis as the raw response)
        self.log(
            page_url=page_url,
            page_depth=page_depth,
            check_id=check_id,
            check_name=check_name,
            wcag_criteria=result_dict.get("wcag_criteria", []),
            result=result_dict.get("result", ""),
            severity=result_dict.get("severity", ""),
            failure_reason=result_dict.get("failure_reason", ""),
            molmo_prompt="[see check MOLMO_QUESTION]",
            molmo_response=result_dict.get("molmo_analysis", ""),
            screenshot_path=result_dict.get("screenshot_path"),
            details=result_dict.get("details"),
        )

    def close(self) -> None:
        self._fh.close()
        print(f"[EvalLogger] Wrote {self._count} records → {self._path}")

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
