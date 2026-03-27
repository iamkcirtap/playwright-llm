import json
import os
import pathlib

from prompt_loader import load_prompt, build_prompt
from llm_client import call_llm
from swagger_loader import resolve_swagger_source, load_swagger_spec_dict, extract_api_endpoints
import validator

BASE_PROMPT_NAME = "base_lean"
API_TESTS_DIR = pathlib.Path("tests") / "api"
WEB_TESTS_DIR = pathlib.Path("tests") / "web"
FORCE_REGENERATE = os.getenv("FORCE_REGENERATE", "").lower() in {"1", "true", "yes"}


def clean_json_response(response_text: str) -> str:
    cleaned = response_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    return cleaned


# this is the main function that orchestrates the whole process of generating test cases, 
# it will call the other functions in the correct order to generate the test cases based on the swagger specifications and the prompts, 
# and it will also handle the validation and repair of the generated test cases, 
# and finally save the generated test cases in the tests folder with .spec.ts extension
def main():
    swagger_source = resolve_swagger_source()
    swagger_spec_dict = load_swagger_spec_dict(swagger_source)
    swagger_spec = json.dumps(swagger_spec_dict)
    allowed_api_endpoints = extract_api_endpoints(swagger_spec_dict)

    plan = generate_plan(swagger_spec)

    generate_api_tests(plan["api"], allowed_api_endpoints)
    generate_e2e_tests(plan["e2e"])

    print("Test case generation completed successfully.")

# PHASE 1: this function will generate the test plan based on the swagger specifications and the base prompt for planning
def generate_plan(swagger_spec: str) -> dict:
    # load the base prompt and phase 1 for generating the test plan
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    phase1_prompt = load_prompt("phase_1_plan")
    
    # build the prompt for phase 1 by injecting the swagger specifications into the base prompt and the phase 1 prompt
    prompt = build_prompt(base_prompt, phase1_prompt, {"SWAGGER_SPEC": swagger_spec})
    
    # call the LLM to generate the test plan
    plan_str = clean_json_response(call_llm(prompt))
    
    # parse the plan string into a dictionary and return it
    plan = json.loads(plan_str)
    return plan


# this function will generate API tests from the api test plan
def generate_api_tests(api_test_plan: list, allowed_api_endpoints: set[str]):
    for item in api_test_plan:
        endpoint = item["endpoint"]
        method = item.get("method", "GET").upper()
        existing_file_path = get_api_test_file_path(endpoint)

        if endpoint not in allowed_api_endpoints:
            print(f"Skipping API test generation for unknown endpoint '{endpoint}' not found in Swagger.")
            continue

        if not FORCE_REGENERATE and existing_file_path.is_file():
            existing_code = existing_file_path.read_text()
            if validator.validate_test_cases(existing_code, allowed_api_endpoints=allowed_api_endpoints):
                print(f"Skipping regeneration for '{endpoint}' because an existing valid spec already exists.")
                continue

        payload = item.get("payload", {})
        if method != "GET" and not payload:
            payload = generate_payload(endpoint)

        test_code = generate_api_test(endpoint, payload)

        test_code = validator.validate_and_repair_test_cases(
            test_code,
            allowed_api_endpoints=allowed_api_endpoints,
        )
        if test_code is None:
            print(f"Skipping API test generation for endpoint '{endpoint}' after validation/repair failed.")
            continue

        save_api_test(endpoint, test_code)


# PHASE 2: this function will generate the payload for the API tests based on the endpoint specifications
def generate_payload(endpoint: str) -> dict:
    # load the base prompt and phase 2 for generating the payloads for the API tests
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    phase2_prompt = load_prompt("phase_2_payload")
    
    # build the prompt for phase 2 by injecting the endpoint specifications into the base prompt and the phase 2 prompt
    prompt = build_prompt(base_prompt, phase2_prompt, {"ENDPOINT": endpoint})
    
    # call the LLM to generate the payload for the API test
    payload_str = clean_json_response(call_llm(prompt))
    
    # parse the payload string into a dictionary and return it
    payload = json.loads(payload_str)
    return payload


# PHASE 3: this function will generate the API test code based on the endpoint specifications and the generated payload
def generate_api_test(endpoint: str, payload: dict) -> str:
    # load the base prompt and phase 3 for generating the API test code
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    phase3_prompt = load_prompt("phase_3_api")
    
    # build the prompt for phase 3 by injecting the endpoint specifications and the generated payload into the base prompt and the phase 3 prompt
    prompt = build_prompt(base_prompt, phase3_prompt, {"ENDPOINT": endpoint, "PAYLOAD": json.dumps(payload)})
    
    # call the LLM to generate the API test code
    test_code = call_llm(prompt)
    return test_code


# PHASE 4: this function will generate the E2E test code based on the generated API tests and the test plan
def generate_e2e_tests(e2e_test_plan: dict):
    existing_file_path = get_e2e_test_file_path(e2e_test_plan["flow"])

    if not FORCE_REGENERATE and existing_file_path.is_file():
        existing_code = existing_file_path.read_text()
        if validator.validate_test_cases(existing_code, require_e2e_structure=True):
            print(
                f"Skipping regeneration for E2E flow '{e2e_test_plan['flow']}' "
                "because an existing valid spec already exists."
            )
            return

    test_code = generate_e2e_test(e2e_test_plan)

    test_code = validator.validate_and_repair_test_cases(
        test_code,
        require_e2e_structure=True,
    )
    if test_code is None:
        print(f"Skipping E2E test generation for '{e2e_test_plan['flow']}' after validation/repair failed.")
        return

    save_e2e_test(e2e_test_plan["flow"], test_code)


def generate_e2e_test(e2e_test_plan: dict) -> str:
    # load the base prompt and phase 4 for generating the E2E test code
    base_prompt = load_prompt(BASE_PROMPT_NAME)
    phase4_prompt = load_prompt("phase_4_e2e")
    
    # build the prompt for phase 4 by injecting the E2E plan into the base prompt and the phase 4 prompt
    prompt = build_prompt(base_prompt, phase4_prompt, {"E2E_PLAN": json.dumps(e2e_test_plan)})
    
    # call the LLM to generate the E2E test code
    test_code = call_llm(prompt)
    return test_code


# this function will save the generated API test code in the tests folder with .spec.ts extension, and the file name will be based on the endpoint name
def save_api_test(endpoint: str, test_code: str):
    file_path = get_api_test_file_path(endpoint)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write(test_code)


# this function will save the generated E2E test code in the tests folder with .spec.ts extension, and the file name will be based on the test name
def save_e2e_test(test_name: str, test_code: str):
    file_path = get_e2e_test_file_path(test_name)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write(test_code)


def get_api_test_file_path(endpoint: str) -> pathlib.Path:
    file_name = endpoint.strip("/").replace("/", "_") + ".spec.ts"
    return API_TESTS_DIR / file_name


def get_e2e_test_file_path(test_name: str) -> pathlib.Path:
    file_name = test_name.strip().replace(" ", "_").lower() + ".spec.ts"
    return WEB_TESTS_DIR / file_name


if __name__ == "__main__":
    main()
