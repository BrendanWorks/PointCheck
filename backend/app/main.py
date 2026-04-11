"""
MolmoAccess Agent — FastAPI backend

Endpoints:
  POST /api/crawl              Create a crawl job, return job_id
  GET  /api/crawl/{job_id}     Get job status / completed report
  GET  /api/crawls             List all jobs (summary)
  WS   /ws/crawl/{job_id}      Stream live progress events
  GET  /health                 Liveness check

WebSocket event types emitted (backward-compatible with PointCheck v1 frontend):
  status          — free-form progress message
  page_start      — BFS navigated to a new page
  test_start      — individual WCAG check beginning
  progress        — check sub-step message
  result          — individual TestResult (includes screenshot_b64)
  test_complete   — individual check finished
  page_done       — all checks finished for one page
  crawl_done      — (internal, consumed in WS handler)
  done            — final report (screenshot_b64 stripped)
  error           — fatal error

Models are loaded lazily on first WS connection and cached globally.
On Modal A10G (24GB VRAM):
  MolmoWeb-8B  4-bit NF4  ~4GB
  OLMo 3       bfloat16   ~14GB  (or 4-bit ~4GB)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.schemas import CrawlRequest, CrawlResponse, CrawlJobState, ALL_TESTS
from app.models.molmo2 import MolmoWebAnalyzer
from app.models.olmo3 import OLMo3Narrator
from app.crawler import SiteCrawler
from app.eval_logger import EvalLogger
from app.report_generator import build_site_report, strip_b64


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="MolmoAccess Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCREENSHOTS_DIR = Path(__file__).parents[1] / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")


# ── Global model singletons (lazy-loaded on first WS connection) ───────────────

_analyzer: Optional[MolmoWebAnalyzer] = None
_narrator: Optional[OLMo3Narrator]    = None
_model_lock = asyncio.Lock()

# In-memory job store (replace with Redis/DB for production)
_jobs: dict[str, CrawlJobState] = {}


async def _ensure_models() -> tuple[MolmoWebAnalyzer, OLMo3Narrator]:
    """Load both models once and cache globally. Thread-safe via asyncio.Lock."""
    global _analyzer, _narrator
    async with _model_lock:
        if _analyzer is None:
            _analyzer = await asyncio.get_event_loop().run_in_executor(
                None, lambda: MolmoWebAnalyzer(use_quantization=True)
            )
        if _narrator is None:
            _narrator = await asyncio.get_event_loop().run_in_executor(
                None, lambda: OLMo3Narrator()
            )
    return _analyzer, _narrator


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "models_loaded": _analyzer is not None and _narrator is not None,
        "jobs": len(_jobs),
    }


@app.post("/api/crawl", response_model=CrawlResponse)
async def create_crawl(req: CrawlRequest):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = CrawlJobState(
        job_id=job_id,
        url=req.url,
        wcag_version=req.wcag_version,
        max_pages=req.max_pages,
        max_depth=req.max_depth,
        tests=req.tests,
        created_at=datetime.utcnow().isoformat(),
    )
    return CrawlResponse(
        job_id=job_id,
        message="Job created. Connect to /ws/crawl/{job_id} to start.",
    )


@app.get("/api/crawl/{job_id}")
async def get_crawl(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    job = _jobs[job_id]
    return job.model_dump()


@app.get("/api/crawls")
async def list_crawls():
    return [
        {
            "job_id":        j.job_id,
            "url":           j.url,
            "status":        j.status,
            "created_at":    j.created_at,
            "pages_scanned": j.pages_scanned,
        }
        for j in _jobs.values()
    ]


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws/crawl/{job_id}")
async def ws_crawl(ws: WebSocket, job_id: str):
    await ws.accept()

    if job_id not in _jobs:
        await ws.send_json({"type": "error", "message": "Job not found"})
        await ws.close()
        return

    job = _jobs[job_id]
    if job.status not in ("queued", "error"):
        await ws.send_json({"type": "error", "message": f"Job is already {job.status}"})
        await ws.close()
        return

    job.status = "running"

    async def send(msg: dict) -> None:
        try:
            await ws.send_json(msg)
        except Exception:
            pass

    try:
        # ── Load models ───────────────────────────────────────────────────
        await send({"type": "status", "message": "Loading MolmoWeb-8B (visual analyzer)..."})
        analyzer, narrator = await _ensure_models()
        await send({"type": "status", "message": "Models ready. Starting crawler..."})

        # ── Set up directories ────────────────────────────────────────────
        job_screenshots = SCREENSHOTS_DIR / job_id
        job_screenshots.mkdir(exist_ok=True)

        # ── Eval logger ───────────────────────────────────────────────────
        eval_logger = EvalLogger(job_id=job_id)

        # ── BFS crawl ─────────────────────────────────────────────────────
        crawler = SiteCrawler(
            start_url=job.url,
            analyzer=analyzer,
            screenshots_dir=job_screenshots,
            wcag_version=job.wcag_version,
            max_pages=job.max_pages,
            max_depth=job.max_depth,
            tests=job.tests,
            eval_logger=eval_logger,
        )

        page_reports: list[dict] = []

        async for event in crawler.crawl():
            if event["type"] == "crawl_done":
                page_reports = event["page_reports"]
                job.pages_scanned = event["pages_scanned"]
                # Don't forward raw crawl_done — we send `done` instead
                continue

            if event["type"] == "page_done":
                job.pages_scanned += 1
                page_reports.append(event["page_report"])
                # Forward page_done without b64 to keep frames small
                await send({**event, "page_report": strip_b64(event["page_report"])})
                continue

            if event["type"] == "result":
                job.page_results.append(event["data"])
                await send(event)  # individual results include b64
                continue

            await send(event)

        eval_logger.close()

        # ── Narrative ─────────────────────────────────────────────────────
        await send({"type": "status", "message": "Generating accessibility narrative with OLMo 3..."})
        narrative = await narrator.generate_narrative(
            all_results=job.page_results,
            site_url=job.url,
            pages_scanned=job.pages_scanned,
        )
        job.narrative = narrative

        # ── Final report ──────────────────────────────────────────────────
        report = build_site_report(
            job_id=job_id,
            site_url=job.url,
            wcag_version=job.wcag_version,
            narrative=narrative,
            page_reports=page_reports,
            tests_run=job.tests,
        )
        job.report = report
        job.status = "complete"
        job.completed_at = datetime.utcnow().isoformat()

        await send({"type": "done", "job_id": job_id, "report": strip_b64(report)})

    except WebSocketDisconnect:
        job.status = "disconnected"
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[WS error] job={job_id}\n{tb}")
        job.status = "error"
        job.error  = str(e)
        try:
            await send({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ── Backward-compatible single-page endpoint (PointCheck v1 API) ──────────────
# Accepts the old /api/run shape so the existing frontend still works
# while the new /api/crawl + /ws/crawl endpoints are being wired up.

from fastapi import Request

@app.post("/api/run")
async def legacy_run(request: Request):
    """
    Shim: maps old { url, tests, wcag_version } → new CrawlRequest.
    Returns the same job_id + WebSocket path shape so the v1 frontend
    can connect to /ws/crawl/{job_id} without modification.
    """
    body = await request.json()
    crawl_req = CrawlRequest(
        url=body.get("url", ""),
        wcag_version=body.get("wcag_version", "2.2"),
        max_pages=1,    # single-page mode for v1 compatibility
        max_depth=0,
        tests=body.get("tests", ALL_TESTS),
    )
    resp = await create_crawl(crawl_req)
    return {"run_id": resp.job_id, "message": resp.message}


@app.websocket("/ws/{job_id}")
async def legacy_ws(ws: WebSocket, job_id: str):
    """Legacy WebSocket path redirect — maps /ws/{id} → /ws/crawl/{id} logic."""
    await ws_crawl(ws, job_id)
