"""Image generation for Lumina's "Image" mode.

Two providers (choose with IMAGE_PROVIDER in .env):

* ``local``  – a Stable Diffusion model running on this PC through Hugging Face
  ``diffusers`` (default model: stabilityai/sd-turbo, 1 step, 512 x 512).
  Works on Windows, Linux and macOS, on CPU or an NVIDIA/Apple GPU.
  The libraries are optional: ``pip install -r backend/requirements-image.txt``.
  The model downloads automatically the first time (about 2–3 GB).
* ``openai`` – any server with the OpenAI ``/v1/images/generations`` API, for
  example Ollama's image models on macOS or LocalAI.

Images are saved as PNG files in IMAGE_DIR and served by the API.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from backend.app.core.config import settings

log = logging.getLogger("lumina.images")

REQUIRED_PACKAGES = ("torch", "diffusers", "transformers", "accelerate")
INSTALL_HINT = (
    "Image generation needs extra libraries. In the project folder run:\n"
    "pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
    "pip install -r backend/requirements-image.txt\n"
    "then restart the backend."
)
_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_pipeline: Any = None
_pipeline_model: str | None = None
_lock = asyncio.Lock()          # one image at a time – it uses the whole CPU/GPU


class ImageError(Exception):
    """A problem the user can fix (shown as a friendly message)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ helpers

def provider() -> str:
    p = settings().image_provider.strip().lower()
    return p if p in {"local", "openai", "off"} else "local"


def image_dir() -> Path:
    path = Path(settings().image_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_path(image_id: str) -> Path | None:
    """Path of a saved image, or None for an invalid/unknown id."""
    if not _ID_RE.match(image_id or ""):
        return None
    path = image_dir() / f"{image_id}.png"
    return path if path.exists() else None


def missing_packages() -> list[str]:
    return [name for name in REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]


def clamp_size(value: int | None) -> int:
    """256–1024 px, rounded to a multiple of 64 (what Stable Diffusion needs)."""
    size = int(value or settings().image_size or 512)
    size = max(256, min(1024, size))
    return int(round(size / 64) * 64)


def status() -> dict[str, Any]:
    s = settings()
    p = provider()
    info: dict[str, Any] = {"provider": p, "enabled": p != "off", "size": clamp_size(None)}
    if p == "local":
        missing = missing_packages()
        info.update(
            model=s.image_model,
            ready=not missing,
            loaded=_pipeline is not None and _pipeline_model == s.image_model,
            missing=missing,
            message="" if not missing else INSTALL_HINT,
        )
    elif p == "openai":
        info.update(model=s.image_api_model, ready=True, missing=[], message="", base_url=_api_base())
    else:
        info.update(model="", ready=False, missing=[], message="Image generation is turned off (IMAGE_PROVIDER=off).")
    return info


# ------------------------------------------------------------------ local (diffusers)

def _load_pipeline():
    """Load the diffusers pipeline once and keep it in memory."""
    global _pipeline, _pipeline_model
    s = settings()
    if _pipeline is not None and _pipeline_model == s.image_model:
        return _pipeline

    import torch  # noqa: PLC0415 – optional dependency
    from diffusers import AutoPipelineForText2Image  # noqa: PLC0415

    if torch.cuda.is_available():
        device, dtype = "cuda", torch.float16
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device, dtype = "mps", torch.float16
    else:
        device, dtype = "cpu", torch.float32

    log.info("Loading image model %s on %s (first time downloads it)…", s.image_model, device)
    started = time.perf_counter()
    try:
        # The half-size "fp16" files download about twice as fast; on CPU they
        # are converted to float32 after loading.
        pipe = AutoPipelineForText2Image.from_pretrained(s.image_model, torch_dtype=dtype, variant="fp16")
    except (OSError, ValueError):
        pipe = AutoPipelineForText2Image.from_pretrained(s.image_model, torch_dtype=dtype)
    pipe = pipe.to(device)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    log.info("Image model ready in %.1f s", time.perf_counter() - started)
    _pipeline, _pipeline_model = pipe, s.image_model
    return pipe


def _generate_local(prompt: str, size: int, steps: int, seed: int) -> Image.Image:
    import torch  # noqa: PLC0415

    pipe = _load_pipeline()
    device = getattr(pipe, "device", "cpu")
    generator = torch.Generator(device="cpu" if str(device).startswith("mps") else device).manual_seed(seed)
    result = pipe(
        prompt=prompt,
        width=size,
        height=size,
        num_inference_steps=steps,
        guidance_scale=settings().image_guidance,
        generator=generator,
    )
    return result.images[0]


# ------------------------------------------------------------------ OpenAI-compatible server

def _api_base() -> str:
    s = settings()
    return (s.image_api_base_url or f"{s.ollama_base_url.rstrip('/')}/v1").rstrip("/")


async def _generate_openai(prompt: str, size: int, steps: int, seed: int) -> Image.Image:
    s = settings()
    headers = {"Authorization": f"Bearer {s.image_api_key}"} if s.image_api_key else {}
    body = {
        "model": s.image_api_model,
        "prompt": prompt,
        "size": f"{size}x{size}",
        "n": 1,
        "response_format": "b64_json",
        "steps": steps,
        "seed": seed,
    }
    async with httpx.AsyncClient(timeout=s.image_timeout) as client:
        response = await client.post(f"{_api_base()}/images/generations", json=body, headers=headers)
        if response.status_code >= 400:
            raise ImageError(f"The image server answered {response.status_code}: {response.text[:300]}", 502)
        item = (response.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            raw = (await client.get(item["url"])).content
        else:
            raise ImageError("The image server returned no image.", 502)
    return Image.open(io.BytesIO(raw))


# ------------------------------------------------------------------ public API

async def generate(prompt: str, size: int | None = None, steps: int | None = None, seed: int | None = None) -> dict[str, Any]:
    """Create one image from a text prompt, save it as PNG and return its details."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageError("Describe the image you want.")
    p = provider()
    if p == "off":
        raise ImageError("Image generation is turned off (IMAGE_PROVIDER=off in .env).", 403)
    if p == "local" and missing_packages():
        raise ImageError(INSTALL_HINT, 503)

    s = settings()
    size = clamp_size(size)
    steps = max(1, min(50, int(steps or s.image_steps or 1)))
    seed = int(seed) if seed is not None else random.randint(0, 2**31 - 1)

    async with _lock:
        started = time.perf_counter()
        try:
            if p == "local":
                image = await asyncio.to_thread(_generate_local, prompt, size, steps, seed)
            else:
                image = await _generate_openai(prompt, size, steps, seed)
        except ImageError:
            raise
        except httpx.HTTPError as exc:
            raise ImageError(f"Could not reach the image server at {_api_base()}: {exc}", 502) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception("Image generation failed")
            raise ImageError(f"Image generation failed: {exc}", 500) from exc
        elapsed = time.perf_counter() - started

    image_id = uuid.uuid4().hex
    path = image_dir() / f"{image_id}.png"
    image.convert("RGB").save(path, format="PNG")
    log.info("Image %s made in %.1f s (%dx%d, %d steps)", image_id, elapsed, image.width, image.height, steps)
    return {
        "id": image_id,
        "url": f"/api/images/{image_id}",
        "prompt": prompt,
        "width": image.width,
        "height": image.height,
        "steps": steps,
        "seed": seed,
        "model": s.image_model if p == "local" else s.image_api_model,
        "seconds": round(elapsed, 1),
    }
