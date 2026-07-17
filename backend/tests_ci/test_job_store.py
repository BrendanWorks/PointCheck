"""Rate limiter (sliding window) and job eviction — the two in-memory
protections extracted from main.py so CI can cover them."""

from collections import deque

from app.job_store import (
    TERMINAL_STATUSES,
    rate_limit_allow,
    select_evictable,
)


# ── rate limiter ──────────────────────────────────────────────────────────

def test_rate_limit_allows_up_to_cap_then_blocks():
    bucket = deque()
    # 8 allowed, 9th blocked, all within the same window (now = 0)
    for i in range(8):
        assert rate_limit_allow(bucket, now=0.0, max_scans=8, window_s=600) is True, i
    assert rate_limit_allow(bucket, now=0.0, max_scans=8, window_s=600) is False


def test_rate_limit_window_expiry_frees_slots():
    bucket = deque()
    for _ in range(8):
        rate_limit_allow(bucket, now=0.0, max_scans=8, window_s=600)
    # still blocked just inside the window
    assert rate_limit_allow(bucket, now=599.0, max_scans=8, window_s=600) is False
    # once the old timestamps age out past the window, allowed again
    assert rate_limit_allow(bucket, now=601.0, max_scans=8, window_s=600) is True


def test_rate_limit_blocked_request_not_recorded():
    bucket = deque()
    for _ in range(8):
        rate_limit_allow(bucket, now=0.0, max_scans=8, window_s=600)
    assert rate_limit_allow(bucket, now=0.0, max_scans=8, window_s=600) is False
    # the blocked attempt must not have consumed a slot / grown the bucket
    assert len(bucket) == 8


# ── eviction ──────────────────────────────────────────────────────────────

def _statuses(*pairs):
    return list(pairs)


def test_no_eviction_under_cap():
    items = _statuses(("a", "complete"), ("b", "running"))
    assert select_evictable(items, cap=5, terminal=TERMINAL_STATUSES) == []


def test_evicts_oldest_terminal_first():
    # 4 terminal (oldest) + 3 active, cap 5 -> drop 2 oldest terminal
    items = _statuses(
        ("t0", "complete"), ("t1", "error"), ("t2", "complete"), ("t3", "disconnected"),
        ("a0", "running"), ("a1", "queued"), ("a2", "running"),
    )
    assert select_evictable(items, cap=5, terminal=TERMINAL_STATUSES) == ["t0", "t1"]


def test_never_evicts_active_even_over_cap():
    items = _statuses(*[(f"a{i}", "running") for i in range(8)])
    # 8 active, cap 5, but none are terminal -> nothing evictable
    assert select_evictable(items, cap=5, terminal=TERMINAL_STATUSES) == []


def test_evicts_only_terminal_skipping_interleaved_active():
    items = _statuses(
        ("t0", "complete"), ("a0", "running"), ("t1", "complete"),
        ("a1", "running"), ("t2", "error"), ("a2", "running"),
    )
    # 6 items, cap 4 -> need to drop 2, only terminal are eligible, oldest first
    assert select_evictable(items, cap=4, terminal=TERMINAL_STATUSES) == ["t0", "t1"]
