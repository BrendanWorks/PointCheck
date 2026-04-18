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

Two-phase sequential model residency on Modal A100-40GB (42.4 GB VRAM):
  Phase 1 (visual checks):
    MolmoWeb-8B  bfloat16  ~16 GB  — pointing + agent navigation
    MolmoQA-7B   4-bit NF4  ~4 GB  — screenshot description QA
    Total Phase 1: ~20 GB, leaving ~22 GB headroom.
    OLMo is NOT loaded during Phase 1.

  Phase 2 (narrative):
    MolmoWeb + MolmoQA freed (gc.collect + cuda.empty_cache + synchronize).
    OLMo-3-7B  bfloat16  ~14 GB  — executive summary narrative.
    Fits comfortably with ~28 GB free after Phase 1 teardown.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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


# In-memory job store — tracks active + recently completed jobs within this container.
_jobs: dict[str, CrawlJobState] = {}

# Serialise scans so only one model-load phase runs at a time.
_scan_lock = asyncio.Lock()

# ── Persistent job store (Modal Dict) ─────────────────────────────────────────
# Completed jobs are written here so permalinks survive container restarts.
# Dict name is read from MODAL_JOBS_DICT env var; Modal's --env flag isolates
# staging and prod into separate namespaces, so they never share state.
# Falls back to no-op when running locally (modal package unavailable or no auth).

_MODAL_DICT_NAME: str = os.environ.get("MODAL_JOBS_DICT", "pointcheck-jobs")
_modal_store: Any = None          # modal.Dict handle once initialised
_modal_store_ready: bool | None = None  # None = not tried yet


def _get_modal_store() -> Any | None:
    """Return the Modal Dict handle, or None if unavailable."""
    global _modal_store, _modal_store_ready
    if _modal_store_ready is None:
        try:
            import modal as _modal
            _modal_store = _modal.Dict.from_name(_MODAL_DICT_NAME, create_if_missing=True)
            _modal_store_ready = True
            print(f"[jobs] Modal Dict '{_MODAL_DICT_NAME}' ready — permalinks will persist.")
        except Exception as exc:
            _modal_store_ready = False
            print(f"[jobs] Modal Dict unavailable, using in-memory only: {exc}")
    return _modal_store if _modal_store_ready else None


def _persist_completed_job(job: CrawlJobState) -> None:
    """Write a completed job to the persistent store. Fire-and-forget; never raises."""
    store = _get_modal_store()
    if store is None:
        return
    try:
        store[job.job_id] = job.model_dump()
    except Exception as exc:
        print(f"[jobs] Failed to persist job {job.job_id}: {exc}")


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
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
    # Check in-memory first (active / recently completed in this container)
    if job_id in _jobs:
        return _jobs[job_id].model_dump()
    # Fall back to persistent store (survives container restarts)
    store = _get_modal_store()
    if store is not None:
        try:
            data = store[job_id]
            return data
        except KeyError:
            pass
    raise HTTPException(404, "Job not found")


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

    # ── Keepalive task ────────────────────────────────────────────────────────
    # Modal's load balancer silently drops WebSocket connections after ~45 s of
    # inactivity.  Model loading (Phase 1 + Phase 2) can each take 60–90 s with
    # no application messages.  We send a heartbeat every 20 s throughout the
    # scan so the connection stays alive.
    _ka_stop = [False]   # mutable cell so the coroutine always sees current value
    async def _keepalive():
        elapsed = 0
        while not _ka_stop[0]:
            await asyncio.sleep(20)
            if _ka_stop[0]:
                break
            elapsed += 20
            try:
                await ws.send_json({"type": "status", "message": f"⏳ Still working… ({elapsed}s elapsed)"})
            except Exception:
                break

    keepalive_task = asyncio.create_task(_keepalive())

    try:
        # Tell the client we received their job before we compete for the lock
        await send({"type": "status", "message": "Job queued — waiting for GPU…"})

        async with _scan_lock:

            loop = asyncio.get_event_loop()

            # ── Phase 1: MolmoWeb-8B bfloat16 (~16 GB) ───────────────────────
            # OLMo is NOT loaded. MolmoWeb alone fits in A10G 24 GB.
            await send({"type": "status", "message": "Loading MolmoWeb-8B (visual analyzer)..."})
            analyzer = await loop.run_in_executor(
                None, lambda: MolmoWebAnalyzer(use_quantization=False)
            )
            await send({"type": "status", "message": "MolmoWeb-8B ready. Starting visual checks..."})

            job_screenshots = SCREENSHOTS_DIR / job_id
            job_screenshots.mkdir(exist_ok=True)
            eval_logger = EvalLogger(job_id=job_id)

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
                    continue
                if event["type"] == "page_done":
                    job.pages_scanned += 1
                    page_reports.append(event["page_report"])
                    await send({**event, "page_report": strip_b64(event["page_report"])})
                    continue
                if event["type"] == "result":
                    job.page_results.append(event["data"])
                    await send(event)
                    continue
                await send(event)

            eval_logger.close()

            # ── Free MolmoWeb, then load OLMo ────────────────────────────────
            # Sequential residency — never both models in VRAM at once.
            # gc.collect() must run before empty_cache() so Python finalizers
            # release CUDA tensors; synchronize() drains pending CUDA ops.
            del crawler, analyzer
            import gc as _gc
            _gc.collect()
            import torch as _torch
            if _torch.cuda.is_available():
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
            # ── Phase 2: OLMo-3-7B bfloat16 (~14 GB) ────────────────────────
            # Skip entirely if no pages were scanned — there is nothing to
            # summarise and loading a 14 GB model to say "no results" wastes
            # ~60 s and produces a misleading narrative.
            narrative = ""
            olmo_inference_stats: dict | None = None
            if job.pages_scanned == 0:
                await send({
                    "type": "status",
                    "message": "No pages were scanned — skipping narrative generation.",
                })
            else:
                await send({"type": "status", "message": "Visual checks done. Loading OLMo-3-7B for narrative..."})
                # 4-bit NF4 is NOT used — bitsandbytes tries to overwrite a
                # read-only property in OLMo-3's architecture → "property of
                # Olmo3Model object has no setter".  bfloat16 fits on the A100
                # (~14 GB) with ~28 GB of freed VRAM available after Phase 1.
                # Wrapped in try/except — if OLMo fails to load (e.g. fragmented
                # VRAM on a warm container), we still deliver a complete report
                # with the visual check results. The narrative is best-effort.
                try:
                    narrator = await loop.run_in_executor(None, OLMo3Narrator)
                    narrative = await narrator.generate_narrative(
                        all_results=job.page_results,
                        site_url=job.url,
                        pages_scanned=job.pages_scanned,
                    )
                    olmo_inference_stats = narrator.last_inference_stats
                    del narrator
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                except Exception as _olmo_err:
                    import traceback as _tb
                    print(f"[OLMo3] Load/generate failed (non-fatal): {_olmo_err}\n{_tb.format_exc()}")
                    await send({"type": "status", "message": "Narrative generation unavailable — delivering visual results."})
            job.narrative = narrative

            # ── Final report ──────────────────────────────────────────────────
            report = build_site_report(
                job_id=job_id,
                site_url=job.url,
                wcag_version=job.wcag_version,
                narrative=narrative,
                page_reports=page_reports,
                tests_run=job.tests,
                olmo_inference_stats=olmo_inference_stats,
            )
            job.report = report
            job.status = "complete"
            job.completed_at = datetime.utcnow().isoformat()
            # Persist to Modal Dict so this job is retrievable after container restarts
            _persist_completed_job(job)
            _ka_stop[0] = True
            keepalive_task.cancel()
            await send({"type": "done", "job_id": job_id, "report": strip_b64(report)})

    except WebSocketDisconnect:
        _ka_stop[0] = True
        keepalive_task.cancel()
        job.status = "disconnected"
    except Exception as e:
        _ka_stop[0] = True
        keepalive_task.cancel()
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
