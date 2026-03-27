# AGENTS.md

## Overview

This repository implements an AI-driven Playwright test generation pipeline using Google Gemini.

The system automatically generates:
- API tests from Swagger/OpenAPI definitions
- E2E tests for the checkout flow

Generated tests are executed in CI as a quality gate.

---

## Core Objective

Build a reproducible, low-maintenance test automation system where:

- Tests are generated programmatically using an LLM (Gemini)
- Tests validate real application behavior
- Tests run in CI and fail on regression
- Minimal manual test maintenance is required

---

## Constraints

- Do NOT modify `playwright.config.ts`
- Do NOT change existing project structure
- Output only runnable `.spec.ts` files
- Do NOT include placeholders or TODOs
- Do NOT invent endpoints, fields, or UI elements
- Use deterministic inputs (no randomness)

---

## LLM Usage

- All test generation must be done via Google Gemini API
- Prompts must be structured and deterministic
- Output must be consistent across runs

---

## Test Coverage Requirements

The following endpoints MUST be fully covered:

- `/api/checkout`
- `/api/validate-card`
- `/api/validate-email`

Additionally:
- At least one full E2E checkout flow must be generated

---

## Source of Truth

- Swagger/OpenAPI is used as guidance
- Actual runtime behavior takes priority if discrepancies exist

---

## Test Design Rules

### API Tests

- Must send valid request payloads
- Must assert HTTP status
- Must assert at least one meaningful response field
- Must be self-contained (no dependency on helpers)

---

### E2E Tests

Must:
- Fill required fields (email, cardNumber, expiry, cvv, amount)
- Submit the checkout form
- Assert a visible success state

Selector priority:
1. `input[name="..."]`
2. `getByPlaceholder(...)`
3. `getByRole(...)`
4. CSS fallback (last resort)

Avoid:
- `getByLabel` unless explicitly valid
- `data-testid` (not present in UI)

---

## Determinism Rules

- Use fixed input values
- Avoid randomness
- Avoid timing assumptions
- Prefer Playwright built-in waiting

---

## Generation Flow

1. Load Swagger and prompts
2. Generate test plan (LLM)
3. For each endpoint:
   - Generate payload (LLM)
   - Generate API test (LLM)
   - Validate test
   - Repair once if invalid (LLM)
   - Save test
4. Generate E2E test (LLM)
5. Validate and repair
6. Save test

---

## Validation Rules

A generated test is considered valid if:

- Contains `test()`
- Contains `expect()`
- Is syntactically valid
- Has no placeholders or TODOs

If invalid:
- Attempt one repair using LLM
- If still invalid, skip

---

## CI/CD Requirements

The CI pipeline must:

- Execute test generation
- Run Playwright API tests
- Run Playwright E2E tests
- Fail the pipeline if any test fails
- Produce test reports/artifacts

---

## Environment Assumption

The CI pipeline assumes the application is already running and accessible via `BASE_URL`, based on assessment clarification.

Environment variables:

- `GEMINI_API_KEY` → used for LLM generation
- `BASE_URL` → target application URL

---

## Real-World Consideration

In a production setup, CI would also:

- Start backend and frontend services
- Wait for service readiness
- Run tests in an isolated environment

This is intentionally omitted to align with assessment scope.

---

## Project Structure
scripts/
generate_tests.py
llm_client.py
validator.py
prompt_loader.py

prompts/
base.txt
phase*.txt

tests/
api/
web/

docs/
swagger.json

---

## Error Handling

- Validation failures trigger one repair attempt
- No retry loops beyond one repair
- Invalid tests are skipped

---

## Non-Goals

- No framework redesign
- No Playwright config changes
- No complex validation engines
- No multi-LLM orchestration
- No caching layers

---

## Summary

This system demonstrates:

- AI-driven test generation
- CI-integrated quality gate
- Regeneratable test automation
- Alignment with modern SDLC and STLC practices