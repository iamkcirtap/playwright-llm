# API happy-path test

## Task

Generate exactly one deterministic happy-path test for the supplied POST endpoint. Do not add negative or edge-case tests.

## Supplied context

### Target endpoint

{{ENDPOINT}}

### Swagger operation and validation expectations

{{ENDPOINT_SPEC}}

### Authoritative request payload

{{PAYLOAD}}

## Required structure

- Import `test` and `expect` from `@playwright/test` and `{ ApiHelper }` from `../../utils/api-helper`.
- Wrap one `test()` in `test.describe('<target endpoint> API', ...)` and use the `request` fixture.
- Create `const apiHelper = new ApiHelper(request);`.
- Declare `const endpoint` using the supplied relative route as a string literal and `const payload` using the supplied JSON values exactly.
- Send `const response = await apiHelper.post(endpoint, payload);`.
- Assert `expect(response.status()).toBe(...)` using the numeric literal in `validation_expectations.expected_status`.
- Parse `const body = await response.json();` and assert one or two fields listed in `validation_expectations.field_names`.

## Assertion policy

- For a field with a contract `const` or single-value `enum`, assert that exact value with `expect(body.field).toBe(...)`.
- When only a primitive type is guaranteed, use `expect(typeof body.field).toBe(...)` with the schema's JavaScript type. A schema example alone does not guarantee an exact value.
- Do not invent response values, assert IDs or timestamps, or turn a contract mismatch into an expected success.
- Assert exact message text only when the contract guarantees it.
- Use direct assertions and literal arguments so the lightweight validator can verify them. Do not hide requests or assertions in helper wrappers.

## Output

Return the complete `.spec.ts` file only.
