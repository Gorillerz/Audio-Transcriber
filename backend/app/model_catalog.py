"""Fetch and cache OpenRouter model labels and token pricing for pipeline editing."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from .workflows import openrouter_key

_cache_lock = threading.Lock()
_cached_models: list[dict] | None = None


def _publisher(model_id: str) -> str:
    """Derive a readable publisher label from OpenRouter's author/model ID."""
    author = model_id.split("/", 1)[0]
    return " ".join(part.capitalize() for part in author.replace("_", "-").split("-"))


def _per_million(value: object) -> float | None:
    """Convert OpenRouter's per-token USD price to a per-million-token price."""
    try:
        return float(value) * 1_000_000
    except (TypeError, ValueError):
        return None


def list_openrouter_models() -> list[dict]:
    """Return a process-cached model catalog, fetching OpenRouter only once."""
    global _cached_models
    if _cached_models is not None:
        return _cached_models
    with _cache_lock:
        if _cached_models is not None:
            return _cached_models
        headers = {"Accept": "application/json"}
        api_key, _ = openrouter_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request("https://openrouter.ai/api/v1/models?sort=newest", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"OpenRouter model catalog returned HTTP {error.code}.") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"Could not reach OpenRouter model catalog: {getattr(error, 'reason', error)}") from error
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("OpenRouter returned an unexpected model catalog response.")
        models = []
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
            model_id = str(item["id"])
            models.append({
                "id": model_id,
                "name": str(item.get("name") or model_id),
                "publisher": _publisher(model_id),
                "created": int(item.get("created") or 0),
                "input_cost_per_million": _per_million(pricing.get("prompt")),
                "output_cost_per_million": _per_million(pricing.get("completion")),
            })
        # Preserve OpenRouter's newest-first response order for later client-side filtering.
        _cached_models = models
        return _cached_models
