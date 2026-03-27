from llm_client import call_llm
from prompt_loader import build_prompt, load_prompt
import re

BASE_PROMPT_NAME = "base_lean"
GENERIC_REPAIR_ERROR_PROMPT = "phase_6_repair_error_generic"
SPECIFIC_REPAIR_ERROR_PROMPT = "phase_6_repair_error_specific"


# this function will clean the generated code by removing any markdown code fences and trimming whitespace, 
# it will return the cleaned code as a string
def clean_code(code: str) -> str:
    return code.replace("```ts", "").replace("```", "").strip()


# this function will extract the API endpoints from the generated test code by 
# using a regular expression to find all occurrences of strings that look like API routes (e.g., "/api/endpoint"),
def extract_api_routes(code: str) -> set[str]:
    return set(re.findall(r"/api/[A-Za-z0-9_-]+", code))


def validate_e2e_test_structure(code: str) -> bool:
    required_markers = [
        "page.goto(",
        'input[name="email"]',
        'input[name="cardNumber"]',
        'input[name="expiry"]',
        'input[name="cvv"]',
        'input[name="amount"]',
    ]
    return all(marker in code for marker in required_markers)


# this function will validate the generated test code by checking for the presence of certain keywords and patterns that are expected in valid test code,
# it will also check if the referenced API endpoints in the test code are within the allowed API endpoints extracted from the swagger specification, if provided, 
# it will return True if the code is valid and False otherwise
def validate_test_cases(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
) -> bool:
    code = clean_code(code)
    if not code:
        return False
    
    if "TODO" in code or "FIXME" in code:
        return False
    
    checks = [
        "test(" in code,
        "expect(" in code,
        "import" in code or "require" in code
    ]

    if allowed_api_endpoints is not None:
        referenced_routes = extract_api_routes(code)
        if not referenced_routes:
            return False
        if not referenced_routes.issubset(allowed_api_endpoints):
            return False

    if require_e2e_structure and not validate_e2e_test_structure(code):
        return False

    return all(checks)


# this function will attempt to repair the generated test code by calling the LLM 
# with a repair prompt that includes the error message and the original test code,
# it will return the repaired code as a string
def repair_test_cases(code: str, error: str = "") -> str:
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


# this function will validate the generated test code, and if it is not valid, 
# it will attempt to repair it by calling the repair_test_cases function,
# it will return the valid test code if the validation or repair is successful, 
# and None if the validation fails and the repair is unsuccessful after multiple attempts
def validate_and_repair_test_cases(
    code: str,
    allowed_api_endpoints: set[str] | None = None,
    require_e2e_structure: bool = False,
) -> str | None:
    print("Validating the generated test code...")
    code = clean_code(code)
    if validate_test_cases(
        code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
    ):
        return code
    print("The generated test code is not valid and cannot be executed. Attempting to repair the code...")  
    
    # Attempt to repair the code with a generic error message first
    print("Attempting to repair the code with a generic error message...")
    fixed_code = repair_test_cases(code, load_prompt(GENERIC_REPAIR_ERROR_PROMPT))
    
    if validate_test_cases(
        fixed_code,
        allowed_api_endpoints=allowed_api_endpoints,
        require_e2e_structure=require_e2e_structure,
    ):
        print("Successfully repaired the test code with a generic error message.")
        return fixed_code
    else:
        print("Failed to repair the test code with a generic error message. Attempting to repair the code with a specific error message...")
        
        # If the first repair attempt fails, try again with a more specific error message
        specific_error = load_prompt(SPECIFIC_REPAIR_ERROR_PROMPT)
        fixed_code = repair_test_cases(fixed_code, specific_error)
        
        if validate_test_cases(
            fixed_code,
            allowed_api_endpoints=allowed_api_endpoints,
            require_e2e_structure=require_e2e_structure,
        ):
            print("Successfully repaired the test code with a specific error message.")
            return fixed_code
        else:
            print("Failed to repair the test code after multiple attempts.")
            return None
