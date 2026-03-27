# PayMongo SDET Assessment

This repository implements an AI-assisted Playwright test generation pipeline. It uses a staged LLM workflow to translate API contracts and checkout-flow intent into runnable `.spec.ts` files while keeping the existing Playwright template intact.

## What This Project Does

- Generates API Playwright tests from the Swagger/OpenAPI contract
- Generates an E2E checkout Playwright test from a structured plan
- Validates generated tests and attempts one repair cycle when output is not runnable
- Runs generation and test execution in CI so broken output never silently ships

## System Under Test

This repository is the quality-gate and test-generation repository. The application under test runs in a separate project.

Expected application contract:

- frontend: `http://localhost:3000`
- backend API: `http://localhost:8080`
- Swagger JSON: `http://localhost:8080/swagger.json`
- health check: `http://localhost:8080/api/health`

The backend exposes:

- `GET /api/health`
- `POST /api/checkout`
- `POST /api/validate-email`
- `POST /api/validate-card`

## Regenerating Tests

The generation workflow is reproducible and executable from this repository.

1. Install Python dependencies:
   `pip install -r requirements.txt`
2. Install Node.js dependencies:
   `npm install`
3. Install Playwright browsers:
   `npx playwright install`
4. Set the Gemini API key:
   `GEMINI_API_KEY=<your_key>`
5. Start the application under test separately:
   - frontend on `http://localhost:3000`
   - backend on `http://localhost:8080`
6. Provide the Swagger/OpenAPI JSON file in one of three ways:
   - pass it explicitly with `--swagger <path>`
   - pass it explicitly with `--swagger <url>`
   - or set `SWAGGER_PATH=<path>`
   - a common local value is the separate app's `docs/swagger.json`
   - if neither is provided, the generator fetches the live Swagger URL `http://localhost:8080/swagger.json`
   - after a successful live fetch, the local cache at `swagger/spec.json` is updated automatically
   - if the live fetch is unavailable, the generator falls back to the cached local file at `swagger/spec.json`
   - a local file can still be used directly when passed explicitly
7. Generate tests:
   `python scripts/generate_tests.py`
   or
   `python scripts/generate_tests.py --swagger ../separate-app/swagger.json`
   or
   `python scripts/generate_tests.py --swagger http://localhost:8080/swagger.json`
   - by default, the generator reuses existing valid API and E2E specs to reduce unnecessary LLM calls
   - set `FORCE_REGENERATE=true` to regenerate specs even when valid files already exist
8. Run Playwright:
   `npx playwright test`

Generated API specs are written to `tests/api/` and generated E2E specs are written to `tests/web/`.

This repository is intended to execute generated Playwright specs as the primary test assets. It does not rely on handwritten example specs for the assessment workflow.

## Expected Generated Test Shape

Generated API tests should follow this general pattern:

```ts
import { test, expect } from '@playwright/test';

test('validates an API endpoint', async ({ request }) => {
  const response = await request.post('/api/checkout', {
    data: {
      email: 'buyer@example.com',
      cardNumber: '4111111111111111',
      expiry: '12/34',
      cvv: '123',
      amount: 1000,
    },
  });

  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.success).toBe(true);
});
```

Generated E2E tests should follow this general pattern:

```ts
import { test, expect } from '@playwright/test';

test('completes checkout', async ({ page }) => {
  await page.goto('/');
  await page.locator('input[name="email"]').fill('buyer@example.com');
  await page.locator('input[name="cardNumber"]').fill('4111111111111111');
  await page.locator('input[name="expiry"]').fill('12/34');
  await page.locator('input[name="cvv"]').fill('123');
  await page.locator('input[name="amount"]').fill('1000');
  await page.getByRole('button').click();
  await expect(page.locator('text=success')).toBeVisible();
});
```

These snippets are documentation only. The actual assessment flow relies on generated `.spec.ts` files written by the LLM pipeline.

## Secret Handling

The LLM client reads the Gemini key from the `GEMINI_API_KEY` environment variable in [`scripts/llm_client.py`](scripts/llm_client.py). Secrets are never hardcoded in the repository and should never be committed.

Local development:

- PowerShell:
  `$env:GEMINI_API_KEY="your-temporary-key"`
- macOS/Linux shell:
  `export GEMINI_API_KEY="your-temporary-key"`
- Optional reference file:
  copy [`.env.example`](.env.example) to `.env` for local configuration guidance, but do not commit real secret values

CI injection:

- GitHub Actions injects the key from repository secrets:
  `GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}`
- The workflow then uses that environment variable during `python scripts/generate_tests.py`
- Swagger and target app locations can be injected through repository variables such as:
  `SWAGGER_PATH`, `STAGING_BASE_URL`, and `STAGING_API_URL`

Rules:

- do not hardcode API keys in Python, prompts, workflow files, or tests
- do not commit `.env` files containing real secret values
- rotate or replace the temporary key outside the repo if exposure is suspected

## Orchestration

The repository supports both direct commands and simple npm-based orchestration.

Available scripts:

- `npm run generate`
  Triggers the LLM-based generation workflow in [`scripts/generate_tests.py`](scripts/generate_tests.py).
- `npm run test:api`
  Executes Playwright API tests only.
- `npm run test:web`
  Executes Playwright E2E/frontend tests only.
- `npm run quality:gate`
  Runs generation first, then API tests, then E2E tests.

That means the quality-gate sequence is reproducible locally with one command:

`npm run quality:gate`

If the Swagger file is not at the default location, run the generator directly:

`python scripts/generate_tests.py --swagger ../separate-app/swagger.json`

Or point directly to the running backend:

`python scripts/generate_tests.py --swagger http://localhost:8080/swagger.json`

Then execute:

- `npm run test:api`
- `npm run test:web`

For CI against a separate application project, configure these repository variables:

- `SWAGGER_PATH`
- `STAGING_BASE_URL`
- `STAGING_API_URL`

Recommended values for the provided application:

- `STAGING_BASE_URL=http://localhost:3000`
- `STAGING_API_URL=http://localhost:8080`
- `SWAGGER_PATH=../application/docs/swagger.json` or another mounted/checked-out path in CI

## Repository Rules

- Do not modify `playwright.config.ts`
- Do not change the folder structure
- Output only `.spec.ts` files
- Do not invent endpoints, request fields, or UI selectors
- Use deterministic inputs and stable assertions

## Generation Pipeline

The generator is orchestrated by [`scripts/generate_tests.py`](scripts/generate_tests.py). The flow is intentionally split into small phases so each prompt has one job:

1. `phase_1_plan`
   Reads the Swagger spec and returns a minimal JSON plan with API coverage plus one E2E flow.
2. `phase_2_payload`
   Produces a deterministic request payload for each endpoint in the plan.
3. `phase_3_api`
   Converts one endpoint plus one payload into a runnable Playwright API test.
4. `phase_4_e2e`
   Converts the E2E flow plan into a runnable checkout test.
5. Validation and repair
   Checks for `test()`, `expect()`, imports, and missing placeholders; if the output is invalid, a repair prompt is applied before the test is saved.

This staged design matters because it reduces prompt complexity. Instead of asking the model to infer everything in one pass, we first force it to plan, then generate only the data or code needed for the next step.

## 1. LLM Prompt Design

The prompt design is phase-based and constraint-heavy rather than free-form. The shared base prompt in [`prompts/base_lean.txt`](prompts/base_lean.txt) establishes the global rules:

- code only
- runnable `.spec.ts`
- deterministic behavior
- no placeholders
- no config or structure changes
- no invented data

Each phase prompt then narrows the model's job:

- [`prompts/phase_1_plan.txt`](prompts/phase_1_plan.txt) asks for JSON only, which makes the planning step machine-readable and easy to validate.
- [`prompts/phase_2_payload.txt`](prompts/phase_2_payload.txt) isolates payload generation so request data can be reasoned about separately from test syntax.
- [`prompts/phase_3_api.txt`](prompts/phase_3_api.txt) focuses only on turning a known endpoint plus payload into API assertions.
- [`prompts/phase_4_e2e.txt`](prompts/phase_4_e2e.txt) constrains selector strategy and checkout interactions.
- [`prompts/phase_5_validate.txt`](prompts/phase_5_validate.txt) and [`prompts/phase_6_repair.txt`](prompts/phase_6_repair.txt) provide a safety net for malformed or low-quality output.

The practical design principle is: make every prompt narrow, typed, and falsifiable. JSON plans are easier to trust than prose plans, and code generation is safer when it receives structured inputs rather than the full Swagger blob every time.

## 2. How Swagger Is Translated Into Playwright Tests

Swagger is first loaded as raw JSON by the generator, then passed into the planning phase. The model is instructed to:

- enumerate the supported endpoints
- choose realistic payloads
- define expected status codes
- identify 1-2 meaningful assertions per endpoint

That plan becomes the contract for API test generation. For each endpoint:

1. the endpoint name is passed into the payload prompt
2. the payload prompt returns deterministic request data
3. the API prompt receives the endpoint and payload
4. the API prompt emits a Playwright `request`-based test with status and field assertions

This keeps Swagger translation explicit. The model does not jump directly from an OpenAPI document to final code in one step; it first converts the contract into a smaller internal test plan, then code is generated from that plan.

## 3. How The Generation Process Works

At a high level, generation works like this:

1. Load Swagger from the configured local spec file.
2. Ask the LLM for a minimal JSON plan covering API endpoints and the checkout E2E flow.
3. Generate payloads and API tests endpoint-by-endpoint.
4. Generate one checkout E2E test from the E2E plan.
5. Validate generated code.
6. If validation fails, run repair once more with stronger guidance.
7. Save only valid `.spec.ts` files.

This approach keeps the generator modular. If a single endpoint fails generation or repair, the pipeline can skip that artifact instead of failing the entire generation run immediately.

## 4. How CI Gates Production

The GitHub Actions workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) acts as the production gate:

1. Checkout the repository
2. Install Python dependencies
3. Install Node.js dependencies
4. Install Playwright browsers
5. Run `python scripts/generate_tests.py`
6. Run Playwright API tests
7. Run Playwright E2E tests
8. Upload Playwright logs and artifacts

That means production is gated by both generation success and execution success. A prompt that produces syntactically broken code, invalid selectors, or failing assertions will be caught before merge because CI executes the generated tests rather than merely checking that files exist.

If the Swagger file lives in a separate project, CI can still use this workflow as long as that file is made available to this repo and passed through `SWAGGER_PATH` or `--swagger`.

In other words:

- generation is triggered by `scripts/generate_tests.py`
- tests are executed by Playwright project runs
- CI coordinates those steps in order and fails the PR on any generation or test failure

For the provided application, CI should ensure:

- the frontend is available on port `3000`
- the backend is available on port `8080`
- the Swagger JSON is accessible to this repo as a file path

## 5. How This Scales To Many Endpoints

This approach scales because endpoint generation is naturally iterable. The plan phase can return a list of endpoints, and the generator can loop through them independently.

Why that matters:

- each endpoint is generated in isolation, so prompt size stays bounded
- failures are localized to a single endpoint instead of poisoning the entire run
- new endpoints can be added by updating the Swagger spec instead of manually writing new test files
- endpoint-specific payloads and assertions can evolve without redesigning the full pipeline

If this needed to scale further, the next steps would be:

- normalize Swagger parsing before prompt submission so the model sees only the relevant endpoint fragment
- shard generation per endpoint in CI for faster feedback
- add endpoint-level metadata such as auth requirements, negative cases, and idempotency expectations
- store generation logs per endpoint for debugging regressions

## 6. Preventing Or Detecting Incorrect Or Hallucinated Tests

Hallucinated tests are the main risk in any AI-generated test system, so the pipeline should defend against them in multiple layers.

Current safeguards in this repo:

- prompts explicitly ban invented endpoints, fields, and selectors
- the plan is constrained to known endpoints
- validation rejects placeholders and obviously incomplete code
- generated API tests are checked against Swagger-derived `/api/...` endpoints before they are saved
- generated E2E tests are checked for core checkout structure before they are saved
- CI executes the tests, which catches many false assumptions

Recommended hardening beyond the current baseline:

- parse the Swagger spec programmatically and pass only real methods, paths, schemas, and examples into prompts
- validate generated API payload keys against the spec before saving
- statically reject any generated selector or route not found in the inspected app or plan
- compare generated assertions against a whitelist of known response fields
- require generated tests to reference only endpoints present in the parsed contract
- run TypeScript compile checks before Playwright execution

The most important anti-hallucination rule is to move as much truth as possible out of the model and into deterministic pre-validation.

## 7. How To Handle Flaky Or Unstable Tests

Flaky tests should be treated as a product-quality issue, not just a test issue. The pipeline already points in the right direction by favoring deterministic inputs and stable assertions, and it also includes a determinism prompt in [`prompts/phase_7_determinism.txt`](prompts/phase_7_determinism.txt).

The right handling strategy is:

- use fixed test data
- avoid assertions on timing-sensitive or random values
- wait on observable UI states, not arbitrary sleeps
- keep assertions narrow and meaningful
- retry generation only when the failure is clearly due to malformed code, not app behavior
- quarantine and label flaky cases so they do not silently lower trust in the suite

For API tests specifically, prefer asserting status plus a small number of stable fields. For E2E tests, prefer asserting that the user-visible success state appears rather than asserting transient animations or internal timings.

## 8. How The LLM Generates E2E Selectors And Ensures Stability

The E2E prompt explicitly constrains selector strategy in [`prompts/phase_4_e2e.txt`](prompts/phase_4_e2e.txt):

1. `input[name="..."]`
2. `getByPlaceholder(...)`
3. `getByRole(...)`

That ordering is deliberate:

- `input[name]` is usually stable because it is tied to form structure rather than visual layout
- placeholder selectors are useful when placeholders are deliberate product copy
- role-based selectors are resilient for buttons and accessible controls

To keep selectors stable, the prompt also tells the model:

- do not invent selectors
- use only elements present in the UI
- use stable interactions

If I were strengthening this further, I would feed the model a precomputed selector inventory from a DOM snapshot or component render so selector generation is grounded in observed elements, not inference.

## 9. How To Prevent Flaky Frontend Tests

Frontend flakiness usually comes from weak selectors, implicit timing, shared state, and over-assertion. The prevention strategy here is:

- prefer semantic and form-bound selectors over brittle CSS chains
- use deterministic field values every run
- keep the checkout flow scoped to one happy path with one clear success assertion
- wait for element visibility or enabled state before interacting
- avoid network timing assumptions and arbitrary `waitForTimeout`
- isolate each test so prior state does not leak into the next one

Additional improvements that would make frontend tests even more stable:

- add `data-testid` hooks for business-critical elements if the UI permits it
- stub non-essential third-party calls during E2E runs
- record traces on failure and inspect repeat offenders
- run suspect tests multiple times in CI to detect flake before merge

## Prompt Files

- [`prompts/base_lean.txt`](prompts/base_lean.txt)
- [`prompts/phase_1_plan.txt`](prompts/phase_1_plan.txt)
- [`prompts/phase_2_payload.txt`](prompts/phase_2_payload.txt)
- [`prompts/phase_3_api.txt`](prompts/phase_3_api.txt)
- [`prompts/phase_4_e2e.txt`](prompts/phase_4_e2e.txt)
- [`prompts/phase_5_validate.txt`](prompts/phase_5_validate.txt)
- [`prompts/phase_6_repair.txt`](prompts/phase_6_repair.txt)
- [`prompts/phase_7_determinism.txt`](prompts/phase_7_determinism.txt)

## Core Files

- [`scripts/generate_tests.py`](scripts/generate_tests.py)
- [`scripts/validator.py`](scripts/validator.py)
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

## Why This Design Is Production-Ready

This design treats LLM generation as one component in a larger quality gate, not as an isolated convenience script.

- generation is deterministic and prompt-driven rather than manual
- Swagger acts as a contract input, and generated API tests are checked against contract endpoints
- CI executes generation, API tests, E2E tests, and artifact upload in one reproducible flow
- secrets are injected through environment variables and CI secret stores rather than source control
- the staged prompt design keeps the system maintainable as endpoint coverage grows
