"""Validate and repair generated Playwright specs.

This module provides lightweight but targeted guardrails before generated code
is saved:
- basic Playwright structure checks
- allowed API route checks
- route-specific API status and field assertion checks
- required checkout-flow structure, submit, and success-state checks
- one repair attempt using Gemini when validation fails
"""

import re
from llm_client import call_llm
from prompt_loader import build_prompt, load_prompt

BASE_PROMPT_NAME = "core_context"
REQUIRED_E2E_FIELDS = ["email", "cardNumber", "expiry", "cvv", "amount"]
PLACEHOLDER_MARKERS = ["TODO", "FIXME"]
MAX_API_TEST_BLOCKS = 1
API_ROUTE_EXPECTATIONS = {
    "/api/checkout": {
        "expected_status": 200,
        "field_names": ["status", "message"],
    },
    "/api/validate-card": {
        "expected_status": 200,
        "field_names": ["valid", "message"],
    },
    "/api/validate-email": {
        "expected_status": 500,
        "field_names": ["error"],
    },
}
# Markers used to confirm the generated checkout flow actually submits the form.
SUBMIT_SELECTOR_MARKERS = [
    'button[type="submit"]',
    "button[type='submit']",
]
SUBMIT_ACTION_MARKERS = [
    "click()",
    "press('Enter')",
    'press("Enter")',
]
# Markers that indicate the E2E test verifies a visible success outcome.
SUCCESS_STATE_MARKERS = [
    "Payment processed successfully!",
    "toContain('✅')",
    'toContain("✅")',
    "toContainText('✅')",
    'toContainText("✅")',
    "toContain('Payment processed successfully!')",
    'toContain("Payment processed successfully!")',
    "toContainText('Payment processed successfully!')",
    'toContainText("Payment processed successfully!")',
]


def contains_any(text: str, markers: list[str]) -> bool:
    """Return True when at least one marker exists in the text."""
    return any(marker in text for marker in markers)


def has_module_import(code: str) -> bool:
    """Return True when code includes import or require syntax."""
    return "import" in code or "require" in code


def has_status_assertion(code: str, expected_status: int) -> bool:
    """Return True when the code appears to assert the expected HTTP status."""
    expected_status_text = str(expected_status)
    status_markers = [
        f"status()).toBe({expected_status_text}",
        f"status() === {expected_status_text}",
        f"validateAndGetJson(response, {expected_status_text})",
        f"toBe({expected_status_text})",
        f"toEqual({expected_status_text})",
    ]
    if contains_any(code, status_markers):
        return True

    return "status()" in code and expected_status_text in code


def has_field_assertion(code: str, field_names: list[str]) -> bool:
    """Return True when at least one expected response field is asserted."""
    field_markers: list[str] = []
    for field_name in field_names:
        field_markers.extend(
            [
                f".{field_name}",
                f"['{field_name}']",
                f'["{field_name}"]',
                f"'{field_name}'",
                f'"{field_name}"',
            ]
        )

    return "expect(" in code and contains_any(code, field_markers)


def has_valid_api_helper_import(code: str) -> bool:
    """Return True when ApiHelper is imported using the actual named export."""
    if "ApiHelper" not in code:
        return True
    return "import { ApiHelper } from '../../utils/api-helper';" in code


def count_test_blocks(code: str) -> int:
    """Count Playwright test blocks in the generated code."""
    return len(re.findall(r"\btest\s*\(", code))


def clean_code(code: str) -> str:
    """Remove markdown fences and trim whitespace from generated code."""
    code_without_fences = re.sub(r"```[a-zA-Z]*", "", code)
    return code_without_fences.strip()


def extract_api_routes(code: str) -> set[str]:
    """Find `/api/...` routes referenced inside generated test code."""
    return set(re.findall(r"/api(?:/[A-Za-z0-9_-]+)+", code))


def references_required_field(code: str, field_name: str) -> bool:
    """Check if a field is used through common Playwright selector styles."""
    selector_markers = [
        f'input[name="{field_name}"]',
        f"input[name='{field_name}']",
        f"getByPlaceholder('{field_name}')",
        f'getByPlaceholder("{field_name}")',
    ]
    if contains_any(code, selector_markers):
        return True
    # Fallback for other selector styles where the field token is still present.
    return re.search(rf"\\b{re.escape(field_name)}\\b", code) is not None


def find_missing_basics(code: str) -> str | None:
    """Return an error when core runnable test structure is missing."""
    if contains_any(code, PLACEHOLDER_MARKERS):
        return "Generated output still contains a placeholder such as TODO or FIXME."

    if "test(" not in code:
        return "Generated output must include at least one Playwright test() call."

    if "expect(" not in code:
        return "Generated output must include at least one expect() assertion."

    if not has_module_import(code):
        return "Generated output must include imports or requires so the spec is runnable."

    return None


def find_invalid_api_routes(code: str, allowed_api_endpoints: set[str]) -> str | None:
    """Return an API route error message, or None when routes are valid."""
    referenced_routes = extract_api_routes(code)
    if not referenced_routes:
        return "API spec must reference at least one allowed /api/... route."

    invalid_routes = sorted(referenced_routes - allowed_api_endpoints)
    if invalid_routes:
        return f"API spec referenced unknown routes: {', '.join(invalid_routes)}."
    return None


def find_missing_api_assertions(code: str, referenced_routes: set[str]) -> str | None:
    """Return an error when an API test misses required status or field assertions."""
    if count_test_blocks(code) != MAX_API_TEST_BLOCKS:
        return "API spec must contain exactly one deterministic happy-path test."

    if not has_valid_api_helper_import(code):
        return "API spec must import ApiHelper as a named import from ../../utils/api-helper."

    for route in sorted(referenced_routes):
        route_expectations = API_ROUTE_EXPECTATIONS.get(route)
        if route_expectations is None:
            continue

        if not has_status_assertion(code, route_expectations["expected_status"]):
            return (
                f"API spec for {route} must assert HTTP status "
                f"{route_expectations['expected_status']}."
            )

        if not has_field_assertion(code, route_expectations["field_names"]):
            return (
                f"API spec for {route} must assert at least one stable response field: "
                f"{', '.join(route_expectations['field_names'])}."
            )

        if route == "/api/validate-email" and "Internal server error" in code:
            return (
                "API spec for /api/validate-email should assert the error field exists, "
                "but should not assume an exact error message string."
            )

    return None


def validate_e2e_test_structure(code: str) -> bool:
    """Check for required checkout field usage, submit action, and success state."""
    if "page.goto(" not in code:
        return False

    if not contains_any(code, SUBMIT_SELECTOR_MARKERS):
        return False

    if not contains_any(code, SUBMIT_ACTION_MARKERS):
        return False

    if not contains_any(code, SUCCESS_STATE_MARKERS):
        return False

    return all(references_required_field(code, field) for field in REQUIRED_E2E_FIELDS)


def find_validation_error(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
) -> str | None:
    """Return a human-readable validation error, or None when valid."""
    code = clean_code(code)
    if not code:
        return "Generated output was empty."

    basics_error = find_missing_basics(code)
    if basics_error:
        return basics_error

    if allowed_api_endpoints is not None:
        route_error = find_invalid_api_routes(code, allowed_api_endpoints)
        if route_error:
            return route_error

        referenced_routes = extract_api_routes(code)
        assertion_error = find_missing_api_assertions(code, referenced_routes)
        if assertion_error:
            return assertion_error

    if require_e2e_structure and not validate_e2e_test_structure(code):
        return (
            "E2E spec must include page.goto(), fill input[name=\"email\"], "
            "input[name=\"cardNumber\"], input[name=\"expiry\"], input[name=\"cvv\"], "
            "input[name=\"amount\"], submit via button[type=\"submit\"], and assert a visible success state."
        )

    return None


def validate_test_cases(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
) -> bool:
    """Return True when generated test code passes the lightweight checks."""
    return (
        find_validation_error(
            code,
            allowed_api_endpoints=allowed_api_endpoints,
            require_e2e_structure=require_e2e_structure,
        )
        is None
    )


def repair_test_cases(code: str, error: str = "") -> str:
    """Ask Gemini to repair invalid generated code using a focused error message."""
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    repair_prompt = load_prompt("repair_generation")
    full_prompt = build_prompt(
        base_prompt,
        repair_prompt,
        {
            "ERROR": error,
            "TEST_CODE": code,
        },
    )

    repaired_code = call_llm(full_prompt)
    return clean_code(repaired_code)


def validate_and_repair_test_cases(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
) -> str | None:
    """Validate generated code and attempt one repair if validation fails.

    The repair pass receives a concrete validation error so it can fix the
    exact missing requirement instead of guessing.
    """
    print("Validating the generated test code...")
    code = clean_code(code)
    if validate_test_cases(
        code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
    ):
        return code
    print("The generated test code is not valid and cannot be executed. Attempting to repair the code...")  

    validation_error = find_validation_error(
        code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
    ) or ""
    fixed_code = repair_test_cases(code, validation_error)

    if validate_test_cases(
        fixed_code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
    ):
        print("Successfully repaired the test code.")
        return fixed_code

    print("Failed to repair the test code after one repair attempt.")
    return None
