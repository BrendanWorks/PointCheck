"""
MolmoAccess Agent — FastAPI backend

Endpoints:
  POST /api/crawl              Create a crawl job, return job_id
  GET  /api/crawl/{job_id}     Get job status / completed report
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

Model residency on Modal A100-40GB (42.4 GB VRAM):
  MolmoWeb-8B  bfloat16  ~16 GB  — pointing + agent navigation
  MolmoQA-7B   4-bit NF4  ~4 GB  — screenshot description QA
  Both load once per container (module-level cache) and stay resident
  (~20 GB, ~22 GB headroom) — warm scans skip the 60-90 s load entirely.

  OLMo-3-7B (narrative) is NEVER loaded in this container. It runs in the
  separate `narrate` Modal function (see modal_app.py) on its own
  scale-to-zero GPU, invoked remotely after the visual checks finish.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.schemas import CrawlRequest, CrawlResponse, CrawlJobState, ALL_TESTS
from app.models.molmo2 import MolmoWebAnalyzer
from app.crawler import SiteCrawler
from app.eval_logger import EvalLogger
from app.report_generator import build_site_report, strip_b64
from app.url_guard import url_block_reason


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="MolmoAccess Agent", version="1.0.0")

# Browser origins allowed to call the API. curl / server-side callers bypass
# CORS entirely — the rate limiter below is the actual abuse control; this
# just stops third-party webpages from triggering GPU scans via visitors'
# browsers.
ALLOWED_ORIGINS = [
    "https://pointcheck.org",
    "https://www.pointcheck.org",
    "http://localhost:3000",   # local frontend dev
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCREENSHOTS_DIR = Path(__file__).parents[1] / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")


# In-memory job store — tracks active + recently completed jobs within this container.
_jobs: dict[str, CrawlJobState] = {}

# ── Per-IP rate limiting ──────────────────────────────────────────────────────
# Each scan costs minutes of A100 time, so job creation is rate-limited.
# In-memory and per-container (Modal may run several containers), so this is
# burst control per IP, not a global cap — the hard spend ceiling is
# max_containers in modal_app.py.
# Sized so the 6-case regression suite plus a manual retry fits in one window.
_RATE_LIMIT_MAX_SCANS = 8
_RATE_LIMIT_WINDOW_S = 600
_rate_buckets: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request) -> None:
    """Raise 429 if this IP has created too many jobs in the current window."""
    ip = _client_ip(request)
    now = time.monotonic()
    bucket = _rate_buckets[ip]
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX_SCANS:
        raise HTTPException(
            429,
            f"Rate limit exceeded — max {_RATE_LIMIT_MAX_SCANS} scans per "
            f"{_RATE_LIMIT_WINDOW_S // 60} minutes. Please try again later.",
        )
    bucket.append(now)
    # Drop stale IP buckets so the map can't grow unbounded in a warm container
    if len(_rate_buckets) > 1000:
        stale = [
            k for k, v in _rate_buckets.items()
            if not v or now - v[-1] > _RATE_LIMIT_WINDOW_S
        ]
        for k in stale:
            del _rate_buckets[k]

# Serialise scans so only one model-load phase runs at a time.
_scan_lock = asyncio.Lock()

# Module-level analyzer cache — MolmoWeb-8B + Molmo-7B-D QA (~20 GB) load once
# per container and stay resident across scans. Only touched under _scan_lock.
_analyzer: Optional[MolmoWebAnalyzer] = None

# ── Persistent job store (Modal Dict) ─────────────────────────────────────────
# Jobs are written here at every status transition (queued → running →
# complete/error) for two reasons:
#   1. Permalinks survive container restarts (completed jobs).
#   2. Container affinity: Modal can route the POST /api/crawl and the
#      follow-up WebSocket to DIFFERENT containers once it scales out. The WS
#      handler hydrates queued jobs from this store when they aren't in local
#      memory, so the scan starts regardless of which container got the POST.
# Screenshots are stripped before writing (see _persist_job) to keep values
# well under Modal's per-value size limit. Dict name is read from
# MODAL_JOBS_DICT env var; Modal's --env flag isolates staging and prod into
# separate namespaces, so they never share state. Falls back to no-op when
# running locally (modal package unavailable or no auth).

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


# Keep at most this many jobs in local memory. Terminal jobs beyond the cap
# are evicted (they live in the Modal Dict, so get_crawl/hydrate still find
# them); active jobs are never evicted. Bounds growth in warm containers,
# which now live much longer since the visual models stay resident.
_MAX_JOBS_IN_MEMORY = 50
_TERMINAL_STATUSES = ("complete", "error", "disconnected")


def _persist_job(job: CrawlJobState) -> None:
    """Write a job's current state to the persistent store. Fire-and-forget; never raises.

    Screenshots (screenshot_b64) are stripped before writing: a multi-page
    scan's base64 frames can push a single Dict value past Modal's size limit,
    which would make the persist throw and silently break the permalink. Live
    scans stream b64 over the WebSocket, and same-container permalinks read the
    in-memory copy (which keeps b64), so this only affects permalinks opened
    after a container recycle — those load the full report minus thumbnails.
    """
    store = _get_modal_store()
    if store is None:
        return
    try:
        store[job.job_id] = strip_b64(job.model_dump())
    except Exception as exc:
        print(f"[jobs] Failed to persist job {job.job_id}: {exc}")


def _evict_old_jobs() -> None:
    """Drop the oldest terminal jobs from memory once over the cap.

    Safe because terminal jobs are already persisted to the Modal Dict.
    Active (queued/running) jobs are never evicted. Dict preserves insertion
    order, so iterating yields oldest-first.
    """
    if len(_jobs) <= _MAX_JOBS_IN_MEMORY:
        return
    removable = [
        jid for jid, j in _jobs.items() if j.status in _TERMINAL_STATUSES
    ]
    for jid in removable[: len(_jobs) - _MAX_JOBS_IN_MEMORY]:
        _jobs.pop(jid, None)


def _hydrate_job(job_id: str) -> Optional[CrawlJobState]:
    """Fetch a job from the persistent store (created on another container)."""
    store = _get_modal_store()
    if store is None:
        return None
    try:
        return CrawlJobState(**store[job_id])
    except KeyError:
        return None
    except Exception as exc:
        print(f"[jobs] Failed to hydrate job {job_id}: {exc}")
        return None


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "jobs": len(_jobs),
    }


@app.post("/api/crawl", response_model=CrawlResponse)
async def create_crawl(req: CrawlRequest, request: Request):
    _enforce_rate_limit(request)

    # SSRF guard — refuse URLs that resolve to private/internal addresses.
    # getaddrinfo blocks on DNS, so run it off the event loop.
    block_reason = await asyncio.get_event_loop().run_in_executor(
        None, url_block_reason, req.url
    )
    if block_reason:
        raise HTTPException(400, f"URL refused: {block_reason}")

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
    # Persist immediately so the WebSocket can pick this job up even if Modal
    # routes it to a different container than the one that took this POST.
    _persist_job(_jobs[job_id])
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


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws/crawl/{job_id}")
async def ws_crawl(ws: WebSocket, job_id: str):
    await ws.accept()

    job = _jobs.get(job_id)
    if job is None:
        # The POST may have landed on a different container — check the store.
        job = _hydrate_job(job_id)
        if job is not None:
            _jobs[job_id] = job

    if job is None:
        await ws.send_json({"type": "error", "message": "Job not found"})
        await ws.close()
        return

    if job.status not in ("queued", "error"):
        await ws.send_json({"type": "error", "message": f"Job is already {job.status}"})
        await ws.close()
        return

    job.status = "running"
    # Mark running in the store so a second WS to another container can't
    # hydrate the same queued job and start a duplicate scan.
    _persist_job(job)

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

            # ── Visual models: load once per container, reuse across scans ──
            global _analyzer
            if _analyzer is None:
                await send({"type": "status", "message": "Loading MolmoWeb-8B (visual analyzer)..."})
                _analyzer = await loop.run_in_executor(
                    None, lambda: MolmoWebAnalyzer(use_quantization=False)
                )
                await send({"type": "status", "message": "MolmoWeb-8B ready. Starting visual checks..."})
            else:
                await send({"type": "status", "message": "MolmoWeb-8B already warm — starting visual checks..."})
            analyzer = _analyzer

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

            # Free per-scan objects (browser/crawler state), but keep the
            # analyzer resident for the next scan. empty_cache() releases
            # activation memory back to the CUDA pool between scans.
            del crawler
            import gc as _gc
            _gc.collect()
            import torch as _torch
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()

            # ── Narrative: remote OLMo-3 call (separate Modal function) ─────
            # Runs on its own scale-to-zero GPU (see modal_app.py `narrate`)
            # so this container never unloads MolmoWeb. Skip if no pages were
            # scanned — a narrative over zero results is misleading.
            narrative = ""
            olmo_inference_stats: dict | None = None
            if job.pages_scanned == 0:
                await send({
                    "type": "status",
                    "message": "No pages were scanned — skipping narrative generation.",
                })
            else:
                await send({"type": "status", "message": "Visual checks done. Generating OLMo-3 narrative..."})
                # Best-effort — if the remote call fails we still deliver a
                # complete report with the visual check results.
                try:
                    import modal as _modal
                    narrate_fn = _modal.Function.from_name("wcag-tester", "narrate")
                    # Strip screenshots — the narrator only reads text fields,
                    # and b64 payloads would bloat the remote call.
                    narrate_result = await narrate_fn.remote.aio(
                        all_results=strip_b64(job.page_results),
                        site_url=job.url,
                        pages_scanned=job.pages_scanned,
                    )
                    narrative = narrate_result.get("narrative", "")
                    olmo_inference_stats = narrate_result.get("stats")
                except Exception as _olmo_err:
                    import traceback as _tb
                    print(f"[OLMo3] Remote narrate failed (non-fatal): {_olmo_err}\n{_tb.format_exc()}")
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
            _persist_job(job)
            _evict_old_jobs()
            _ka_stop[0] = True
            keepalive_task.cancel()
            await send({"type": "done", "job_id": job_id, "report": strip_b64(report)})

    except WebSocketDisconnect:
        _ka_stop[0] = True
        keepalive_task.cancel()
        job.status = "disconnected"
        _persist_job(job)
        _evict_old_jobs()
    except Exception as e:
        _ka_stop[0] = True
        keepalive_task.cancel()
        import traceback
        tb = traceback.format_exc()
        print(f"[WS error] job={job_id}\n{tb}")
        job.status = "error"
        job.error  = str(e)
        _persist_job(job)
        _evict_old_jobs()
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
    resp = await create_crawl(crawl_req, request)
    return {"run_id": resp.job_id, "message": resp.message}


@app.websocket("/ws/{job_id}")
async def legacy_ws(ws: WebSocket, job_id: str):
    """Legacy WebSocket path redirect — maps /ws/{id} → /ws/crawl/{id} logic."""
    await ws_crawl(ws, job_id)
