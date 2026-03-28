"""Small Gemini client wrapper used by the generator.

This module keeps the LLM integration simple by handling:
- API key loading
- model fallback order when quota is exhausted
- retry-with-backoff for temporary failures
- versioned file-based caching for repeated runs

The cache is intentionally readable and lightweight so prompt-strategy changes
can be managed by bumping `LLM_CACHE_VERSION`.
"""

import os
import time
from pathlib import Path
from typing import Any

from google.genai import Client, types
from env_loader import load_local_env


# Load local .env values for local runs before reading os.getenv defaults.
load_local_env()


def read_bool_env(var_name: str, default: bool = False) -> bool:
    """Read a boolean-like env value such as 1/true/yes."""
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes"}


def parse_model_fallback_order(raw_value: str) -> list[str]:
    """Parse a comma-separated model list into a cleaned ordered list."""
    models = [model.strip() for model in raw_value.split(",") if model.strip()]
    if not models:
        return ["gemini-2.5-flash"]
    return models


MODEL_FALLBACK_ORDER = parse_model_fallback_order(
    os.getenv("LLM_MODEL", "gemini-2.5-flash,gemini-flash-latest,gemini-flash-lite-latest")
)
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096"))
MAX_RETRY_ATTEMPTS = int(os.getenv("LLM_MAX_RETRIES", "4"))
INITIAL_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_INITIAL_DELAY", "1"))
MAX_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_MAX_DELAY", "8"))
IS_CI = read_bool_env("CI") or read_bool_env("GITHUB_ACTIONS")
CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", ".cache/llm"))
USE_CACHE = read_bool_env("LLM_CACHE_ENABLED", default=not IS_CI)
CACHE_VERSION = os.getenv("LLM_CACHE_VERSION", "v1")


def load_api_key() -> str:
    """Read the Gemini API key from the environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    return api_key


def get_cache_path(cache_key: str) -> Path:
    """Build the file path for a cached LLM response."""
    return CACHE_DIR / f"{cache_key}_{CACHE_VERSION}.txt"


def load_cached_response(cache_key: str | None) -> str | None:
    """Return a cached response when caching is enabled and a file exists."""
    if not USE_CACHE:
        return None
    if not cache_key:
        return None

    cache_path = get_cache_path(cache_key)
    if not cache_path.is_file():
        return None

    print(f"Using cached response: {cache_path.name}")
    return cache_path.read_text(encoding="utf-8")


def save_cached_response(cache_key: str | None, response_text: str) -> None:
    """Persist an LLM response to the local cache when enabled."""
    if not USE_CACHE:
        return
    if not cache_key:
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cache_path(cache_key)
    cache_path.write_text(response_text, encoding="utf-8")


def call_llm(
    prompt: str,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    cache_key: str | None = None,
) -> str:
    """Send a prompt to Gemini and return text output.

    If a cache key is provided, the module will try to reuse a cached response
    before calling the API. When quota-style errors happen, it can fall back to
    the next model in `LLM_MODEL` order.
    """
    cached_response = load_cached_response(cache_key)
    if cached_response is not None:
        return cached_response.strip()

    client = Client(api_key=load_api_key())
    config = types.GenerateContentConfig(max_output_tokens=max_output_tokens)

    last_error: Exception | None = None

    for model_index, model_name in enumerate(MODEL_FALLBACK_ORDER):
        next_model_name = None
        if model_index < len(MODEL_FALLBACK_ORDER) - 1:
            next_model_name = MODEL_FALLBACK_ORDER[model_index + 1]

        try:
            response_text = request_with_model_retries(
                client=client,
                config=config,
                prompt=prompt,
                cache_key=cache_key,
                model_name=model_name,
                next_model_name=next_model_name,
            )
            if response_text is not None:
                save_cached_response(cache_key, response_text=response_text)
                return response_text
        except Exception as error:
            last_error = error
            raise

    if last_error is not None:
        raise RuntimeError(
            "All configured Gemini models failed after retries. "
            f"Models tried: {', '.join(MODEL_FALLBACK_ORDER)}"
        ) from last_error

    # Defensive fallback for static analysis; normal control flow should
    # already return in try-blocks or raise in the final retry.
    raise RuntimeError("LLM request ended without producing a response.")


def extract_response(response: Any) -> str:
    """Pull the generated text from the Gemini SDK response object."""
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Failed to extract generated text from LLM response.")
    return text


def log_model_attempt(cache_key: str | None, model_name: str, attempt: int) -> None:
    """Log request details for one model attempt."""
    if cache_key:
        print(
            f"Generating '{cache_key}' with Gemini model '{model_name}' "
            f"(attempt {attempt}/{MAX_RETRY_ATTEMPTS})..."
        )
        return

    print(
        f"Calling Gemini model '{model_name}' "
        f"(attempt {attempt}/{MAX_RETRY_ATTEMPTS})..."
    )


def request_with_model_retries(
    client: Client,
    config: types.GenerateContentConfig,
    prompt: str,
    cache_key: str | None,
    model_name: str,
    next_model_name: str | None,
) -> str | None:
    """Try one model with retries and return None if fallback should be used."""
    delay_seconds = INITIAL_RETRY_DELAY_SECONDS

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            log_model_attempt(cache_key, model_name, attempt)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return extract_response(response).strip()
        except Exception as error:
            if is_quota_exhausted_error(error) and next_model_name:
                print(
                    f"Model '{model_name}' appears quota-limited ({error}). "
                    f"Falling back to '{next_model_name}'."
                )
                return None

            if not is_retryable_error(error) or attempt == MAX_RETRY_ATTEMPTS:
                print(f"LLM request failed and will not be retried: {error}")
                raise

            print(
                f"LLM error detected ({error}). "
                f"Retrying in {delay_seconds:.1f} seconds..."
            )
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, MAX_RETRY_DELAY_SECONDS)

    return None


def is_retryable_error(error: Exception) -> bool:
    """Check whether an exception looks temporary and worth retrying."""
    message = str(error).lower()
    retryable_markers = [
        "429",
        "rate limit",
        "resource exhausted",
        "deadline exceeded",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "service unavailable",
        "unavailable",
        "internal error",
    ]
    return any(marker in message for marker in retryable_markers)


def is_quota_exhausted_error(error: Exception) -> bool:
    """Check whether the error appears to be a request quota exhaustion."""
    message = str(error).lower()
    quota_markers = [
        "429",
        "quota exceeded",
        "resource exhausted",
        "free_tier_requests",
    ]
    return any(marker in message for marker in quota_markers)
