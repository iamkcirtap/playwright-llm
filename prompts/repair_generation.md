# Repair a generated Playwright spec

## Task

Correct the supplied spec to satisfy the original generation requirements and validation error. This is the single repair attempt.

## Original generation requirements

{{GENERATION_CONTEXT}}

## Validation error and Swagger expectations

{{ERROR}}

## Spec to repair

{{TEST_CODE}}

## Requirements

- Preserve the supplied target route, POST method, exact payload or checkout sample values, and Swagger success expectations.
- Apply the original task's required direct request, action, and assertion structure. Fix syntax, imports, selectors, and awaited operations as needed.
- Keep exactly one happy-path `test()` and meaningful assertions on the actual response or visible UI.
- Never weaken assertions, change contract expectations to match a backend bug, invent missing facts, mock success, or bypass failures.
- For API tests, assert the numeric contract status literal and at least one supported parsed body field. Preserve contract const and single-enum values.
- For checkout, navigate relatively, fill every supplied input using literal values, click the submit selector, and then await the exact visible success assertion.

## Output

Return the complete corrected `.spec.ts` file only.
