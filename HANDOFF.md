# WCAG MolmoWeb Tester — Handoff Document

## What This Is
A WCAG 2.1 Level AA accessibility testing tool powered by Allen AI's MolmoWeb-4B vision-language model. Users enter a URL, select tests, and get an accessibility audit. Built as a portfolio piece / calling card for an Allen AI job application.

- **GitHub**: https://github.com/BrendanWorks/wcag-molmoweb-tester
- **Live**: https://brendanworks--wcag-tester-web.modal.run
- **Stack**: FastAPI + WebSocket + Playwright + MolmoWeb-4B on Modal (A10G GPU)

## Architecture

```
Frontend (static HTML)  →  FastAPI  →  WebSocket streams progress
                                    →  Playwright captures screenshots
                                    →  MolmoWeb-4B analyzes them
                                    →  Report generated & sent back
```

### Key Files
| File | Purpose |
|------|---------|
| `backend/wcag_agent.py` | **Core file.** MolmoWeb wrapper with all compatibility patches. |
| `backend/main.py` | FastAPI app. Serves frontend, WebSocket for live progress. |
| `backend/static/index.html` | Complete static HTML frontend (replaced broken Next.js). |
| `backend/report_generator.py` | Generates compliance report from test results. |
| `backend/setup_model.py` | Modal image build script — downloads model, applies file patches. |
| `modal_app.py` | Modal deployment config — A10G GPU, 900s timeout. |
| `backend/tests/keyboard_nav.py` | Phase 1: Tab navigation + MolmoWeb analysis (MAX_TABS=10). |
| `backend/tests/zoom_test.py` | Phase 1: 200% zoom + MolmoWeb analysis. |
| `backend/tests/color_blindness.py` | Phase 1: Deuteranopia filter + MolmoWeb analysis. |
| `backend/tests/focus_indicator.py` | Phase 2: DOM-only focus ring check (no MolmoWeb, fast). |
| `backend/tests/form_errors.py` | Phase 2: Form submission + MolmoWeb analysis (2 inferences). |

## Critical Technical Knowledge

### MolmoWeb-4B + Transformers 5.x Requires THREE Patches

1. **ROPE patch** — `ROPE_INIT_FUNCTIONS` missing `"default"` key. We add a custom `_default_rope` function.
2. **ProcessorMixin patch** — `__init__` rejects unknown kwargs from MolmoWeb's remote code. We monkey-patch to be lenient.
3. **cache_position patch** — Transformers 5.x stopped passing `cache_position` to `prepare_inputs_for_generation`, but Molmo2's code does `cache_position[0]` which crashes. We wrap the original method and synthesize a valid `cache_position` tensor.

All three patches are applied in BOTH `setup_model.py` (image build) AND `wcag_agent.py` / `modal_app.py` (runtime).

### MolmoWeb Inference — Critical Details

These were discovered through painful debugging. **Do not change without understanding:**

1. **`token_type_ids` MUST be removed** from inputs before `generate()`. MolmoWeb uses causal attention only. HuggingFace adds `token_type_ids` for bidirectional attention on image tokens, which causes **degenerate repetitive output** (the "the the the the" bug).

2. **One-step processor call** — Pass the PIL image directly in messages:
   ```python
   messages = [{"role": "user", "content": [
       {"type": "image", "image": pil_image},  # NOT just {"type": "image"}
       {"type": "text", "text": prompt},
   ]}]
   inputs = processor.apply_chat_template(messages, tokenize=True, return_dict=True, ...)
   ```
   The old two-step approach (apply_chat_template then processor()) didn't bind images to tokens correctly.

3. **`"molmo_web_think: "` prefix** — MolmoWeb expects this system message prefix on prompts.

4. **No sampling parameters** — Just `max_new_tokens=512`. No `temperature`, no `top_p`. Model was trained for greedy decoding.

5. **`padding_side="left"`** on the processor.

6. **Only decode NEW tokens** — `outputs[0][input_len:]` not `outputs[0]`. Otherwise you get the echoed prompt.

7. **Use `AutoModelForImageTextToText`** not `AutoModelForCausalLM`.

8. **`bfloat16` on GPU, `float32` on CPU** — Model card recommends float32 but bfloat16 works on A10G. If quality degrades, try float32.

### Monkey-Patch for cache_position (in wcag_agent.py)

The patch wraps the model's OWN `prepare_inputs_for_generation` (not the grandparent's!) and synthesizes `cache_position` when it's None:
- Prefill: `torch.arange(seq_len)`
- Decode: `torch.tensor([past_length])`

**DO NOT** call `GenerationMixin.prepare_inputs_for_generation` (grandparent) as a replacement — that bypasses Molmo2's image embedding logic and the model can't see screenshots.

### File-Based Patch (in setup_model.py)

Also patches `modeling_molmo2.py` on disk during image build to handle `cache_position=None`:
```python
# Replaces: if cache_position[0] == 0:
# With: is_prefill = (cache_position is not None and cache_position[0] == 0) or (cache_position is None and past_key_values is None)
```

## Deployment Workflow

```bash
# Push to GitHub
git add -A && git commit -m "message" && git push

# Deploy to Modal (takes ~3-5 min, downloads 12GB model into image)
cd "/path/to/WCAG_Tool" && modal deploy modal_app.py

# Check logs
modal app logs wcag-tester

# Keep Mac awake during long runs
caffeinate -d -i -s
```

## Current Status (as of 2026-04-05)

### Working
- All 5 tests run to completion on Modal within 900s timeout
- Keyboard navigation: produces real FAIL results using DOM fallbacks
- Focus indicator: fast DOM-only check, working
- Form errors: finds forms, checks labels, working
- Screenshots: inline base64 in results (fixed 404 issue with file URLs on Modal)
- Frontend: form, progress bar, results dashboard, JSON/CSV download

### In Progress / Needs Verification
- **Zoom test + Color blindness test**: Latest deploy has the `token_type_ids` fix, `molmo_web_think:` prefix, one-step processor call, and greedy decoding. **WAITING TO SEE IF MODEL PRODUCES VALID JSON.** If still broken, check Modal logs with `modal app logs wcag-tester | grep "\[MolmoWeb\] Generated"`.

### If Model Still Produces Garbage
Debug checklist:
1. Check `modal app logs wcag-tester | grep "\[MolmoWeb\] Generated"` — is output coherent text or repetitive?
2. If repetitive: `token_type_ids` might not be getting removed. Add `print(list(inputs.keys()))` before generate.
3. If coherent but not JSON: prompt needs adjustment. MolmoWeb is a web-agent model, not a general VLM. It may respond with action commands instead of JSON analysis. Consider parsing its natural language output instead.
4. If error/crash: check full traceback in logs. Likely a cache_position or tensor shape issue.
5. Nuclear option: try `allenai/Molmo2-4B` (non-web variant) which may be better at general image analysis.

### Bugs Fixed (Don't Reintroduce)
- **Next.js hydration failure** → replaced with static HTML
- **Turbopack scanning home dir** → no more Next.js
- **WebSocket not flushing** → `run_in_executor` for model load
- **Model inference blocking event loop** → `run_in_executor` for all inference
- **Modal Mount API deprecated** → `image.add_local_dir(copy=True)`
- **Modal allow_concurrent_inputs deprecated** → `@modal.concurrent(max_inputs=5)`
- **Results dashboard showing zeros** → fixed field names (total_tests, passed, failed)
- **Screenshot 404 on Modal** → switched to inline base64 data URIs

## Future Enhancements
- DOM-only tests for broader WCAG coverage (alt text, heading hierarchy, ARIA, contrast ratio via computed styles)
- Better prompt engineering if MolmoWeb produces action commands instead of analysis
- Consider Molmo2-4B (non-web) as alternative for visual analysis tasks
- Polish report: add WCAG criterion descriptions, link to spec, severity scoring
