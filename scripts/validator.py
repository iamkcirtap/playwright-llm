"""Validate and repair generated Playwright specs.

This module provides lightweight but targeted guardrails before generated code
is saved:
- basic Playwright structure checks
- allowed API route checks
- route-specific API status and field assertion checks
- required checkout-flow structure, submit, and success-state checks
- one repair attempt using the selected provider when validation fails
"""

import json
import re
from llm_client import call_llm
from prompt_loader import build_prompt, load_prompt

BASE_PROMPT_NAME = "core_context"
REQUIRED_E2E_FIELDS = ["email", "cardNumber", "expiry", "cvv", "amount"]
PLACEHOLDER_MARKERS = ["TODO", "FIXME"]
MAX_API_TEST_BLOCKS = 1
JS_TOKENS = r"(['\"`])(?:\\.|(?!\1)[\s\S])*?\1|//[^\n]*|/\*[\s\S]*?\*/"


def contains_any(text: str, markers: list[str]) -> bool:
    """Return True when at least one marker exists in the text."""
    return any(marker in text for marker in markers)


def has_module_import(code: str) -> bool:
    """Return True when code includes import or require syntax."""
    return "import" in code or "require" in code


def without_comments(code: str) -> str:
    """Discard comments while preserving quoted strings used by selectors."""
    return re.sub(JS_TOKENS, lambda match: "" if match[0].startswith(("//", "/*"))
                  else match[0], code)


def find_execution_bypass(code: str) -> str | None:
    """Reject common skip/focus and response-interception calls, not prose."""
    executable = re.sub(JS_TOKENS, lambda match: " " * len(match[0]), code)
    forbidden = r"skip|fixme|only|route|routeFromHAR|routeWebSocket|fulfill"
    if re.search(rf"\.\s*(?:{forbidden})\b", executable):
        return "Specs must execute normally against the real application; skip/focus and response interception are forbidden."
    for token in re.finditer(JS_TOKENS, code):
        if token[0].startswith("`") and "${" in token[0]:
            return "Use fixed literal strings without template interpolation."
        if token[0][1:-1] in forbidden.split("|") and code[:token.start()].rstrip().endswith("["):
            return "Skip/focus and response interception members are forbidden, including bracket access."
    # Bracket member calls are not needed by the supported generation format.
    # Preserve field access such as body['status'], but reject computed calls.
    if re.search(r"\]\s*\(", executable):
        return "Use direct method calls; computed calls can bypass execution checks."
    return None


def has_status_assertion(code: str, expected_status: int, response: str) -> bool:
    """Require an assertion on the response from the target request."""
    return re.search(
        rf"expect\(\s*{re.escape(response)}\.status\(\)\s*\)"
        rf"\s*\.(?:toBe|toEqual)\(\s*{expected_status}\s*\)", code
    ) is not None


def has_field_assertion(code: str, field_schemas: dict, body: str) -> bool:
    """Require a matcher on a contract field of the parsed response body."""
    for field, schema in field_schemas.items():
        access = rf"{re.escape(body)}(?:\.{re.escape(field)}|\[['\"]{re.escape(field)}['\"]\])"
        # A single enum/const is an explicit contract value, unlike an example.
        values = schema.get("enum", [])
        fixed = [schema["const"]] if "const" in schema else values if len(values) == 1 else []
        if fixed:
            literal = json.dumps(fixed[0])
            expected = (rf"['\"]{re.escape(fixed[0])}['\"]" if isinstance(fixed[0], str)
                        else re.escape(literal))
            pattern = rf"expect\(\s*{access}\s*\)\s*\.(?:toBe|toEqual)\(\s*{expected}\s*\)"
        else:
            pattern = (rf"expect\(\s*(?:typeof\s+)?{access}\s*\)\s*"
                       r"\.(?:toBe|toEqual|toBeTruthy|toBeDefined|toMatch|toContain)\(")
        if re.search(pattern, code):
            return True
    return False


def has_valid_api_helper_import(code: str) -> bool:
    """Return True when ApiHelper is imported using the actual named export."""
    if "ApiHelper" not in code:
        return True
    return re.search(
        r"import\s*\{\s*ApiHelper\s*\}\s*from\s*['\"]../../utils/api-helper['\"]", code
    ) is not None


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
    """Require an awaited fill on the actual field selector."""
    selector = rf"input\[name=['\"]{re.escape(field_name)}['\"]\]"
    return re.search(
        rf"await\s+page\.locator\(\s*(['\"]){selector}\1\s*\)"
        r"\s*\.fill\(\s*['\"][^'\"]+['\"]\s*\)", code
    ) is not None


def find_missing_basics(code: str) -> str | None:
    """Return an error when core runnable test structure is missing."""
    if contains_any(code, PLACEHOLDER_MARKERS):
        return "Generated output still contains a placeholder such as TODO or FIXME."

    bypass_error = find_execution_bypass(code)
    if bypass_error:
        return bypass_error

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


def find_missing_api_assertions(code: str, expectations: dict) -> str | None:
    """Tie the target request, status assertion, and body assertion together."""
    if count_test_blocks(code) != MAX_API_TEST_BLOCKS:
        return "API spec must contain exactly one deterministic happy-path test."
    if not has_valid_api_helper_import(code):
        return "API spec must import ApiHelper as a named import from ../../utils/api-helper."
    endpoint = expectations["endpoint"]
    if extract_api_routes(code) != {endpoint}:
        return f"API spec must exercise only the target endpoint {endpoint}."
    route = rf"['\"]{re.escape(endpoint)}['\"]"
    aliases = re.findall(rf"const\s+(\w+)\s*=\s*{route}\s*;", code)
    argument = "(?:" + "|".join([route, *(re.escape(alias) for alias in aliases)]) + ")"
    request = re.search(
        rf"const\s+(\w+)\s*=\s*await\s+(request|\w+)\."
        rf"{expectations['method']}\(\s*{argument}\s*[,)]", code
    )
    if not request:
        return f"API spec must await a {expectations['method'].upper()} request to {endpoint}."
    response, receiver = request.groups()
    if receiver != "request" and not re.search(
        rf"const\s+{re.escape(receiver)}\s*=\s*new\s+ApiHelper\(\s*request\s*\)", code
    ):
        return "API request helper must be constructed from the request fixture."
    status = expectations["expected_status"]
    helper_json = re.search(
        rf"const\s+(\w+)\s*=\s*await\s+{re.escape(receiver)}"
        rf"\.validateAndGetJson\(\s*{re.escape(response)}\s*,\s*{status}\s*\)", code
    ) if receiver != "request" else None
    if not has_status_assertion(code, status, response) and not helper_json:
        return f"API spec for {endpoint} must assert response.status() equals {status}."
    parsed = re.search(
        rf"const\s+(\w+)\s*=\s*await\s+{re.escape(response)}\.json\(\)", code
    ) or helper_json
    if not parsed or not has_field_assertion(code, expectations["field_schemas"], parsed[1]):
        return f"API spec must assert a parsed response field from {expectations['field_names']}."
    return None


def validate_e2e_test_structure(code: str) -> bool:
    """Check direct awaited checkout actions and a visible success assertion."""
    if count_test_blocks(code) != 1:
        return False
    navigation = re.search(r"await\s+page\.goto\(\s*['\"]/['\"]\s*\)", code)
    if not navigation:
        return False
    submit = re.search(
        r"await\s+page\.locator\(\s*(['\"])button\[type=['\"]submit['\"]\]\1\s*\)\s*\.click\(\)", code
    )
    if not submit or submit.start() < navigation.end():
        return False
    form_actions = code[navigation.end():submit.start()]
    if not all(references_required_field(form_actions, field) for field in REQUIRED_E2E_FIELDS):
        return False
    return re.search(
        r"await\s+expect\(\s*page\.getByText\(\s*(['\"])✅ Payment processed successfully!\1\s*\)"
        r"\s*\)\s*\.toBeVisible\(\)", code[submit.end():]
    ) is not None


def find_validation_error(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
    api_expectations: dict | None = None,
) -> str | None:
    """Return a human-readable validation error, or None when valid."""
    code = without_comments(clean_code(code))
    if not code:
        return "Generated output was empty."

    basics_error = find_missing_basics(code)
    if basics_error:
        return basics_error

    if allowed_api_endpoints is not None:
        route_error = find_invalid_api_routes(code, allowed_api_endpoints)
        if route_error:
            return route_error

    if allowed_api_endpoints is not None and api_expectations is None:
        return "API validation requires expectations from the target Swagger operation."

    if api_expectations is not None:
        assertion_error = find_missing_api_assertions(code, api_expectations)
        if assertion_error:
            return assertion_error

    if require_e2e_structure and not validate_e2e_test_structure(code):
        return (
            "E2E spec must await page.goto('/'), fill input[name=\"email\"], "
            "input[name=\"cardNumber\"], input[name=\"expiry\"], input[name=\"cvv\"], "
            "input[name=\"amount\"], submit via button[type=\"submit\"], and await expect(page.getByText('✅ Payment processed successfully!')).toBeVisible()."
        )

    return None


def validate_test_cases(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
    api_expectations: dict | None = None,
) -> bool:
    """Return True when generated test code passes the lightweight checks."""
    return (
        find_validation_error(
            code,
            allowed_api_endpoints=allowed_api_endpoints,
            require_e2e_structure=require_e2e_structure,
            api_expectations=api_expectations,
        )
        is None
    )


def repair_test_cases(code: str, error: str = "", generation_context: str = "") -> str:
    """Ask the selected provider to repair invalid generated code using a focused error message."""
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    repair_prompt = load_prompt("repair_generation")
    full_prompt = build_prompt(
        base_prompt,
        repair_prompt,
        {
            "ERROR": error,
            "TEST_CODE": code,
            "GENERATION_CONTEXT": generation_context,
        },
    )

    repaired_code = call_llm(full_prompt)
    return clean_code(repaired_code)


def validate_and_repair_test_cases(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
    api_expectations: dict | None = None,
    generation_context: str = "",
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
        api_expectations=api_expectations,
    ):
        return code
    print("The generated test code is not valid and cannot be executed. Attempting to repair the code...")  

    validation_error = find_validation_error(
        code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
        api_expectations=api_expectations,
    ) or ""
    repair_context = validation_error
    if api_expectations is not None:
        repair_context += "\nTarget Swagger expectations: " + json.dumps(api_expectations)
    fixed_code = repair_test_cases(code, repair_context, generation_context)

    if validate_test_cases(
        fixed_code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
        api_expectations=api_expectations,
    ):
        print("Successfully repaired the test code.")
        return fixed_code

    print("Failed to repair the test code after one repair attempt.")
    return None
