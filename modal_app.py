"""
PointCheck — Modal Deployment

Three-model architecture:
  allenai/MolmoWeb-8B       — web navigation agent + element pointing (bfloat16, ~16 GB)
  allenai/Molmo-7B-D-0924   — screenshot QA + holistic WCAG analysis (4-bit NF4, ~4 GB)
  allenai/OLMo-3-7B-Instruct — executive summary narrative (bfloat16, ~14 GB)

Function layout:
  web      (A100-40GB) — FastAPI + WebSocket. MolmoWeb + MolmoQA load once per
                         container and stay resident (~20 GB / 42.4 GB); warm
                         scans skip the 60-90 s model load entirely.
  narrate  (A10G)      — OLMo-3 executive summary on its own scale-to-zero GPU,
                         called remotely by web, so the visual models are never
                         unloaded to make room for it.
BFS site crawl via Playwright.
Entrypoint: backend/app/main.py (FastAPI + WebSocket streaming).
"""

import modal

app = modal.App("wcag-tester")

# Container-level OLMo cache for the narrate function — persists across
# .remote() calls while the container stays warm.
_narrator = None

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "torchvision",
        "transformers>=4.57.0",
        "Pillow",
        "einops",
        "requests",
        "numpy",
        "accelerate",
        "bitsandbytes",
        "playwright",
        "fastapi",
        "uvicorn[standard]",
        "websockets",
        "pydantic",
        "python-multipart",
        "tensorflow-cpu",  # required by Molmo-7B-D-0924 processor remote code
    )
    .run_commands("playwright install chromium && playwright install-deps")
    .add_local_dir("backend", remote_path="/app", copy=True)
    .run_commands("cd /app/app && python setup_models.py", gpu="any")
)


@app.function(
    image=image,
    gpu="A100-40GB",
    # Must cover the longest scan the API will accept: max_pages (capped at 15
    # in schemas.py) × worst-case ~90 s/page cold ≈ 1350 s, with margin.
    # A shorter timeout would silently kill large crawls mid-scan.
    timeout=1800,
    # Hard spend ceiling: at most 2 A100 containers, no matter the request
    # volume. Per-IP rate limiting in app/main.py handles burst control.
    max_containers=2,
    env={
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        # Persistent job store — Modal Dict name for permalink support.
        # Modal's --env flag isolates staging and prod into separate namespaces,
        # so staging and prod never share state even with the same dict name.
        "MODAL_JOBS_DICT": "pointcheck-jobs",
    },
)
@modal.concurrent(max_inputs=5)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")

    # Runtime Molmo2 compat patches (mirrors setup_model.py)
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
    if "default" not in ROPE_INIT_FUNCTIONS:
        import torch as _t
        def _default_rope(config, device=None):
            inv_freq = 1.0 / (
                config.rope_theta ** (
                    _t.arange(0, config.head_dim, 2, dtype=_t.float32, device=device)
                    / config.head_dim
                )
            )
            return inv_freq, 1.0
        ROPE_INIT_FUNCTIONS["default"] = _default_rope

    import transformers.processing_utils as _pu
    _orig = _pu.ProcessorMixin.__init__
    def _lenient(self, *a, **kw):
        known  = set(self.get_attributes()) | {"chat_template", "audio_tokenizer"}
        extras = {k: v for k, v in kw.items() if k not in known}
        clean  = {k: v for k, v in kw.items() if k in known}
        for k, v in extras.items():
            setattr(self, k, v)
        return _orig(self, *a, **clean)
    _pu.ProcessorMixin.__init__ = _lenient

    from app.main import app as fastapi_app
    return fastapi_app


@app.function(
    image=image,
    gpu="A10G",
    timeout=300,
    max_containers=2,
    env={"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
)
def narrate(all_results: list, site_url: str, pages_scanned: int) -> dict:
    """
    OLMo-3-7B executive-summary narrative, isolated on its own GPU so the
    web container never unloads MolmoWeb between scans. OLMo-3 bf16 (~14 GB)
    fits an A10G (24 GB). Callers must strip screenshot_b64 from all_results
    first — the narrator only reads the text fields.

    Returns {"narrative": str, "stats": dict | None}.
    """
    import asyncio
    import sys
    sys.path.insert(0, "/app")

    global _narrator
    if _narrator is None:
        from app.models.olmo3 import OLMo3Narrator
        _narrator = OLMo3Narrator()

    narrative = asyncio.run(_narrator.generate_narrative(
        all_results=all_results,
        site_url=site_url,
        pages_scanned=pages_scanned,
    ))
    return {"narrative": narrative, "stats": _narrator.last_inference_stats}
