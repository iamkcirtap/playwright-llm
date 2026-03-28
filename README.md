# PayMongo SDET Assessment

This repository generates Playwright tests with Google Gemini, validates the generated code, and runs the saved specs in CI as a quality gate.

## What This Project Does

- Generates API tests for `/api/checkout`, `/api/validate-card`, and `/api/validate-email`
- Generates one happy-path E2E checkout test
- Validates generated output before saving it
- Repairs invalid output once, then skips it if still invalid
- Reuses valid specs and simple cached LLM responses to reduce repeated Gemini calls

## Overall Design

The design is intentionally simple:

1. Load Swagger from a URL or local file
2. Check that the required endpoints exist
3. Use fixed payloads for the required API endpoints
4. Ask Gemini to generate one API spec per endpoint and one E2E spec
5. Validate the generated code
6. Repair once if needed
7. Save only valid `.spec.ts` files

This keeps the solution deterministic, cheaper to run, and easier to explain in an interview.

## Short Script Explanations

- [`scripts/generate_tests.py`](scripts/generate_tests.py)
  Main orchestration script. It loads Swagger, loops through the required endpoints, calls Gemini with focused prompts, validates the output, and saves runnable specs.
- [`scripts/swagger_loader.py`](scripts/swagger_loader.py)
  Loads Swagger from a live URL or file path, updates a local fallback copy, and extracts endpoint-specific contract data.
- [`scripts/prompt_loader.py`](scripts/prompt_loader.py)
  Loads prompt templates and replaces variables like `{{ENDPOINT}}` and `{{PAYLOAD}}`.
- [`scripts/llm_client.py`](scripts/llm_client.py)
  Calls Gemini, retries temporary failures like rate limits, and stores simple versioned cache files for repeated runs.
- [`scripts/validator.py`](scripts/validator.py)
  Checks if generated code looks runnable, explains what failed, and performs one repair attempt if needed.

## Natural Interview Explanation

You can say this out loud:

"This repo is a small AI-assisted test generator for a payment app. I load the Swagger contract, keep the scope limited to the required endpoints, use fixed payloads for determinism, and ask Gemini to generate Playwright specs. Then I validate the output, repair it once if needed, and run the saved tests in CI. To reduce rate-limit issues, I reuse valid files and cache named LLM responses."

## System Under Test

This repository is the test-generation and quality-gate repo. The application under test runs separately.

Expected environment:

- frontend: `http://localhost:3000`
- backend API: `http://localhost:8080`
- Swagger JSON: `http://localhost:8080/swagger.json`

Required API coverage:

- `POST /api/checkout`
- `POST /api/validate-card`
- `POST /api/validate-email`

Required E2E coverage:

- one happy-path checkout flow

## Regenerating Tests

1. Install Python dependencies:
   `pip install -r requirements.txt`
2. Install Node.js dependencies:
   `npm install`
3. Install Playwright browsers:
   `npx playwright install`
4. Set the Gemini API key:
   PowerShell: `$env:GEMINI_API_KEY="your-key"`
5. Start the application under test:
   frontend on `http://localhost:3000`
   backend on `http://localhost:8080`
6. Run the generator:
   `python scripts/generate_tests.py`

You can also pass Swagger explicitly:

- `python scripts/generate_tests.py --swagger ../separate-app/swagger.json`
- `python scripts/generate_tests.py --swagger http://localhost:8080/swagger.json`

Generated API specs are written to `tests/api/` and E2E specs are written to `tests/web/`.

By default:

- existing valid specs are reused
- LLM responses are cached under `.cache/llm/`

To force regeneration of specs, set:

- `FORCE_REGENERATE=true`

To invalidate old LLM cache entries, bump:

- `LLM_CACHE_VERSION=v2`

## Validation Rules

A generated test is considered valid when it:

- contains `test()`
- contains `expect()`
- contains imports
- contains no `TODO` or `FIXME`
- references only allowed API routes for API specs
- includes the expected checkout structure for E2E specs

If invalid:

- one repair attempt is made with a focused validation message
- if still invalid, the file is skipped

## Caching Strategy

Caching is intentionally simple and interview-friendly.

- Each generated artifact gets a readable cache key such as `api_api_checkout` or `e2e_checkout`
- Responses are stored as versioned text files under `.cache/llm/`
- If the prompt strategy changes, bump `LLM_CACHE_VERSION`

This helps reduce unnecessary Gemini calls and lowers the chance of hitting rate limits quickly.

## CI / Quality Gate

The CI pipeline should:

- run test generation
- run Playwright API tests
- run Playwright E2E tests
- fail on any generation or test failure
- publish reports or artifacts

This repo assumes the target application is already running and reachable during CI.

## Repository Rules

- Do not modify `playwright.config.ts`
- Do not change the project structure
- Output only runnable `.spec.ts` files
- Do not invent endpoints, fields, or UI selectors
- Use deterministic inputs and stable assertions
- Prefer real contract data over model guesses

## Prompt Files In Use

- [`prompts/base_lean.txt`](prompts/base_lean.txt)
- [`prompts/phase_3_api.txt`](prompts/phase_3_api.txt)
- [`prompts/phase_4_e2e.txt`](prompts/phase_4_e2e.txt)
- [`prompts/phase_6_repair.txt`](prompts/phase_6_repair.txt)

## Why This Is A Good SDET Solution

- It is reproducible
- It is deterministic where possible
- It uses the contract as a source of truth
- It treats generated tests as code that must be validated
- It integrates generation and execution into one quality gate
