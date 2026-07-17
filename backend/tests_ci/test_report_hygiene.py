"""strip_b64 — the persist-hygiene guard. If this stops removing screenshot
base64, persisted Dict values can balloon past Modal's size limit and silently
break permalinks."""

from app.report_generator import strip_b64


def test_removes_b64_everywhere_keeps_everything_else():
    payload = {
        "status": "complete",
        "page_results": [
            {"test_id": "zoom", "screenshot_b64": "AAAA",
             "screenshot_path": "/screenshots/x/z.png", "result": "fail"},
        ],
        "report": {
            "test_summaries": [
                {"test_id": "zoom", "screenshot_b64": "BBBB",
                 "screenshot_path": "/screenshots/x/z.png"},
            ],
        },
    }
    out = strip_b64(payload)
    blob = str(out)
    assert "AAAA" not in blob and "BBBB" not in blob, "b64 leaked"
    # everything except screenshot_b64 survives
    assert out["status"] == "complete"
    assert out["page_results"][0]["result"] == "fail"
    assert out["page_results"][0]["screenshot_path"] == "/screenshots/x/z.png"
    assert out["report"]["test_summaries"][0]["screenshot_path"] == "/screenshots/x/z.png"
    assert "screenshot_b64" not in out["page_results"][0]
    assert "screenshot_b64" not in out["report"]["test_summaries"][0]


def test_handles_nested_lists_and_scalars():
    assert strip_b64([{"screenshot_b64": "x", "k": 1}, {"k": 2}]) == [{"k": 1}, {"k": 2}]
    assert strip_b64("plain") == "plain"
    assert strip_b64(42) == 42
    assert strip_b64(None) is None


def test_noop_when_no_b64():
    payload = {"a": 1, "b": [{"c": 2}]}
    assert strip_b64(payload) == payload
