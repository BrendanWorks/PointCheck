# PointCheck — Setup

## Prerequisites
- Python 3.10+
- Node.js 18+
- GPU recommended (NVIDIA CUDA). CPU works but inference is slow.
- ~12 GB free disk space (MolmoWeb-4B model download, one-time)

---

## 1. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## 2. Frontend Setup

```bash
cd frontend
npm install
```

## 3. Run

```bash
# From project root — starts both servers:
bash start.sh
```

Or start separately:

```bash
# Terminal 1 — backend
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:3000**.

---

## First Run Note

The MolmoWeb-4B model (~12 GB) downloads automatically from HuggingFace on the first
test run. This takes several minutes depending on your connection. Subsequent runs use
the cached model and start immediately.

If you're low on VRAM, check **"Use 4-bit quantization"** in the UI. This reduces
memory usage at the cost of slower inference.

---

## Available Tests (Phase 1 — MVP)

| Test | WCAG Criteria |
|------|--------------|
| Keyboard-Only Navigation | 2.1.1, 2.1.2, 2.4.3 |
| 200% Zoom / Reflow | 1.4.4, 1.4.10 |
| Color-Blindness Simulation | 1.4.1, 1.4.3 |

**Phase 2 tests** (also implemented):

| Test | WCAG Criteria |
|------|--------------|
| Focus Visibility Check | 2.4.7 |
| Form Error Handling | 3.3.1, 3.3.2, 3.3.3 |

---

## API

- `POST /api/run` — Queue a test run
- `GET /api/run/{run_id}` — Get run state + report
- `GET /api/runs` — List all runs
- `WS /ws/{run_id}` — Stream live progress
- `GET /health` — Health check
