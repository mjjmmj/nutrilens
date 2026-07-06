"""
cloud_ocr.py
============
Optional cloud-based OCR backends, as an alternative to the local
pytesseract/EasyOCR pipeline in `ocr_parser.py`. These can help with
blurry or steeply-angled photos that a local, general-purpose OCR engine
struggles with, since they run larger vision-language models.

Two backends are supported:

1. **baidu/Unlimited-OCR** (Hugging Face Space, no API key needed)
   https://huggingface.co/spaces/baidu/Unlimited-OCR
   Called via `gradio_client`, the standard way to programmatically call
   any Gradio-based Space. This is a community demo running on HF's
   shared "ZeroGPU" infrastructure, not a stable, versioned API with an
   SLA -- treat it as a free bonus option, not a dependable primary path.

2. **Mistral OCR** (official cloud API, requires the user's own API key)
   This module calls Mistral's official OCR endpoint
   (https://api.mistral.ai/v1/ocr) directly with the person's own API
   key, rather than routing through the community Space at
   huggingface.co/spaces/merterbak/Mistral-OCR. That Space is itself just
   a thin UI wrapper around this same official endpoint (confirmed by
   reading its source) -- calling Mistral directly means the API key
   goes straight to Mistral and never transits a third party's server,
   and doesn't depend on a demo Space staying online.

IMPORTANT HONESTY NOTE: neither integration could be exercised against
the live services while building this, because this development
environment's network access doesn't extend to huggingface.co, *.hf.space,
or api.mistral.ai. The request-building and response-parsing logic below
is implemented directly from each service's own published source/docs and
is unit-tested against realistic mocked responses (see
tests/test_cloud_ocr.py), but genuinely exercising it against the live
services is worth doing once deployed, since either provider could change
their interface without notice -- these are third-party services this
app doesn't control.

Design goals shared with the rest of the OCR pipeline:
- Never crash the app: any failure (missing dependency, network error,
  timeout, bad API key, malformed response) raises a `CloudOCRError`
  with a clear, user-facing message, which the UI catches and turns into
  a friendly warning + fallback suggestion, rather than an unhandled
  exception.
- Return plain text, exactly like the local OCR path, so the *same*
  `parse_nutrition_text()` field-parsing logic (English + Japanese,
  full nutrient panel) works regardless of which engine produced it.
"""

from __future__ import annotations

import base64
import tempfile
from io import BytesIO

import requests
from PIL import Image

try:
    from gradio_client import Client as GradioClient, handle_file
    _HAS_GRADIO_CLIENT = True
except ImportError:
    _HAS_GRADIO_CLIENT = False


class CloudOCRError(Exception):
    """Raised for any cloud OCR failure, with a message safe to show
    directly to the user (no stack traces / internal details)."""


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def _image_to_data_uri(image: Image.Image, format: str = "PNG") -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format=format)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    mime = "image/png" if format.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


# --------------------------------------------------------------------------- #
# Backend 1: baidu/Unlimited-OCR (Hugging Face Space, no API key)
# --------------------------------------------------------------------------- #

BAIDU_SPACE_ID = "baidu/Unlimited-OCR"


def baidu_ocr_available() -> bool:
    return _HAS_GRADIO_CLIENT


def run_baidu_unlimited_ocr(image: Image.Image, mode: str = "gundam", timeout: int = 90) -> str:
    """Run OCR via the baidu/Unlimited-OCR Hugging Face Space.

    `mode`: "gundam" (faster, 640px crop) or "base" (slower, more
    accurate at 1024px) -- these are the two modes the Space itself
    exposes.

    This Space runs on HF's shared ZeroGPU pool: as an anonymous
    (non-logged-in) caller, expect queueing delays and occasional
    unavailability at busy times -- this is a free community resource,
    not a guaranteed-uptime service.

    Raises CloudOCRError on any failure. Never returns partial garbage
    silently; either returns real extracted text or raises.
    """
    if not _HAS_GRADIO_CLIENT:
        raise CloudOCRError(
            "The 'gradio_client' package isn't installed, which is needed "
            "to use the baidu/Unlimited-OCR cloud engine. Add `gradio_client` "
            "to requirements.txt and reinstall, or use a different OCR engine."
        )

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image.convert("RGB").save(tmp, format="PNG")
            tmp_path = tmp.name

        client = GradioClient(BAIDU_SPACE_ID)
        result = client.predict(
            image_path=handle_file(tmp_path),
            mode=mode,
            prompt="document parsing.",
            api_name="/run_ocr",
        )
    except Exception as exc:
        raise CloudOCRError(
            f"Couldn't reach the baidu/Unlimited-OCR service ({exc}). "
            "It may be busy, rate-limiting anonymous requests, or "
            "temporarily down -- try again shortly, or use a different "
            "OCR engine."
        ) from exc

    # The Space's `run_ocr` is a streaming generator that yields
    # {"text": ..., "done": bool} dicts; gradio_client's .predict() on a
    # streaming endpoint returns the final yielded value once the stream
    # completes, i.e. the finished {"text": full_text, "done": True}.
    text = None
    if isinstance(result, dict):
        text = result.get("text")
    elif isinstance(result, str):
        text = result

    if not text:
        raise CloudOCRError(
            "baidu/Unlimited-OCR returned no text for this image. Try a "
            "clearer photo, or use a different OCR engine."
        )
    return text


# --------------------------------------------------------------------------- #
# Backend 2: Mistral OCR (official cloud API, requires user's own API key)
# --------------------------------------------------------------------------- #

MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"
# Per Mistral's own published model naming; update if Mistral releases a
# newer OCR model id.
MISTRAL_OCR_MODEL = "mistral-ocr-2512"
MISTRAL_REQUEST_TIMEOUT_SECONDS = 60


def run_mistral_ocr(image: Image.Image, api_key: str, timeout: int = MISTRAL_REQUEST_TIMEOUT_SECONDS) -> str:
    """Run OCR via Mistral's official cloud OCR API, using the person's
    own Mistral API key (never stored -- passed in per-call from the UI's
    session-only password field).

    Get a key at https://console.mistral.ai/

    Raises CloudOCRError on any failure (missing/invalid key, network
    error, timeout, malformed response), with a message safe to show
    directly to the user.
    """
    if not api_key or not api_key.strip():
        raise CloudOCRError(
            "A Mistral API key is required for this engine. Get one at "
            "https://console.mistral.ai/, or use a different OCR engine "
            "that doesn't need one."
        )

    data_uri = _image_to_data_uri(image)
    payload = {
        "model": MISTRAL_OCR_MODEL,
        "document": {"type": "image_url", "image_url": data_uri},
        "include_image_base64": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            MISTRAL_OCR_URL, json=payload, headers=headers, timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise CloudOCRError(
            "Mistral OCR timed out. Try again, or use a different OCR engine."
        ) from exc
    except Exception as exc:
        raise CloudOCRError(f"Couldn't reach Mistral's OCR API ({exc}).") from exc

    if response.status_code == 401:
        raise CloudOCRError(
            "Mistral rejected the API key (401 Unauthorized). Double-check "
            "the key at https://console.mistral.ai/."
        )
    if response.status_code == 429:
        raise CloudOCRError(
            "Mistral OCR rate limit reached (429). Wait a moment and try "
            "again, or use a different OCR engine."
        )
    if response.status_code != 200:
        raise CloudOCRError(
            f"Mistral OCR request failed (HTTP {response.status_code}). "
            f"{response.text[:200]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise CloudOCRError("Mistral OCR returned an unreadable response.") from exc

    pages = data.get("pages") or []
    text = "\n\n".join(page.get("markdown", "") for page in pages if page.get("markdown"))

    if not text.strip():
        raise CloudOCRError(
            "Mistral OCR returned no text for this image. Try a clearer "
            "photo, or use a different OCR engine."
        )
    return text


# --------------------------------------------------------------------------- #
# Engine registry, for building the UI selector
# --------------------------------------------------------------------------- #

CLOUD_ENGINES = {
    "baidu": {
        "label": "Baidu Unlimited-OCR (Hugging Face, free, no key)",
        "needs_api_key": False,
        "available": baidu_ocr_available,
        "privacy_note": (
            "Sends your photo to a free community Hugging Face Space "
            "(baidu/Unlimited-OCR) for processing. May be slow or "
            "queued at busy times."
        ),
    },
    "mistral": {
        "label": "Mistral OCR (cloud, requires your API key)",
        "needs_api_key": True,
        "available": lambda: True,
        "privacy_note": (
            "Sends your photo directly to Mistral's official OCR API "
            "using your own API key (never stored). Get a key at "
            "https://console.mistral.ai/."
        ),
    },
}
