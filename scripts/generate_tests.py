"""Generate the required Playwright specs for the assessment.

This script is the main entry point for the generation flow. It:
- loads the Swagger contract
- checks that the required endpoints exist
- generates the required API and E2E specs with Gemini
- validates generated output
- repairs invalid output once
- saves only valid `.spec.ts` files
"""

import json
import os
import pathlib

from prompt_loader import load_prompt, build_prompt
from llm_client import call_llm
from swagger_loader import (
    resolve_swagger_source,
    load_swagger_spec_dict,
    extract_api_endpoints,
    extract_endpoint_spec,
)
import validator

BASE_PROMPT_NAME = "base_lean"
API_TESTS_DIR = pathlib.Path("tests") / "api"
WEB_TESTS_DIR = pathlib.Path("tests") / "web"
FORCE_REGENERATE = os.getenv("FORCE_REGENERATE", "").lower() in {"1", "true", "yes"}
REQUIRED_API_ENDPOINTS = [
    "/api/checkout",
    "/api/validate-card",
    "/api/validate-email",
]
CHECKOUT_E2E_PLAN = {
    "flow": "checkout",
    "requiredFields": ["email", "cardNumber", "expiry", "cvv", "amount"],
}
DETERMINISTIC_PAYLOADS = {
    "/api/checkout": {
        "email": "buyer@example.com",
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
 
def main():
    """Run the end-to-end generation workflow."""
    swagger_source = resolve_swagger_source()
    swagger_spec_dict = load_swagger_spec_dict(swagger_source)
    allowed_api_endpoints = extract_api_endpoints(swagger_spec_dict)
    ensure_required_endpoints_exist(allowed_api_endpoints)

    generate_api_tests(swagger_spec_dict, allowed_api_endpoints)
    generate_e2e_tests()

    print("Test case generation completed successfully.")


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


def generate_api_tests(swagger_spec_dict: dict, allowed_api_endpoints: set[str]):
    """Generate one API spec per required endpoint."""
    for endpoint in REQUIRED_API_ENDPOINTS:
        existing_file_path = get_api_test_file_path(endpoint)

        if not FORCE_REGENERATE and existing_file_path.is_file():
            existing_code = existing_file_path.read_text(encoding="utf-8")
            if validator.validate_test_cases(existing_code, allowed_api_endpoints=allowed_api_endpoints):
                print(f"Skipping regeneration for '{endpoint}' because an existing valid spec already exists.")
                continue

        endpoint_spec = extract_endpoint_spec(swagger_spec_dict, endpoint)
        payload = DETERMINISTIC_PAYLOADS[endpoint]
        test_code = generate_api_test(endpoint_spec, payload)

        test_code = validator.validate_and_repair_test_cases(
            test_code,
            allowed_api_endpoints=allowed_api_endpoints,
        )
        if test_code is None:
            print(f"Skipping API test generation for endpoint '{endpoint}' after validation/repair failed.")
            continue

        save_api_test(endpoint, test_code)


def generate_api_test(endpoint_spec: dict, payload: dict) -> str:
    """Build the API prompt for one endpoint and ask Gemini for a spec file."""
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    phase3_prompt = load_prompt("phase_3_api")

    prompt = build_prompt(
        base_prompt,
        phase3_prompt,
        {
            "ENDPOINT": endpoint_spec["endpoint"],
            "ENDPOINT_SPEC": json.dumps(endpoint_spec, indent=2),
            "PAYLOAD": json.dumps(payload, indent=2),
        },
    )
    endpoint_cache_key = endpoint_spec["endpoint"].strip("/").replace("/", "_")
    return call_llm(prompt, cache_key=f"api_{endpoint_cache_key}")


def generate_e2e_tests():
    """Generate the single required checkout E2E spec."""
    existing_file_path = get_e2e_test_file_path(CHECKOUT_E2E_PLAN["flow"])

    if not FORCE_REGENERATE and existing_file_path.is_file():
        existing_code = existing_file_path.read_text(encoding="utf-8")
        if validator.validate_test_cases(existing_code, require_e2e_structure=True):
            print(
                f"Skipping regeneration for E2E flow '{CHECKOUT_E2E_PLAN['flow']}' "
                "because an existing valid spec already exists."
            )
            return

    test_code = generate_e2e_test(CHECKOUT_E2E_PLAN)

    test_code = validator.validate_and_repair_test_cases(
        test_code,
        require_e2e_structure=True,
    )
    if test_code is None:
        print(f"Skipping E2E test generation for '{CHECKOUT_E2E_PLAN['flow']}' after validation/repair failed.")
        return

    save_e2e_test(CHECKOUT_E2E_PLAN["flow"], test_code)


def generate_e2e_test(e2e_test_plan: dict) -> str:
    """Build the E2E prompt and ask Gemini for a checkout spec file."""
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    phase4_prompt = load_prompt("phase_4_e2e")

    prompt = build_prompt(base_prompt, phase4_prompt, {"E2E_PLAN": json.dumps(e2e_test_plan)})
    return call_llm(prompt, cache_key=f"e2e_{e2e_test_plan['flow']}")


def save_api_test(endpoint: str, test_code: str):
    """Write a generated API spec to the expected tests/api path."""
    file_path = get_api_test_file_path(endpoint)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(test_code)


def save_e2e_test(test_name: str, test_code: str):
    """Write a generated E2E spec to the expected tests/web path."""
    file_path = get_e2e_test_file_path(test_name)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(test_code)


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
