<p align="center">
  <img src="frontend/public/logo-dark.svg" width="120" alt="PointCheck logo" />
</p>

# PointCheck

An automated WCAG 2.1 & 2.2 Level AA accessibility testing tool powered by three Allen AI open-source models running on a single A100-40GB GPU. Paste a URL, select WCAG 2.1 or 2.2 Level AA tests, and get a detailed accessibility report — including a plain-English executive summary from OLMo-3 and visual confirmation of focus rings from MolmoWeb.

**Live:** [pointcheck.org](https://pointcheck.org)

---

## What It Does

The tool runs up to six accessibility tests against any public URL using a headless Chromium browser (Playwright). Results stream back live over WebSocket. When all visual checks finish, an LLM writes a plain-English executive summary.

| Test | WCAG Criteria | Method |
|---|---|---|
| Keyboard-Only Navigation | 2.1.1 · 2.1.2 · 2.4.1 · 2.4.3 | Tab traversal + static JS scan for mouse-only handlers |
| 200% Zoom / Reflow | 1.4.4 · 1.4.10 | Browser zoom + clipped-element detection |
| Color & Contrast | 1.4.1 · 1.4.3 | Deuteranopia SVG filter + DOM-tree contrast walk |
| Focus Visibility | 2.4.7 | CSS inspection + **MolmoWeb-8B pointing** + **Molmo-7B-D QA** ("Is there a visible focus indicator?") |
| Form Error Handling | 3.3.1 · 3.3.2 · 3.3.3 | Form submission with invalid data |
| Page Structure & Semantics | 1.1.1 · 1.3.1 · 1.4.1 · 2.2.2 · 2.4.2 · 2.4.4 · 2.5.5 · 3.1.1 · 4.1.1 · 4.1.2 | Single JS evaluation (~100 ms, no GPU) |

---

## Architecture

```
┌─────────────────────────────────┐        ┌──────────────────────────────────────────┐
│  Next.js 16 + React 19          │        │  FastAPI + Playwright  (Modal A100-40GB) │
│                                 │        │                                          │
│  • URL input + WCAG 2.1/2.2     │◄──WS──►│  Phase 1: MolmoWeb-8B + Molmo-7B-D      │
│  • Live progress feed           │        │    → visual checks, focus confirmation   │
│  • Results dashboard + PDF      │        │  Phase 2: OLMo-3-7B-Instruct             │
│  • JSON / CSV export            │        │    → plain-English narrative             │
└─────────────────────────────────┘        └──────────────────────────────────────────┘
```

### Models

| Model | Role | VRAM |
|---|---|---|
| [allenai/MolmoWeb-8B](https://huggingface.co/allenai/MolmoWeb-8B) | Navigation and visual pointing — drives the headless browser, locates focused elements by pixel coordinate, and confirms focus rings are visually present (not just in the DOM). Output format: `<point x="42.3" y="67.1">` | ~16 GB bfloat16 |
| [allenai/Molmo-7B-D-0924](https://huggingface.co/allenai/Molmo-7B-D-0924) | Screenshot QA — answers accessibility questions about what's visible in a screenshot ("Is there a visible focus indicator? Describe it.") | ~4 GB 4-bit NF4 |
| [allenai/OLMo-3-7B-Instruct](https://huggingface.co/allenai/OLMo-3-7B-Instruct) | Writes the plain-English executive summary after all visual checks complete | ~14 GB bfloat16 |

#### Two-phase model residency

MolmoWeb-8B and Molmo-7B-D run simultaneously during Phase 1 (~20 GB combined), handling all visual checks. Both are freed before OLMo-3 loads for Phase 2 (~14 GB). Total peak VRAM never exceeds ~20 GB — well within the A100-40GB's 42.4 GB.

---

## Key Technical Details

- **WCAG 2.1 & 2.2 support** — a version selector switches between 2.1 AA and 2.2 AA rule sets. WCAG 2.2 adds criterion 2.4.11 (focus appearance) and tightens 2.5.8 (minimum touch target 24×24 px)
- **WebSocket streaming** — test events (`test_start`, `result`, `test_complete`, `done`) push to the browser in real time
- **WebSocket keepalive** — a 20-second heartbeat task keeps the connection alive across cold-start model loading (60–90 s) to prevent Modal's load balancer from dropping idle connections
- **Base64 screenshots** — Modal is serverless; screenshots are embedded directly in result events rather than saved to disk
- **4-bit quantization** — Molmo-7B-D uses `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4")` to fit alongside MolmoWeb-8B (~16 GB) within Phase 1's VRAM budget
- **Transformers 5.x compatibility** — MolmoWeb's `trust_remote_code` predates Transformers 5.x. PointCheck patches `GenerationMixin` into the model's MRO at load time, adds `DynamicCache.__getitem__` for tuple-style KV cache access, and shims `prepare_inputs_for_generation` with a `cache_position` fallback. OLMo-3 receives a separate patch to add a no-op setter on `PreTrainedModel.all_tied_weights_keys`, which Transformers 5.x `post_init()` tries to assign
- **DOM-tree contrast walk** — `getEffectiveBg()` composites alpha layers up the DOM tree to find the actual rendered background, avoiding false passes on transparent elements
- **Static JS keyboard scan** — before tab traversal, scans the DOM for `javascript:` hrefs, `onclick` on non-interactive elements, missing skip navigation, and positive `tabindex` values that override natural tab order (2.4.3)
- **Touch target size** — flags interactive elements under 24×24 px (WCAG 2.2 AA 2.5.8; WCAG 2.1 AAA 2.5.5 requires 44×44 px)
- **Table headers** — detects data table cells with no associated `<th>` or `scope` (1.3.1)
- **iframe titles** — flags `<iframe>` elements missing `title` or `aria-label` (4.1.2)
- **Color-only links** — detects inline links with no underline or non-color visual cue (1.4.1)
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` — reduces CUDA memory fragmentation across the two-phase model lifecycle

---

## Project Structure

```
.
├── modal_app.py              # Modal deployment (image build + ASGI wrapper)
├── backend/
│   └── app/
│       ├── main.py               # FastAPI app, WebSocket handler, keepalive
│       ├── crawler.py            # Playwright BFS site crawler
│       ├── report_generator.py   # Aggregates results → JSON/CSV report
│       ├── eval_logger.py        # Per-run evaluation logging
│       ├── schemas.py            # Pydantic request/response models
│       ├── models/
│       │   ├── molmo2.py         # MolmoWeb-8B (navigation) + Molmo-7B-D (QA)
│       │   └── olmo3.py          # OLMo-3-7B-Instruct (narrative)
│       └── checks/
│           ├── keyboard_nav.py
│           ├── zoom_test.py
│           ├── color_blindness.py
│           ├── focus_indicator.py
│           ├── form_errors.py
│           └── page_structure.py
└── frontend/
    ├── app/
    │   └── page.tsx              # Server component entry point
    └── components/
        ├── AuditForm.tsx         # URL input, WCAG version selector, WebSocket client
        ├── TestSelector.tsx      # Test checkbox list with severity badges
        ├── ProgressDisplay.tsx   # Live event feed with cold-start notice
        └── ResultsDashboard.tsx  # Results, compliance score, PDF export
```

---

## Running Locally

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

uvicorn app.main:app --reload --port 8000
```

The first run downloads MolmoWeb-8B (~16 GB), Molmo-7B-D (~4 GB), and OLMo-3-7B (~14 GB). A CUDA GPU with at least 20 GB VRAM is required for Phase 1 (both Molmo models co-resident).

### Frontend

```bash
cd frontend
npm install

# Point at your local backend
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

> **Note:** The frontend uses Next.js 16 with React 19. Run `npm run build && npm run start` instead of `npm run dev` if you encounter hydration issues in the development server.

---

## Deploying

### Backend → Modal

```bash
pip install modal
modal deploy modal_app.py            # production
modal deploy --env staging modal_app.py   # staging
```

The Modal image bakes all three model weight snapshots into the container at build time (`setup_models.py`) so cold starts don't re-download weights. Typical cold start after a new deploy: ~90 s. Warm subsequent runs: ~60–90 s per scan.

### Frontend → Vercel

Push to `main`. Vercel auto-deploys from the `frontend/` root directory.

Set the environment variable in your Vercel project:

```
NEXT_PUBLIC_API_URL=https://brendanworks--wcag-tester-web.modal.run
```

---

## Validation — Multi-Site Testing

The tool was validated against five external sites to confirm real catches, expose false positives/negatives, and drive bug fixes.

| Site | Purpose | Key Outcome |
|---|---|---|
| [W3C WAI "BAD" Demo](https://www.w3.org/WAI/demos/bad/) | W3C's official intentionally-broken accessibility demo — ground truth | Found + fixed 2 false negatives |
| [GDS Accessibility Tool Audit](https://alphagov.github.io/accessibility-tool-audit/test-cases.html) | GDS benchmark page containing every common failure — primary Lighthouse/Axe comparison | All 6 test dimensions fired correctly |
| Mars Commuter | JS-heavy site with modals, dropdowns, dynamic content | Confirmed correct handling of complex components |
| [Accessible University 3.0](https://www.washington.edu/accesscomputing/AU/) (U. Washington) | Before/after accessibility demo with intentional failures | Confirmed multi-page site handling |
| [Tenon UI](https://tenon-ui.info) | Intentionally *accessible* React component library — adversarial false-positive test | Found + fixed 1 false positive |

### Results by site

**W3C WAI "BAD" Demo** — all documented failures caught (keyboard JS-only links, contrast, focus, zoom, form labels). Two bugs fixed:
- **Contrast false negative** — `getEffectiveBg()` was skipping `rgba(0,0,0,0)` transparent elements. Rewrote to composite alpha layers up the full DOM tree, catching contrast failures on elements with inherited backgrounds.
- **Keyboard false negative** — tab traversal alone missed JS-only links. Added `KEYBOARD_STATIC_JS` pre-scan for `javascript:` hrefs, `onclick` on non-interactive elements, `onmouseover` without `onfocus`, and missing skip navigation.

**GDS Accessibility Tool Audit** — the UK Government Digital Service's benchmark page, built to contain every common failure. Lighthouse scored it 56/100 (19 failures); Axe found 22 violations. PointCheck failed all 6 test dimensions, confirming every test category fires correctly on a page designed to break all of them. The 5 dynamic test categories (zoom, color blindness, MolmoWeb focus, keyboard behavior, form errors) all fired on real failures that neither Lighthouse nor Axe detected.

**Mars Commuter** — keyboard JS links detected, contrast failures caught, 5 unlabeled form fields identified. Zoom correctly passed. Tool handled iframe focus issues correctly.

**Accessible University 3.0** — contrast failure caught at 2.52:1 (well below 4.5:1 threshold), 5 unlabeled form fields detected, focus styles correctly flagged as absent. Zoom correctly passed on a site that reflows properly.

**Tenon UI** — all tests correctly passed except one false positive fixed:
- **Zoom false positive on skip links** — "Skip to content" links are intentionally off-screen (`position:absolute; left:-9999px`) until focused. Tool was incorrectly flagging them as clipped text. Fixed by adding off-screen detection and skip link filter in the clipped element JS scan.

---

## WCAG Coverage

| Principle | Criteria Tested |
|---|---|
| Perceivable | 1.1.1 · 1.3.1 · 1.4.1 · 1.4.3 · 1.4.4 · 1.4.10 |
| Operable | 2.1.1 · 2.1.2 · 2.4.1 · 2.4.2 · 2.4.3 · 2.4.4 · 2.4.7 · 2.4.11 *(2.2)* · 2.5.5 · 2.5.8 *(2.2)* |
| Understandable | 3.1.1 · 3.3.1 · 3.3.2 · 3.3.3 |
| Robust | 4.1.1 · 4.1.2 |

Approximately **85–90% of WCAG 2.1 Level AA** success criteria are covered programmatically, with additional **WCAG 2.2** criteria for focus appearance and touch targets. Tests that require human judgment (e.g. captions on live video, cognitive load assessment) are out of scope.

---

## Built With

- [Allen AI MolmoWeb-8B](https://huggingface.co/allenai/MolmoWeb-8B) — open-source VLM for browser navigation and visual pointing
- [Allen AI Molmo-7B-D](https://huggingface.co/allenai/Molmo-7B-D-0924) — open-source VLM for screenshot QA
- [Allen AI OLMo-3](https://allenai.org/olmo) — open-source LLM for narrative generation
- [Playwright](https://playwright.dev) — headless browser automation
- [FastAPI](https://fastapi.tiangolo.com) — async Python API
- [Modal](https://modal.com) — serverless GPU deployment (A100-40GB)
- [Next.js 16](https://nextjs.org) — React 19 frontend
- [Vercel](https://vercel.com) — frontend hosting
