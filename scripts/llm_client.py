import os
import time
from typing import Any

from google.genai import Client, types

MODEL_NAME = "gemini-2.5-flash"
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096"))
MAX_RETRY_ATTEMPTS = int(os.getenv("LLM_MAX_RETRIES", "4"))
INITIAL_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_INITIAL_DELAY", "1"))
MAX_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_MAX_DELAY", "8"))


# Load the Gemini API key from environment variable
def load_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    return api_key

client = Client(api_key=load_api_key())


# Build the request payload for calling the LLM
def build_request(prompt: str, max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS) -> dict[str, Any]:
    # build the SDK request payload for calling the LLM
    return {
        "model": MODEL_NAME,
        "contents": prompt,
        "config": types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
        ),
    }


# Call the LLM with the provided prompt and return the generated response
def call_llm(prompt: str, max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS) -> str:
    # call the Gemini model with the provided prompt and return the generated response
    print("Loading Gemini API key...")
    load_api_key()

    print(f"Calling LLM with prompt: {prompt}")
    request = build_request(prompt, max_output_tokens=max_output_tokens)

    delay_seconds = INITIAL_RETRY_DELAY_SECONDS

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            print(f"Sending request to Gemini API (attempt {attempt}/{MAX_RETRY_ATTEMPTS})...")
            response = client.models.generate_content(
                model=request["model"],
                contents=request["contents"],
                config=request["config"],
            )
            print("Received response from Gemini API.")
            return extract_response(response).strip()
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


# Extract the generated text from the LLM response
def extract_response(response: Any) -> str:
    # extract the generated text from the response object
    text = getattr(response, "text", None)
    print(f"Extracted text from response: {text}")
    if not text:
        raise ValueError("Failed to extract generated text from LLM response.")
    return text


def is_retryable_error(error: Exception) -> bool:
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
