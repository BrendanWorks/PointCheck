# PointCheck — Post-Launch Handoff
**Last updated: 2026-04-09**

## What This Is
PointCheck is a deployed WCAG 2.1 Level AA accessibility testing tool built as a portfolio piece for an Allen AI job application. Users paste a URL, select tests, and receive a detailed accessibility report with live streaming progress, Molmo2 visual focus confirmation, and an OLMo3-written executive summary.

| | |
|---|---|
| **Live site** | https://pointcheck.org |
| **Backend** | https://brendanworks--wcag-tester-web.modal.run |
| **GitHub** | https://github.com/BrendanWorks/PointCheck |
| **Stack** | Next.js 16 (Vercel) → FastAPI + WebSocket + Playwright + OLMo3-7B + Molmo2-4B (Modal A10G) |

---

## Architecture

```
┌─────────────────────────────────┐        ┌──────────────────────────────────────┐
│  Next.js 16 (Vercel)            │        │  FastAPI + Playwright (Modal A10G)   │
│                                 │        │                                      │
│  • URL input + test selector    │◄──WS──►│  • Runs 6 WCAG tests via Playwright  │
│  • Live progress stream         │        │  • OLMo3-7B  → executive narrative   │
│  • Results dashboard            │        │  • Molmo2-4B → visual pointer        │
│  • JSON / CSV export            │        │  • Streams events over WebSocket     │
└─────────────────────────────────┘        └──────────────────────────────────────┘
```

### Models
| Model | Role | Size |
|---|---|---|
| `allenai/Olmo-3-7B-Instruct` | Plain-English executive summary after all tests complete | ~14 GB bfloat16 |
| `allenai/Molmo2-4B` | Visual pointer — outputs `<point x="X" y="Y">` pixel coords from screenshots to confirm focus ring visibility | ~2 GB, 4-bit NF4 |

Both models are baked into the Modal container at build time via `setup_model.py` — cold starts don't re-download weights.

---

## Key Files

| File | Purpose |
|---|---|
| `modal_app.py` | Modal deployment — A10G GPU, 900s timeout, image build, runtime compat patches |
| `backend/main.py` | FastAPI app, WebSocket handler, TEST_MAP, URL normalization, `_strip_b64()` |
| `backend/wcag_agent.py` | OLMo3 (WCAGAgent) + Molmo2 (Molmo2Pointer) + ConsecutiveNewlineSuppressor |
| `backend/setup_model.py` | Modal image build — downloads both models, applies Molmo2 `cache_position` file patch |
| `backend/report_generator.py` | Aggregates per-test results → JSON report |
| `backend/tests/page_structure.py` | 1.1.1 · 1.3.1 · 1.4.1 · 2.2.2 · 2.4.2 · 2.4.4 · 2.5.5 · 3.1.1 · 4.1.1 · 4.1.2 |
| `backend/tests/keyboard_nav.py` | 2.1.1 · 2.1.2 · 2.4.1 · 2.4.3 |
| `backend/tests/focus_indicator.py` | 2.4.7 — CSS inspection + Molmo2 visual confirmation |
| `backend/tests/zoom_test.py` | 1.4.4 · 1.4.10 |
| `backend/tests/color_blindness.py` | 1.4.1 · 1.4.3 |
| `backend/tests/form_errors.py` | 3.3.1 · 3.3.2 · 3.3.3 |
| `frontend/components/AuditForm.tsx` | WebSocket client, cold-start banner, retry logic, screenshot b64 collection |
| `frontend/components/ResultsDashboard.tsx` | Full results UI — per-test cards, Molmo2 visual panel, base64 screenshots |
| `frontend/components/TestSelector.tsx` | Test checkbox list with WCAG criteria labels |

---

## The 6 Tests

| ID | Name | WCAG | Method |
|---|---|---|---|
| `page_structure` | Page Structure & Semantics | 1.1.1 · 1.3.1 · 1.4.1 · 2.2.2 · 2.4.2 · 2.4.4 · 2.5.5 · 3.1.1 · 4.1.1 · 4.1.2 | Single JS eval, no GPU (~100ms) |
| `keyboard_nav` | Keyboard-Only Navigation | 2.1.1 · 2.1.2 · 2.4.1 · 2.4.3 | Static JS pre-scan + tab traversal loop |
| `focus_indicator` | Focus Visibility | 2.4.7 | CSS inspection → Molmo2 visual confirmation (capped at 5 calls, 45s timeout each) |
| `zoom` | 200% Zoom / Reflow | 1.4.4 · 1.4.10 | CDP zoom + clipped element detection |
| `color_blindness` | Color Blindness Simulation | 1.4.1 · 1.4.3 | Deuteranopia SVG filter + DOM-tree contrast walk |
| `form_errors` | Form Error Handling | 3.3.1 · 3.3.2 · 3.3.3 | Form submission with invalid data + ARIA error check |

---

## Critical Technical Knowledge

### Molmo2 — Three Compat Patches (applied in BOTH `setup_model.py` AND `modal_app.py` at runtime)

1. **ROPE patch** — `ROPE_INIT_FUNCTIONS` missing `"default"` key → add custom `_default_rope` function
2. **ProcessorMixin patch** — `__init__` rejects unknown kwargs from Molmo2's remote code → monkey-patch to be lenient, store extras with `setattr`
3. **`cache_position` patch** — Transformers 5.x stopped passing `cache_position`; Molmo2 does `cache_position[0]` which crashes. Wrap the model's own method (NOT GenerationMixin grandparent — that bypasses image embedding). Prefill: `torch.arange(seq_len)`, decode: `torch.tensor([past_length])`. Also patched on-disk in `setup_model.py`.

### Molmo2 Inference — Do Not Change Without Reading This

1. **Remove `token_type_ids`** before `generate()` — causes "the the the" repetition if left in
2. **One-step processor call** — pass PIL image directly in messages dict
3. **No sampling** — `max_new_tokens=512` only, greedy decoding
4. **`padding_side="left"`** on processor
5. **`AutoModelForImageTextToText`** not `AutoModelForCausalLM`
6. **ConsecutiveNewlineSuppressor** — custom LogitsProcessor hard-bans newline token (ID 198) after 2 consecutive newlines. Standard `repetition_penalty` crashes because Molmo2 image-token IDs exceed `vocab_size`.
7. **Always 4-bit quantized on CUDA** — fits alongside OLMo3 on A10G 24GB. `bitsandbytes` must be in `modal_app.py` pip_install or `_pointer` silently becomes `None`.

### focus_indicator Timeout Guard
```python
MAX_MOLMO_CALLS = 5    # cap per run — was causing 12m+ timeouts at 15 calls
MOLMO_TIMEOUT  = 45.0  # seconds per call via asyncio.wait_for()
```

### WebSocket Screenshot Strategy
The `done` event strips `screenshot_b64` to stay under the 1MB frame limit:
```python
def _strip_b64(obj): ...
await send({"type": "done", "run_id": run_id, "report": _strip_b64(report)})
```
The frontend (`AuditForm.tsx`) collects `screenshot_b64` from individual `result` events as they stream in, then splices them back into `test_summaries` before rendering. Screenshots are never fetched via HTTP — no 404s on container recycle.

### Other
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` in `modal_app.py` env — reduces CUDA fragmentation
- `allow_origins=["*"], allow_credentials=False` in CORS middleware — required for Vercel → Modal

---

## Deployment

### Backend → Modal
```bash
cd "/Users/brendanworks/Documents/Documents - Brendan's MacBook Pro/WCAG_Tool"
source backend/venv/bin/activate
python -m modal deploy modal_app.py
# ~7-10 min on first deploy (re-downloads models). Subsequent deploys ~2 min if image is cached.
```

### Frontend → Vercel
Push to `main` — Vercel auto-deploys.
- Root directory: `frontend`
- Env var: `NEXT_PUBLIC_API_URL=https://brendanworks--wcag-tester-web.modal.run`
- Domain: `pointcheck.org` — A record `@` → `76.76.21.21`, CNAME `www` → `cname.vercel-dns.com`

### Git
```bash
cd "/Users/brendanworks/Documents/Documents - Brendan's MacBook Pro/WCAG_Tool"
git add <files> && git commit -m "message" && git push
```

---

## Production Fixes Applied Post-Launch

| Bug | Root Cause | Fix |
|---|---|---|
| WebSocket timeout (12m 44s) | `focus_indicator.py` called Molmo2 up to 15× with no timeout | `MAX_MOLMO_CALLS=5`, `asyncio.wait_for(timeout=45.0)` |
| Screenshot 404s | Modal containers are ephemeral; `screenshot_path` HTTP URLs die with container | Frontend collects `screenshot_b64` from streaming `result` events, merges into report on `done` |
| "Invalid URL" error | Users submitting bare domains (e.g. `communitytransit.org`) without `https://` | Auto-prepend `https://` in both `AuditForm.tsx` `handleSubmit` and `main.py` `start_run` |

---

## Known Gotchas

| Issue | Notes |
|---|---|
| Contrast false negative on transparent bg | `getEffectiveBg()` composites alpha layers up full DOM tree — do not simplify |
| Zoom false positive on skip links | Off-screen + `#`-href filter in clipped element JS |
| Molmo2 "not found" on off-screen elements | Expected — skip links and off-screen elements pass with caveat |
| OOM with concurrent runs | Sequential execution, 15s cooldown between runs |
| Next.js CVE-2025-55182 | Patched — upgraded 15.2.4 → 16.2.2 |
| `bitsandbytes` missing from pip_install | Molmo2 loads but `_pointer=None`, silent CSS-only fallback |

---

## WCAG Coverage

| Principle | Criteria |
|---|---|
| Perceivable | 1.1.1 · 1.3.1 · 1.4.1 · 1.4.3 · 1.4.4 · 1.4.10 |
| Operable | 2.1.1 · 2.1.2 · 2.2.2 · 2.4.1 · 2.4.2 · 2.4.3 · 2.4.4 · 2.4.7 · 2.5.5 |
| Understandable | 3.1.1 · 3.3.1 · 3.3.2 · 3.3.3 |
| Robust | 4.1.1 · 4.1.2 |

~85–90% of WCAG 2.1 Level AA success criteria covered programmatically.
