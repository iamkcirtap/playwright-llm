"""Selected-provider LLM client with bounded retries and model-specific caching.

Gemini remains the default. OpenAI Responses and Anthropic Messages use their
HTTPS APIs through the standard library, without additional SDK dependencies.
Only the selected provider receives prompts; fallback stays within that provider.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from env_loader import load_local_env

load_local_env()

PROVIDER_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
GEMINI_DEFAULT_MODELS = "gemini-2.5-flash,gemini-flash-latest,gemini-flash-lite-latest"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"


def read_bool_env(var_name: str, default: bool = False) -> bool:
    raw_value = os.getenv(var_name)
    return default if raw_value is None else raw_value.strip().lower() in {"1", "true", "yes"}


def parse_model_fallback_order(raw_value: str) -> list[str]:
    """Require explicit model names for non-default providers."""
    models = [model.strip() for model in raw_value.split(",") if model.strip()]
    if not models and LLM_PROVIDER == "gemini":
        return GEMINI_DEFAULT_MODELS.split(",")
    if not models:
        raise ValueError(f"Set LLM_MODEL to a model supported by {LLM_PROVIDER}.")
    return list(dict.fromkeys(models))


if LLM_PROVIDER not in PROVIDER_KEYS:
    raise ValueError("LLM_PROVIDER must be gemini, openai, or anthropic.")
MODEL_FALLBACK_ORDER = parse_model_fallback_order(os.getenv("LLM_MODEL", ""))
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096"))
MAX_RETRY_ATTEMPTS = int(os.getenv("LLM_MAX_RETRIES", "4"))
INITIAL_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_INITIAL_DELAY", "1"))
MAX_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_MAX_DELAY", "8"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
if DEFAULT_MAX_OUTPUT_TOKENS < 1 or MAX_RETRY_ATTEMPTS < 1 or REQUEST_TIMEOUT_SECONDS <= 0:
    raise ValueError("LLM token limit, retry count, and request timeout must be positive.")
if INITIAL_RETRY_DELAY_SECONDS < 0 or MAX_RETRY_DELAY_SECONDS < 0:
    raise ValueError("LLM retry delays must not be negative.")
IS_CI = read_bool_env("CI") or read_bool_env("GITHUB_ACTIONS")
CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", ".cache/llm"))
USE_CACHE = read_bool_env("LLM_CACHE_ENABLED", default=not IS_CI)
CACHE_VERSION = os.getenv("LLM_CACHE_VERSION", "v4")


def load_api_key() -> str:
    """Require only the selected provider's credential."""
    variable = PROVIDER_KEYS[LLM_PROVIDER]
    api_key = os.getenv(variable, "").strip()
    if not api_key:
        raise ValueError(f"{variable} environment variable is not set.")
    return api_key


def get_cache_path(cache_key: str, model_name: str, prompt: str, max_output_tokens: int) -> Path:
    """Isolate cached output by provider, actual model, prompt, and token limit."""
    identity = json.dumps([CACHE_VERSION, LLM_PROVIDER, model_name, prompt, max_output_tokens])
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    # Keep externally supplied names from escaping the cache directory.
    name = "".join(char if char.isalnum() or char in "_-" else "_" for char in cache_key)[:80]
    return CACHE_DIR / f"{LLM_PROVIDER}_{name}_{digest}.txt"


def post_json(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def request_model(model_name: str, prompt: str, max_output_tokens: int, api_key: str) -> str:
    """Normalize each provider's text response without accepting truncated code."""
    if LLM_PROVIDER == "gemini":
        # Other providers do not require the Google SDK to be importable.
        from google.genai import Client, types

        with Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=int(REQUEST_TIMEOUT_SECONDS * 1000)
        )) as client:
            response = client.models.generate_content(
                model=model_name, contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=max_output_tokens),
            )
        for candidate in getattr(response, "candidates", None) or []:
            if str(getattr(candidate, "finish_reason", "")).endswith("MAX_TOKENS"):
                raise ValueError("Gemini output was truncated; increase LLM_MAX_OUTPUT_TOKENS.")
        text = getattr(response, "text", None)
    elif LLM_PROVIDER == "openai":
        response = post_json(
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {api_key}"},
            {"model": model_name, "input": prompt, "max_output_tokens": max_output_tokens,
             "store": False},
        )
        if response.get("status") != "completed":
            raise ValueError("OpenAI response was incomplete or failed; check LLM_MAX_OUTPUT_TOKENS.")
        text = "\n".join(
            block["text"] for item in response.get("output", [])
            if item.get("type") == "message" and item.get("role") == "assistant"
            for block in item.get("content", []) if block.get("type") == "output_text"
        )
    else:
        response = post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": api_key, "anthropic-version": "2026-10-21"},
            {"model": model_name, "max_tokens": max_output_tokens,
             "messages": [{"role": "user", "content": prompt}]},
        )
        if response.get("stop_reason") != "end_turn":
            raise ValueError("Anthropic response did not finish normally; check LLM_MAX_OUTPUT_TOKENS.")
        text = "\n".join(block["text"] for block in response.get("content", [])
                         if block.get("type") == "text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{LLM_PROVIDER} returned no generated text.")
    return text.strip()


def error_status(error: Exception) -> int | None:
    """Read HTTP status codes from urllib and Google SDK exceptions."""
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status if isinstance(status, int) else None


def is_quota_exhausted_error(error: Exception) -> bool:
    if error_status(error) is not None:
        return error_status(error) == 429
    return LLM_PROVIDER == "gemini" and any(
        token in str(error).lower() for token in ("429", "quota exceeded", "resource exhausted")
    )


def is_retryable_error(error: Exception) -> bool:
    status = error_status(error)
    if status is not None:
        retryable = {408, 429, 500, 502, 503, 504}
        if LLM_PROVIDER == "openai":
            retryable.add(409)
        if LLM_PROVIDER == "anthropic":
            retryable.add(529)  # Anthropic's overloaded_error.
        return status in retryable
    if isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return True
    return LLM_PROVIDER == "gemini" and any(
        token in f"{type(error).__name__} {error}".lower() for token in
        ("connecterror", "networkerror", "rate limit", "resource exhausted", "deadline exceeded", "timeout", "timed out",
         "temporarily unavailable", "service unavailable", "internal error")
    )


def call_llm(
    prompt: str,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    cache_key: str | None = None,
) -> str:
    """Generate using one provider, with bounded retries and quota fallback."""
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive.")
    api_key = None
    for model_index, model_name in enumerate(MODEL_FALLBACK_ORDER):
        cache_path = get_cache_path(cache_key, model_name, prompt, max_output_tokens) if cache_key and USE_CACHE else None
        if cache_path and cache_path.is_file():
            cached = cache_path.read_text(encoding="utf-8").strip()
            if cached:
                print(f"Using cached response for {LLM_PROVIDER}/{model_name}.")
                return cached
        if api_key is None:
            api_key = load_api_key()
        delay = min(INITIAL_RETRY_DELAY_SECONDS, MAX_RETRY_DELAY_SECONDS)
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            print(f"Calling {LLM_PROVIDER}/{model_name} (attempt {attempt}/{MAX_RETRY_ATTEMPTS})...")
            try:
                text = request_model(model_name, prompt, max_output_tokens, api_key)
            except Exception as error:
                status = error_status(error)
                retryable = is_retryable_error(error)
                if isinstance(error, urllib.error.HTTPError):
                    error.close()
                # Do not print response bodies, prompts, or credentials in CI logs.
                if retryable and attempt < MAX_RETRY_ATTEMPTS:
                    print(f"Temporary {LLM_PROVIDER} failure (HTTP {status}); retrying in {delay:.1f}s.")
                    time.sleep(delay)
                    delay = min(delay * 2, MAX_RETRY_DELAY_SECONDS)
                    continue
                if is_quota_exhausted_error(error) and model_index + 1 < len(MODEL_FALLBACK_ORDER):
                    print(f"Quota retries exhausted for {model_name}; trying the next configured model.")
                    break
                raise RuntimeError(
                    f"{LLM_PROVIDER}/{model_name} generation failed"
                    f" (HTTP {status}). Check credentials, model access, and token limits."
                ) from error
            else:
                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(text, encoding="utf-8")
                return text
    raise RuntimeError(f"All configured {LLM_PROVIDER} models failed.")
