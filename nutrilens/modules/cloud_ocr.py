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

======================================================================
FUTURE-PROOFING / MAINTENANCE NOTES -- read this if either engine stops
working, since both are third-party services this app doesn't control:
======================================================================

**Baidu Unlimited-OCR** is a community demo; its API name, parameter
names, and even its existence can change without notice. This module
does NOT rely solely on a single hardcoded call shape:
  1. It first tries the known-good call recorded in `_BAIDU_KNOWN_CALL`
     below (api_name="/run_ocr", params image_path/mode/prompt).
  2. If that raises anything at all, it falls back to
     `_discover_and_call_baidu_endpoint()`, which asks the Space itself
     (via `client.view_api()`) what endpoints currently exist, picks the
     one that looks most like an OCR endpoint, and matches its
     parameters by label (looking for "image"/"file" for the photo,
     "mode" for the resolution mode, "prompt"/"instruction" for the
     prompt) rather than assuming exact parameter names.
  3. If discovery also fails, a single clear CloudOCRError is raised
     explaining both attempts failed, with a link to check the Space's
     current API page.
If the Space changes its OCR behavior in a way this can't auto-adapt to
(e.g. a completely different response shape), update `_BAIDU_KNOWN_CALL`
and `_extract_text_from_gradio_result()` below to match.

**Mistral OCR** ties to a specific model ID
(`_MISTRAL_MODEL_CANDIDATES[0]`). Mistral periodically releases newer OCR
model versions and may eventually retire older ones. If the primary
model ID is rejected (HTTP 400/404, "model not found"-type errors), this
module automatically retries with each subsequent entry in
`_MISTRAL_MODEL_CANDIDATES`, and remembers whichever one worked for the
rest of the process so later calls don't repeat the failed attempts.
Check https://docs.mistral.ai/capabilities/OCR/basic_ocr/ periodically
and add new model IDs to the front of that list as they're released.
Response parsing (`_extract_text_from_mistral_response()`) also checks a
few alternate key names in case Mistral changes their response schema,
not just the one documented shape.

Design goals shared with the rest of the OCR pipeline:
- Never crash the app: any failure (missing dependency, network error,
  timeout, bad API key, malformed response, changed upstream API) raises
  a `CloudOCRError` with a clear, user-facing message, which the UI
  catches and turns into a friendly warning + fallback suggestion.
- Return plain text, exactly like the local OCR path, so the *same*
  `parse_nutrition_text()` field-parsing logic (English + Japanese,
  full nutrient panel) works regardless of which engine produced it.

IMPORTANT HONESTY NOTE: neither integration could be exercised against
the live services while building this, because this development
environment's network access doesn't extend to huggingface.co, *.hf.space,
or api.mistral.ai. The request-building, response-parsing, and fallback
logic below is implemented directly from each service's own published
source/docs and is unit-tested against realistic mocked responses (see
tests/test_cloud_ocr.py) -- including simulated "the API changed"
scenarios to verify the fallback paths actually engage -- but genuinely
exercising it against the live services is worth doing once deployed.
"""

from __future__ import annotations

import base64
import os
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


def _first_nonempty_string(*candidates) -> str:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c
    return ""


# --------------------------------------------------------------------------- #
# Backend 1: baidu/Unlimited-OCR (Hugging Face Space, no API key)
# --------------------------------------------------------------------------- #

BAIDU_SPACE_ID = "baidu/Unlimited-OCR"

# The last confirmed-working call shape (see MAINTENANCE notes above). If
# the Space's API changes, `_discover_and_call_baidu_endpoint` below is
# tried automatically as a fallback before giving up.
_BAIDU_KNOWN_API_NAME = "/run_ocr"
_BAIDU_KNOWN_PARAM_NAMES = {"image": "image_path", "mode": "mode", "prompt": "prompt"}
_BAIDU_DEFAULT_PROMPT = "document parsing."

# Remembers whichever call strategy last worked ("known" or "discovered")
# for this process, so repeated calls don't re-attempt a strategy that's
# already been confirmed broken this session.
_baidu_working_strategy = None


def baidu_ocr_available() -> bool:
    return _HAS_GRADIO_CLIENT


def _extract_text_from_gradio_result(result) -> str:
    """Pull plain text out of whatever shape a Gradio endpoint returned.
    Handles the documented shape ({"text": ..., "done": ...}) as well as
    a few plausible alternates, so a future response-format change
    doesn't automatically break this -- see MAINTENANCE notes above."""
    # Multiple outputs come back as a tuple/list; look through each for
    # something usable rather than assuming position 0.
    if isinstance(result, (tuple, list)):
        for item in result:
            text = _extract_text_from_gradio_result(item)
            if text:
                return text
        return ""

    if isinstance(result, dict):
        for key in ("text", "output", "result", "markdown", "content"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ""

    if isinstance(result, str):
        return result

    return ""


def _call_baidu_known_api(client, tmp_path: str, mode: str, prompt: str):
    kwargs = {
        _BAIDU_KNOWN_PARAM_NAMES["image"]: handle_file(tmp_path),
        _BAIDU_KNOWN_PARAM_NAMES["mode"]: mode,
        _BAIDU_KNOWN_PARAM_NAMES["prompt"]: prompt,
    }
    return client.predict(api_name=_BAIDU_KNOWN_API_NAME, **kwargs)


def _discover_and_call_baidu_endpoint(client, tmp_path: str, mode: str, prompt: str):
    """Fallback used when the known call shape fails: ask the Space what
    endpoints it currently exposes, pick the one that looks most like an
    OCR endpoint, and match its parameters by label rather than assuming
    fixed names. This lets the integration keep working through minor
    API renames without a code change."""
    api_info = client.view_api(print_info=False, return_format="dict")
    named_endpoints = (api_info or {}).get("named_endpoints", {}) or {}
    if not named_endpoints:
        raise CloudOCRError(
            "baidu/Unlimited-OCR's API couldn't be introspected (no "
            "named endpoints found) -- the Space's interface may have "
            "changed significantly. Check "
            f"https://huggingface.co/spaces/{BAIDU_SPACE_ID}?view=api"
        )

    ocr_like = [name for name in named_endpoints if "ocr" in name.lower()]
    candidate_names = ocr_like or list(named_endpoints.keys())

    last_error = None
    for endpoint_name in candidate_names:
        params = named_endpoints[endpoint_name].get("parameters", [])
        kwargs = {}
        for p in params:
            label = (p.get("label") or p.get("parameter_name") or "").lower()
            if any(k in label for k in ("image", "file", "photo", "img")):
                kwargs[p.get("parameter_name", p.get("label"))] = handle_file(tmp_path)
            elif "mode" in label or "resolution" in label:
                kwargs[p.get("parameter_name", p.get("label"))] = mode
            elif any(k in label for k in ("prompt", "instruction", "query", "text")):
                kwargs[p.get("parameter_name", p.get("label"))] = prompt

        if not kwargs:
            continue  # this endpoint doesn't look like it takes an image; skip

        try:
            return client.predict(api_name=endpoint_name, **kwargs)
        except Exception as exc:
            last_error = exc
            continue

    detail = f" Last error: {last_error}" if last_error else ""
    raise CloudOCRError(
        "Couldn't find a working OCR endpoint on baidu/Unlimited-OCR -- "
        "its API may have changed. Check "
        f"https://huggingface.co/spaces/{BAIDU_SPACE_ID}?view=api and "
        f"update modules/cloud_ocr.py accordingly.{detail}"
    )


def run_baidu_unlimited_ocr(image: Image.Image, mode: str = "gundam", timeout: int = 90) -> str:
    """Run OCR via the baidu/Unlimited-OCR Hugging Face Space.

    `mode`: "gundam" (faster, 640px crop) or "base" (slower, more
    accurate at 1024px) -- these are the two modes the Space itself
    exposes as of this writing.

    This Space runs on HF's shared ZeroGPU pool: as an anonymous
    (non-logged-in) caller, expect queueing delays and occasional
    unavailability at busy times -- this is a free community resource,
    not a guaranteed-uptime service.

    Tries the known-good call shape first, then falls back to runtime
    endpoint discovery if that fails (see module MAINTENANCE notes).
    Raises CloudOCRError on total failure.
    """
    global _baidu_working_strategy

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
    except Exception as exc:
        raise CloudOCRError(
            f"Couldn't reach the baidu/Unlimited-OCR service ({exc}). "
            "It may be busy, rate-limiting anonymous requests, or "
            "temporarily down -- try again shortly, or use a different "
            "OCR engine."
        ) from exc

    try:
        result = None
        strategies = (
            [_call_baidu_known_api, _discover_and_call_baidu_endpoint]
            if _baidu_working_strategy != "discovered"
            else [_discover_and_call_baidu_endpoint, _call_baidu_known_api]
        )
        errors = []
        for strategy in strategies:
            try:
                result = strategy(client, tmp_path, mode, _BAIDU_DEFAULT_PROMPT)
                _baidu_working_strategy = (
                    "known" if strategy is _call_baidu_known_api else "discovered"
                )
                break
            except CloudOCRError:
                raise  # discovery already produced a clear final message
            except Exception as exc:
                errors.append(str(exc))
                continue

        if result is None:
            raise CloudOCRError(
                "Couldn't reach baidu/Unlimited-OCR with either the known API "
                "shape or by discovering its current one -- it may be busy, "
                "rate-limiting anonymous requests, or its API has changed. "
                f"Details: {'; '.join(errors)}"
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass  # best-effort cleanup; not worth failing the request over

    text = _extract_text_from_gradio_result(result)
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

# Ordered fallback chain of OCR model IDs to try. The first is the
# current model per Mistral's published docs; add newer IDs to the
# *front* of this list as Mistral releases them, and leave older ones
# in place as a safety net for as long as Mistral keeps them live. See
# MAINTENANCE notes above.
_MISTRAL_MODEL_CANDIDATES = ["mistral-ocr-2512", "mistral-ocr-latest"]
_mistral_working_model = None  # cached for the rest of the process once found

MISTRAL_REQUEST_TIMEOUT_SECONDS = 60


def _model_rejected(response: requests.Response) -> bool:
    """Heuristic for 'this model ID isn't valid/available', as distinct
    from other 400-class errors (bad request shape, invalid image,
    etc.) -- checked so the model-fallback chain only advances for the
    right reason instead of masking unrelated request errors."""
    if response.status_code not in (400, 404):
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    message = str(body.get("message") or body.get("error") or "").lower()
    return "model" in message and (
        "not found" in message or "invalid" in message or "does not exist" in message
    )


def _extract_text_from_mistral_response(data: dict) -> str:
    """Pull OCR text out of Mistral's response. Handles the documented
    `{"pages": [{"markdown": ...}, ...]}` shape, plus a couple of
    plausible alternates in case the schema changes -- see MAINTENANCE
    notes above."""
    pages = data.get("pages")
    if isinstance(pages, list) and pages:
        texts = [
            _first_nonempty_string(p.get("markdown"), p.get("text"), p.get("content"))
            for p in pages
            if isinstance(p, dict)
        ]
        texts = [t for t in texts if t]
        if texts:
            return "\n\n".join(texts)

    # Alternate possible top-level shapes if Mistral changes their schema.
    return _first_nonempty_string(data.get("text"), data.get("content"), data.get("result"))


def _post_mistral_ocr(image: Image.Image, api_key: str, model: str, timeout: int) -> requests.Response:
    data_uri = _image_to_data_uri(image)
    payload = {
        "model": model,
        "document": {"type": "image_url", "image_url": data_uri},
        "include_image_base64": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    return requests.post(MISTRAL_OCR_URL, json=payload, headers=headers, timeout=timeout)


def run_mistral_ocr(image: Image.Image, api_key: str, timeout: int = MISTRAL_REQUEST_TIMEOUT_SECONDS) -> str:
    """Run OCR via Mistral's official cloud OCR API, using the person's
    own Mistral API key (never stored -- passed in per-call from the UI's
    session-only password field).

    Get a key at https://console.mistral.ai/

    Automatically falls back through `_MISTRAL_MODEL_CANDIDATES` if the
    current model ID is rejected as unknown/unavailable, so a future
    Mistral model rename/retirement doesn't immediately break this.

    Raises CloudOCRError on any failure (missing/invalid key, network
    error, timeout, malformed response, all model candidates rejected),
    with a message safe to show directly to the user.
    """
    global _mistral_working_model

    if not api_key or not api_key.strip():
        raise CloudOCRError(
            "A Mistral API key is required for this engine. Get one at "
            "https://console.mistral.ai/, or use a different OCR engine "
            "that doesn't need one."
        )

    models_to_try = (
        [_mistral_working_model] + [m for m in _MISTRAL_MODEL_CANDIDATES if m != _mistral_working_model]
        if _mistral_working_model
        else list(_MISTRAL_MODEL_CANDIDATES)
    )

    last_response = None
    for model in models_to_try:
        try:
            response = _post_mistral_ocr(image, api_key, model, timeout)
        except requests.exceptions.Timeout as exc:
            raise CloudOCRError(
                "Mistral OCR timed out. Try again, or use a different OCR engine."
            ) from exc
        except Exception as exc:
            raise CloudOCRError(f"Couldn't reach Mistral's OCR API ({exc}).") from exc

        if response.status_code == 200:
            _mistral_working_model = model
            break

        last_response = response
        if _model_rejected(response):
            continue  # try the next candidate model ID
        break  # a non-model-related error; no point trying other models
    else:
        response = last_response

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
        hint = (
            " All known model IDs were rejected -- Mistral may have "
            "renamed or retired their OCR model; check "
            "https://docs.mistral.ai/capabilities/OCR/basic_ocr/ and "
            "update _MISTRAL_MODEL_CANDIDATES in modules/cloud_ocr.py."
            if _model_rejected(response)
            else ""
        )
        raise CloudOCRError(
            f"Mistral OCR request failed (HTTP {response.status_code}). "
            f"{response.text[:200]}{hint}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise CloudOCRError("Mistral OCR returned an unreadable response.") from exc

    text = _extract_text_from_mistral_response(data)
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

