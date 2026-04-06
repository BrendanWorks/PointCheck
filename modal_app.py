"""
WCAG 2.1 Accessibility Tester — Modal Deployment
Serves the FastAPI app on a GPU with OLMo2-7B-Instruct pre-loaded.

Architecture:
  - 5 WCAG tests run fully programmatically via Playwright DOM inspection
  - allenai/OLMo-2-1124-7B-Instruct generates the executive summary narrative
"""

import modal

app = modal.App("wcag-tester")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "torchvision",
        "transformers>=4.45.0",
        "Pillow",
        "requests",
        "numpy",
        "accelerate",
        "playwright",
        "fastapi",
        "uvicorn[standard]",
        "websockets",
        "pydantic",
        "python-multipart",
    )
    .run_commands("playwright install chromium && playwright install-deps")
    .add_local_dir("backend", remote_path="/app", copy=True)
    .run_commands("cd /app && python setup_model.py", gpu="any")
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=900,
)
@modal.concurrent(max_inputs=5)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/app")

    from main import app as fastapi_app
    return fastapi_app
