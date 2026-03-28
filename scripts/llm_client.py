"""Small Gemini client wrapper used by the generator.

This module keeps the LLM integration simple by handling:
- API key loading
- retry-with-backoff for temporary failures
- versioned file-based caching for repeated runs
"""

import os
import time
from pathlib import Path
from typing import Any

from google.genai import Client, types

MODEL_NAME = "gemini-2.5-flash"
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096"))
MAX_RETRY_ATTEMPTS = int(os.getenv("LLM_MAX_RETRIES", "4"))
INITIAL_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_INITIAL_DELAY", "1"))
MAX_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_MAX_DELAY", "8"))
CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", ".cache/llm"))
USE_CACHE = os.getenv("LLM_CACHE_ENABLED", "true").lower() in {"1", "true", "yes"}
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
    before calling the API.
    """
    cached_response = load_cached_response(cache_key)
    if cached_response is not None:
        return cached_response.strip()

    client = Client(api_key=load_api_key())
    config = types.GenerateContentConfig(max_output_tokens=max_output_tokens)

    delay_seconds = INITIAL_RETRY_DELAY_SECONDS

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            if cache_key:
                print(f"Generating '{cache_key}' with Gemini (attempt {attempt}/{MAX_RETRY_ATTEMPTS})...")
            else:
                print(f"Calling Gemini (attempt {attempt}/{MAX_RETRY_ATTEMPTS})...")
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )
            response_text = extract_response(response).strip()
            save_cached_response(cache_key, response_text=response_text)
            return response_text
        except Exception as error:
            if not is_retryable_error(error) or attempt == MAX_RETRY_ATTEMPTS:
                print(f"LLM request failed and will not be retried: {error}")
                raise

            print(
                f"LLM error detected ({error}). "
                f"Retrying in {delay_seconds:.1f} seconds..."
            )
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, MAX_RETRY_DELAY_SECONDS)


def extract_response(response: Any) -> str:
    """Pull the generated text from the Gemini SDK response object."""
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Failed to extract generated text from LLM response.")
    return text


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
