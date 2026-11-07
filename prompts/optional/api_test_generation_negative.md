# Api test generation negative

> Optional reference: not loaded by the active happy-path generation flow.

Generate a Playwright API negative/edge-case test.

## Endpoint

{{ENDPOINT}}

## Endpoint spec

{{ENDPOINT_SPEC}}

## Payload

{{PAYLOAD}}

## Negative case context

{{NEGATIVE_CASE}}

## Requirements

- Use the provided endpoint exactly as given
- Import `ApiHelper` as a named import from `../../utils/api-helper`
- When using `ApiHelper`, construct it from Playwright's `request` fixture
- Wrap the test in `test.describe('<endpoint> API negative', ...)`
- Parse the JSON response into `const body = await response.json()`
- Use relative API endpoints such as `/api/checkout`, never absolute URLs
- For GET: use `apiHelper.get(endpoint)`
- For POST: use `apiHelper.post(endpoint, payload)`
- Generate exactly one deterministic negative/edge-case test for the endpoint
- Assert the status and 1-2 stable response fields defined by NEGATIVE_CASE and the contract; validation may return 200 with valid: false
- Prefer stable fields such as `error`, `message`, `status`, or `valid`
- Do not invent request or response properties
- Do not assert unstable text, IDs, or timestamps
- Keep output self-contained, deterministic, and runnable
- Return code only. No markdown fences. No explanation.

## Output

Return full .spec.ts file only.
