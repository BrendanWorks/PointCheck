"""
Pure, dependency-free helpers for the in-memory job store and rate limiter.

Extracted from main.py so they can be unit-tested in CI without importing the
heavy inference stack (main.py pulls in torch via the model modules). These
functions hold the *algorithms*; main.py keeps the module-level state and the
FastAPI/HTTP wiring around them. Behaviour is identical to the inline versions
that shipped in the security + hygiene batches.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

# Policy defaults (main.py imports these so there is a single source of truth).
RATE_LIMIT_MAX_SCANS = 8
RATE_LIMIT_WINDOW_S = 600
MAX_JOBS_IN_MEMORY = 50
TERMINAL_STATUSES = ("complete", "error", "disconnected")


def rate_limit_allow(
    bucket: deque, now: float, max_scans: int, window_s: float
) -> bool:
    """Sliding-window per-IP rate check.

    `bucket` is this IP's deque of monotonic timestamps; it is mutated in
    place — timestamps older than the window are dropped, and `now` is
    appended only when the request is allowed. Returns True if allowed,
    False if the IP is over the cap for the current window.
    """
    while bucket and now - bucket[0] > window_s:
        bucket.popleft()
    if len(bucket) >= max_scans:
        return False
    bucket.append(now)
    return True


def select_evictable(
    job_statuses: Iterable[tuple[str, str]], cap: int, terminal: Iterable[str]
) -> list[str]:
    """Choose which jobs to drop from the in-memory store once over `cap`.

    `job_statuses` is an oldest-first iterable of (job_id, status). Only
    terminal jobs are evictable (they are persisted to the Modal Dict, so
    they remain retrievable); active jobs are never returned even when that
    leaves the store above `cap`. Returns the oldest terminal job_ids to
    remove, at most `len - cap` of them.
    """
    items = list(job_statuses)
    if len(items) <= cap:
        return []
    terminal_set = set(terminal)
    removable = [jid for jid, status in items if status in terminal_set]
    return removable[: len(items) - cap]
