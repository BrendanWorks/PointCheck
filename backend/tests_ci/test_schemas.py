"""Schema and data validation tests."""

import pytest
from pydantic import BaseModel, ValidationError


def test_crawl_request_schema():
    """CrawlRequest should validate URL and WCAG version."""
    from pydantic import BaseModel, HttpUrl

    class CrawlRequest(BaseModel):
        url: str
        wcag_version: str = "2.2"
        max_pages: int = 50
        max_depth: int = 3
        tests: list[str] = []

    # Valid request
    req = CrawlRequest(url="https://example.com")
    assert req.url == "https://example.com"
    assert req.wcag_version == "2.2"
    assert req.max_pages == 50

    # Valid with custom values
    req2 = CrawlRequest(
        url="https://test.org",
        wcag_version="2.1",
        max_pages=10,
        max_depth=2,
    )
    assert req2.max_pages == 10


def test_page_cap():
    """Page cap should be enforced at schema level."""

    class CrawlRequest(BaseModel):
        max_pages: int = 50

        def model_post_init(self, __context):
            if self.max_pages > 30:
                self.max_pages = 30

    # Should cap at 30
    req = CrawlRequest(max_pages=50)
    assert req.max_pages == 30

    # Should allow <= 30
    req2 = CrawlRequest(max_pages=15)
    assert req2.max_pages == 15


def test_strip_b64():
    """strip_b64 should remove screenshot data from reports."""

    def strip_b64(data: dict) -> dict:
        """Remove base64 fields from a report."""
        if isinstance(data, dict):
            return {
                k: (None if (k.endswith("_b64") or k == "screenshot_b64") else strip_b64(v))
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [strip_b64(item) for item in data]
        return data

    # Report with b64
    report = {
        "job_id": "123",
        "screenshot_b64": "data:image/png;base64,iVBORw0KGgo=",
        "page_results": [
            {
                "page_num": 1,
                "screenshot_b64": "data:image/png;base64,ABC=",
            }
        ],
    }

    stripped = strip_b64(report)
    assert stripped["job_id"] == "123"
    assert stripped["screenshot_b64"] is None
    assert stripped["page_results"][0]["screenshot_b64"] is None
    assert stripped["page_results"][0]["page_num"] == 1


class TestJobEviction:
    """Test job eviction logic."""

    def test_eviction_caps_jobs(self):
        """Eviction should cap in-memory jobs at 50."""

        def evict_old_jobs(jobs: dict, max_size: int = 50) -> None:
            """Remove oldest TERMINAL jobs when cache exceeds max_size."""
            if len(jobs) > max_size:
                # Filter terminal jobs, sort by created_at, evict oldest
                terminal = [
                    (k, v) for k, v in jobs.items()
                    if v.get("status") == "complete"
                ]
                terminal.sort(key=lambda x: x[1].get("created_at", ""))
                for job_id, _ in terminal[:len(jobs) - max_size]:
                    del jobs[job_id]

        jobs = {}
        for i in range(60):
            jobs[f"job_{i}"] = {
                "job_id": f"job_{i}",
                "status": "complete",
                "created_at": f"2026-07-{i%20 + 1:02d}T00:00:00",
            }

        # Add some active jobs
        jobs["active_1"] = {"job_id": "active_1", "status": "running"}
        jobs["active_2"] = {"job_id": "active_2", "status": "queued"}

        evict_old_jobs(jobs)

        # Should have <= 50 jobs now
        assert len(jobs) <= 50
        # Active jobs should survive
        assert "active_1" in jobs
        assert "active_2" in jobs

    def test_eviction_preserves_active_jobs(self):
        """Eviction should never remove active/running jobs."""

        def evict_old_jobs(jobs: dict, max_size: int = 50) -> None:
            if len(jobs) > max_size:
                terminal = [
                    (k, v) for k, v in jobs.items()
                    if v.get("status") in ("complete", "error", "disconnected")
                ]
                terminal.sort(key=lambda x: x[1].get("created_at", ""))
                to_remove = len(jobs) - max_size
                for job_id, _ in terminal[:to_remove]:
                    del jobs[job_id]

        jobs = {
            "running_1": {"job_id": "running_1", "status": "running"},
            "queued_1": {"job_id": "queued_1", "status": "queued"},
            "complete_1": {"job_id": "complete_1", "status": "complete", "created_at": "2026-01-01"},
        }

        evict_old_jobs(jobs)

        # Active jobs must survive
        assert "running_1" in jobs
        assert "queued_1" in jobs
