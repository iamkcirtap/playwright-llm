"""Generate the required Playwright specs for the assessment.

This script is the main entry point for the generation flow. It:
- loads the Swagger contract
- checks that the required endpoints exist
- generates the required API and E2E specs with the selected provider (API endpoints run in parallel)
- normalizes a few known-safe generated-code patterns before validation
- validates generated output with endpoint-specific rules
- repairs invalid output once
- saves only valid `.spec.ts` files
- runs a TypeScript compile check to catch type errors in generated code
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from prompt_loader import load_prompt, build_prompt
from llm_client import call_llm
from swagger_loader import (
    resolve_swagger_source,
    load_swagger_spec_dict,
    extract_api_endpoints,
    extract_endpoint_spec,
    extract_response_expectations,
)
import validator

BASE_PROMPT_NAME = "core_context"
API_TESTS_DIR = pathlib.Path("tests") / "api"
WEB_TESTS_DIR = pathlib.Path("tests") / "web"
REQUIRED_API_ENDPOINTS = [
    "/api/checkout",
    "/api/validate-card",
    "/api/validate-email",
]
CHECKOUT_E2E_PLAN = {
    "flow": "checkout",
    "path": "/",
    "inputSelectors": {
        field: f'input[name="{field}"]'
        for field in ["email", "cardNumber", "expiry", "cvv", "amount"]
    },
    "submitSelector": 'button[type="submit"]',
    "successText": "✅ Payment processed successfully!",
    "requiredFields": ["email", "cardNumber", "expiry", "cvv", "amount"],
    "sampleValues": {
        "email": "buyer@example.com",
        "cardNumber": "4242424242424242",
        "expiry": "12/34",
        "cvv": "123",
        "amount": "100.00",
    },
}
DETERMINISTIC_PAYLOADS = {
    "/api/checkout": {
        "cardNumber": "4242424242424242",
        "expiry": "12/34",
        "cvv": "123",
        "amount": 1000,
    },
    "/api/validate-card": {
        "cardNumber": "4242424242424242",
    },
    "/api/validate-email": {
        "email": "buyer@example.com",
    },
}


def read_bool_env(var_name: str, default: bool = False) -> bool:
    """Read a boolean-like env value such as 1/true/yes."""
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes"}


IS_CI = read_bool_env("CI") or read_bool_env("GITHUB_ACTIONS")
FORCE_REGENERATE = read_bool_env("FORCE_REGENERATE", default=IS_CI)
STRICT_GENERATION = read_bool_env("STRICT_GENERATION", default=IS_CI)


def main() -> None:
    """Run the end-to-end generation workflow."""
    cli_args = parse_cli_args()
    swagger_source = resolve_swagger_source(cli_args.swagger_source)
    swagger_spec_dict = load_swagger_spec_dict(swagger_source)
    allowed_api_endpoints = extract_api_endpoints(swagger_spec_dict)
    ensure_required_endpoints_exist(allowed_api_endpoints)

    generate_api_tests(swagger_spec_dict, allowed_api_endpoints)
    generate_e2e_tests()
    run_typescript_compile_check()

    print("Test case generation completed successfully.")


def parse_cli_args() -> argparse.Namespace:
    """Parse command-line options for this script.

    Keeping argument parsing in this file makes the execution flow easier to
    follow for beginners.
    """
    parser = argparse.ArgumentParser(
        description="Generate Playwright tests from Swagger and prompts."
    )
    parser.add_argument(
        "--swagger",
        dest="swagger_source",
        help="Path or URL to the Swagger/OpenAPI JSON file.",
    )
    return parser.parse_args()


def ensure_required_endpoints_exist(allowed_api_endpoints: set[str]) -> None:
    """Fail fast if Swagger does not include the required assessment routes."""
    missing_endpoints = [
        endpoint
        for endpoint in REQUIRED_API_ENDPOINTS
        if endpoint not in allowed_api_endpoints
    ]
    if missing_endpoints:
        raise ValueError(
            "Swagger is missing required endpoints: "
            + ", ".join(missing_endpoints)
        )


def generate_api_tests(swagger_spec_dict: dict, allowed_api_endpoints: set[str]) -> None:
    """Generate one API spec per required endpoint, running endpoints in parallel."""
    with ThreadPoolExecutor(max_workers=len(REQUIRED_API_ENDPOINTS)) as executor:
        futures = {
            executor.submit(
                generate_one_api_test,
                endpoint,
                swagger_spec_dict,
                allowed_api_endpoints,
            ): endpoint
            for endpoint in REQUIRED_API_ENDPOINTS
        }
        for future in as_completed(futures):
            future.result()  # re-raises any exception from the worker


def generate_one_api_test(
    endpoint: str,
    swagger_spec_dict: dict,
    allowed_api_endpoints: set[str],
) -> None:
    """Generate, validate, and save one API spec for a single endpoint."""
    existing_file_path = get_api_test_file_path(endpoint)
    endpoint_spec = extract_endpoint_spec(swagger_spec_dict, endpoint)
    expectations = extract_response_expectations(swagger_spec_dict, endpoint)
    endpoint_spec["validation_expectations"] = expectations

    if should_reuse_existing_spec(
        existing_file_path,
        allowed_api_endpoints=allowed_api_endpoints,
        log_name=endpoint,
        api_expectations=expectations,
    ):
        return

    payload = DETERMINISTIC_PAYLOADS[endpoint]
    test_code = generate_with_llm_guard(
        f"endpoint '{endpoint}'",
        lambda: generate_api_test(endpoint_spec, payload),
    )

    validated_code = validate_generated_spec(
        test_code,
        api_expectations=expectations,
        allowed_api_endpoints=allowed_api_endpoints,
        generation_context=build_api_generation_prompt(endpoint_spec, payload),
    )
    if validated_code is None:
        handle_generation_failure(
            existing_file_path,
            f"API test generation for endpoint '{endpoint}' failed after validation/repair.",
        )
        return

    save_spec_file(existing_file_path, validated_code)


def generate_api_test(endpoint_spec: dict, payload: dict) -> str:
    """Build the API prompt for one endpoint and ask the selected provider for a spec file."""
    prompt = build_api_generation_prompt(endpoint_spec, payload)
    endpoint_cache_key = endpoint_spec["endpoint"].strip("/").replace("/", "_")
    return call_llm(prompt, cache_key=f"api_{endpoint_cache_key}")


def build_api_generation_prompt(endpoint_spec: dict, payload: dict) -> str:
    """Share the original API requirements between generation and repair."""
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    api_prompt = load_prompt("api_test_generation")

    return build_prompt(
        base_prompt,
        api_prompt,
        {
            "ENDPOINT": endpoint_spec["endpoint"],
            "ENDPOINT_SPEC": json.dumps(endpoint_spec, indent=2),
            "PAYLOAD": json.dumps(payload, indent=2),
        },
    )


def generate_e2e_tests() -> None:
    """Generate the single required checkout E2E spec."""
    existing_file_path = get_e2e_test_file_path(CHECKOUT_E2E_PLAN["flow"])

    if should_reuse_existing_spec(
        existing_file_path,
        require_e2e_structure=True,
        log_name=f"E2E flow '{CHECKOUT_E2E_PLAN['flow']}'",
    ):
        return

    test_code = generate_with_llm_guard(
        f"E2E flow '{CHECKOUT_E2E_PLAN['flow']}'",
        lambda: generate_e2e_test(CHECKOUT_E2E_PLAN),
    )

    validated_code = validate_generated_spec(
        test_code,
        require_e2e_structure=True,
        generation_context=build_e2e_generation_prompt(CHECKOUT_E2E_PLAN),
    )
    if validated_code is None:
        handle_generation_failure(
            existing_file_path,
            f"E2E test generation for '{CHECKOUT_E2E_PLAN['flow']}' failed after validation/repair.",
        )
        return

    save_spec_file(existing_file_path, validated_code)


def generate_with_llm_guard(target_name: str, generator: Callable[[], str]) -> str:
    """Wrap LLM calls with a clear, target-specific failure message."""
    try:
        return generator()
    except Exception as llm_error:
        raise RuntimeError(f"LLM call failed for {target_name}: {llm_error}") from llm_error


def generate_e2e_test(e2e_test_plan: dict) -> str:
    """Build the E2E prompt and ask the selected provider for a checkout spec file."""
    prompt = build_e2e_generation_prompt(e2e_test_plan)
    return call_llm(prompt, cache_key=f"e2e_{e2e_test_plan['flow']}")


def build_e2e_generation_prompt(e2e_test_plan: dict) -> str:
    """Share the original checkout plan between generation and repair."""
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    e2e_prompt = load_prompt("e2e_test_generation")

    return build_prompt(base_prompt, e2e_prompt, {"E2E_PLAN": json.dumps(e2e_test_plan, ensure_ascii=False)})


def save_spec_file(file_path: pathlib.Path, test_code: str) -> None:
    """Write generated test code to disk."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(test_code)


def run_typescript_compile_check() -> None:
    """Fail fast when generated specs introduce TypeScript compile errors."""
    npx_executable = shutil.which("npx") or shutil.which("npx.cmd")
    if npx_executable:
        command = [npx_executable, "tsc", "--noEmit"]
    else:
        local_tsc = pathlib.Path("node_modules/.bin/tsc.cmd")
        if not local_tsc.exists():
            local_tsc = pathlib.Path("node_modules/.bin/tsc")
        if not local_tsc.exists():
            raise RuntimeError(
                "TypeScript compile check could not find npx or a local tsc binary."
            )
        command = [str(local_tsc), "--noEmit"]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=pathlib.Path.cwd(),
    )
    if result.returncode == 0:
        return

    compiler_output = (result.stdout or result.stderr).strip()
    raise RuntimeError(
        "Generated specs failed the TypeScript compile check.\n"
        f"{compiler_output}"
    )


def validate_generated_spec(
    test_code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
    api_expectations: dict | None = None,
    generation_context: str = "",
) -> str | None:
    """Run validation with one repair attempt and return final code or None.

    Validation enforces route allowlists plus endpoint-specific API assertions
    or the required checkout-flow structure for E2E specs.
    """
    normalized_code = normalize_generated_import_paths(test_code)

    return validator.validate_and_repair_test_cases(
        normalized_code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
        api_expectations=api_expectations,
        generation_context=generation_context,
    )


def normalize_generated_import_paths(test_code: str) -> str:
    """Normalize a small set of safe, common generated-code mistakes."""
    normalized_code = test_code
    replacements = {
        "from '../utils/": "from '../../utils/",
        'from "../utils/': 'from "../../utils/',
    }
    for old_value, new_value in replacements.items():
        normalized_code = normalized_code.replace(old_value, new_value)

    # Remove a common invalid E2E pattern where the model instantiates
    # ApiHelper without the required request context.
    if "new ApiHelper();" in normalized_code:
        normalized_code = re.sub(
            r"^\s*import\s*\{\s*ApiHelper\s*\}\s*from\s*['\"]\.\./\.\./utils/api-helper['\"];\s*\n?",
            "",
            normalized_code,
            flags=re.MULTILINE,
        )
        normalized_code = re.sub(
            r"^\s*const\s+apiHelper\s*=\s*new\s+ApiHelper\(\);\s*\n?",
            "",
            normalized_code,
            flags=re.MULTILINE,
        )

    return normalized_code


def handle_generation_failure(file_path: pathlib.Path, message: str) -> None:
    """Fail strictly in CI and avoid silently reusing stale artifacts there."""
    if STRICT_GENERATION:
        if FORCE_REGENERATE and file_path.exists():
            file_path.unlink()
        raise RuntimeError(message)

    print(message)


def should_reuse_existing_spec(
    file_path: pathlib.Path,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
    log_name: str = "spec",
    api_expectations: dict | None = None,
) -> bool:
    """Return True when an existing file is valid and can be reused."""
    if FORCE_REGENERATE or not file_path.is_file():
        return False

    existing_code = file_path.read_text(encoding="utf-8")
    is_valid = validator.validate_test_cases(
        existing_code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
        api_expectations=api_expectations,
    )
    if is_valid:
        print(f"Skipping regeneration for '{log_name}' because an existing valid spec already exists.")
        return True
    return False


def get_api_test_file_path(endpoint: str) -> pathlib.Path:
    """Convert an API route into its target spec file path."""
    file_name = endpoint.strip("/").replace("/", "_") + ".spec.ts"
    return API_TESTS_DIR / file_name


def get_e2e_test_file_path(test_name: str) -> pathlib.Path:
    """Convert an E2E flow name into its target spec file path."""
    file_name = test_name.strip().replace(" ", "_").lower() + ".spec.ts"
    return WEB_TESTS_DIR / file_name


if __name__ == "__main__":
    main()
