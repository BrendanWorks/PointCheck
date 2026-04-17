#!/usr/bin/env python3
"""
Quick diagnostic: runs ONE case and prints every WebSocket event received.
Usage:
  python debug_scan.py [gds|discord|medium] [--prod]
"""
import argparse
import asyncio
import json
import sys
import time
import urllib.request

import websockets

STAGING_URL = "https://brendanworks-staging--wcag-tester-web.modal.run"
PROD_URL    = "https://brendanworks--wcag-tester-web.modal.run"

CASES = {
    "gds": {
        "label": "GDS Accessibility Audit page",
        "url":   "https://alphagov.github.io/accessibility-tool-audit/test-cases.html",
        "tests": ["keyboard_nav", "color_blindness", "focus_indicator",
                  "form_errors", "page_structure"],
        "wcag":  "2.1",
    },
    "discord": {
        "label": "discord.com",
        "url":   "https://discord.com",
        "tests": ["page_structure"],
        "wcag":  "2.1",
    },
    "medium": {
        "label": "medium.com",
        "url":   "https://medium.com",
        "tests": ["page_structure"],
        "wcag":  "2.1",
    },
}


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def debug_run(base_url: str, case: dict):
    ws_base = base_url.replace("https://", "wss://")

    resp = post_json(
        f"{base_url}/api/run",
        {
            "url":          case["url"],
            "tests":        case["tests"],
            "task":         "Navigate and use the main features of this website",
            "wcag_version": case["wcag"],
        },
    )
    run_id = resp.get("run_id") or resp.get("job_id")
    if not run_id:
        print(f"[ERR] No run_id in response: {resp}")
        return

    ws_url = f"{ws_base}/ws/{run_id}"
    print(f"\n{'─'*64}")
    print(f"  Case  : {case['label']}")
    print(f"  URL   : {case['url']}")
    print(f"  WS    : {ws_url}")
    print(f"{'─'*64}")

    t0 = time.time()
    event_count = 0

    try:
        async with websockets.connect(ws_url, open_timeout=30, ping_timeout=60) as ws:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=420)
                except asyncio.TimeoutError:
                    print(f"\n[TIMEOUT] No message for 420s — aborting.")
                    break
                msg = json.loads(raw)
                event_count += 1
                elapsed = round(time.time() - t0)

                mtype = msg.get("type", "?")

                # Compact printing — show type + key fields
                if mtype == "status":
                    print(f"  [{elapsed:>4}s] STATUS    {msg.get('message', '')[:100]}")
                elif mtype == "page_start":
                    print(f"  [{elapsed:>4}s] PAGE_START {msg.get('url', '')}")
                elif mtype == "page_error":
                    err = (msg.get("error") or msg.get("message", ""))[:120]
                    print(f"  [{elapsed:>4}s] PAGE_ERROR ⛔ {err}")
                elif mtype == "test_start":
                    print(f"  [{elapsed:>4}s] TEST_START [{msg.get('test')}] {msg.get('test_name','')}")
                elif mtype == "progress":
                    print(f"  [{elapsed:>4}s] PROGRESS  [{msg.get('test','')}] {msg.get('message','')[:80]}")
                elif mtype == "result":
                    d = msg.get("data", {})
                    print(f"  [{elapsed:>4}s] RESULT    [{d.get('test_id')}] {d.get('result','?').upper()} — {d.get('summary','')[:60]}")
                elif mtype == "test_complete":
                    print(f"  [{elapsed:>4}s] TEST_DONE [{msg.get('test')}]")
                elif mtype == "page_done":
                    pr = msg.get("page_report", {})
                    s = pr.get("summary", {})
                    print(f"  [{elapsed:>4}s] PAGE_DONE  pass={s.get('passed')} fail={s.get('failed')} warn={s.get('warnings')}")
                elif mtype == "done":
                    r = msg.get("report", {})
                    summ = r.get("summary", {})
                    print(f"  [{elapsed:>4}s] DONE      pages={r.get('pages_scanned')} pass={summ.get('passed')} fail={summ.get('failed')} narrative_len={len(r.get('narrative',''))}")
                    break
                elif mtype == "error":
                    print(f"  [{elapsed:>4}s] ERROR ❌  {msg.get('message','')[:120]}")
                    print(f"\n  Full error event: {json.dumps(msg)[:500]}")
                    break
                else:
                    print(f"  [{elapsed:>4}s] {mtype.upper():<12} {str(msg)[:80]}")

    except Exception as exc:
        print(f"\n[WS EXCEPTION] {exc}")

    total = round(time.time() - t0)
    print(f"\n  Total: {total}s, {event_count} events received")


async def main(base_url: str, case_key: str):
    if case_key not in CASES:
        print(f"Unknown case '{case_key}'. Choose: {', '.join(CASES)}")
        sys.exit(1)
    await debug_run(base_url, CASES[case_key])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", nargs="?", default="gds",
                        choices=list(CASES), help="Which case to debug")
    parser.add_argument("--prod", action="store_true")
    args = parser.parse_args()
    base = PROD_URL if args.prod else STAGING_URL
    asyncio.run(main(base, args.case))
