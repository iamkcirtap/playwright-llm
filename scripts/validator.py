"""Validate and repair generated Playwright specs.

This module provides lightweight guardrails before generated code is saved:
- basic Playwright structure checks
- allowed API route checks
- required checkout-flow structure checks
- one repair attempt using Gemini when validation fails
"""

import re
from llm_client import call_llm
from prompt_loader import build_prompt, load_prompt

BASE_PROMPT_NAME = "base_lean"


def clean_code(code: str) -> str:
    """Remove markdown fences and trim whitespace from generated code."""
    return code.replace("```ts", "").replace("```", "").strip()


def extract_api_routes(code: str) -> set[str]:
    """Find `/api/...` routes referenced inside generated test code."""
    return set(re.findall(r"/api/[A-Za-z0-9_-]+", code))


def validate_e2e_test_structure(code: str) -> bool:
    """Check for the required checkout fields and navigation call."""
    required_markers = [
        "page.goto(",
        'input[name="email"]',
        'input[name="cardNumber"]',
        'input[name="expiry"]',
        'input[name="cvv"]',
        'input[name="amount"]',
    ]
    return all(marker in code for marker in required_markers)


def find_validation_error(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
) -> str | None:
    """Return a human-readable validation error, or None when valid."""
    code = clean_code(code)
    if not code:
        return "Generated output was empty."
    
    if "TODO" in code or "FIXME" in code:
        return "Generated output still contains a placeholder such as TODO or FIXME."

    if "test(" not in code:
        return "Generated output must include at least one Playwright test() call."

    if "expect(" not in code:
        return "Generated output must include at least one expect() assertion."

    if "import" not in code and "require" not in code:
        return "Generated output must include imports or requires so the spec is runnable."

    if allowed_api_endpoints is not None:
        referenced_routes = extract_api_routes(code)
        if not referenced_routes:
            return "API spec must reference at least one allowed /api/... route."
        if not referenced_routes.issubset(allowed_api_endpoints):
            invalid_routes = sorted(referenced_routes - allowed_api_endpoints)
            return f"API spec referenced unknown routes: {', '.join(invalid_routes)}."

    if require_e2e_structure and not validate_e2e_test_structure(code):
        return (
            "E2E spec must include page.goto() and fill input[name=\"email\"], "
            "input[name=\"cardNumber\"], input[name=\"expiry\"], input[name=\"cvv\"], "
            "and input[name=\"amount\"]."
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
    repair_prompt = load_prompt("phase_6_repair")
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
    """Validate generated code and attempt one repair if validation fails."""
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
