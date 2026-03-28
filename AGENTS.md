# AGENTS.md

## Overview

This repository implements an AI-driven Playwright test generation pipeline using Google Gemini.

The system generates:

- API tests from Swagger/OpenAPI definitions
- one E2E checkout flow

Generated tests are then executed in CI as a quality gate.

---

## Core Objective

Build a reproducible, low-maintenance automation flow where:

- tests are generated programmatically with Gemini
- tests validate real application behavior
- tests run in CI and fail on regression
- manual maintenance stays minimal

---

## Constraints

- Do NOT modify `playwright.config.ts`
- Do NOT change the existing project structure
- Output only runnable `.spec.ts` files
- Do NOT include placeholders or TODOs
- Do NOT invent endpoints, fields, or UI elements
- Use deterministic inputs

---

## Required Coverage

The following endpoints must be covered:

- `/api/checkout`
- `/api/validate-card`
- `/api/validate-email`

Additionally:

- generate at least one full E2E checkout flow

---

## Source Of Truth

- Swagger/OpenAPI is the contract guide
- Actual runtime behavior takes priority if Swagger and runtime differ

---

## Test Design Rules

### API Tests

- Send valid deterministic payloads
- Assert HTTP status
- Assert at least one meaningful response field
- Keep each test self-contained

### E2E Tests

Must:

- fill email, cardNumber, expiry, cvv, and amount
- submit the checkout form
- assert a visible success state

Selector priority:

1. `input[name="..."]`
2. `getByPlaceholder(...)`
3. `getByRole(...)`
4. CSS fallback only if needed

Avoid:

- `getByLabel` unless clearly valid
- `data-testid` assumptions when not present

---

## Determinism Rules

- Use fixed input values
- Avoid randomness
- Avoid timing assumptions
- Prefer Playwright waiting over manual sleeps

---

## Generation Flow

1. Load Swagger and prompts
2. Confirm required endpoints exist
3. For each required API endpoint:
   - use a fixed deterministic payload
   - generate the API test with Gemini
   - validate the generated code
   - repair once if invalid
   - save only valid output
4. Generate one checkout E2E test with Gemini
5. Validate and repair once if needed
6. Save only valid output
7. Reuse existing valid specs and simple cached LLM responses when available

---

## Validation Rules

A generated test is valid if it:

- contains `test()`
- contains `expect()`
- contains imports
- has no placeholders or TODOs
- references only allowed API routes for API specs
- includes the required checkout structure for E2E specs

If invalid:

- attempt one repair using Gemini
- if still invalid, skip the file

---

## Environment Assumption

The pipeline assumes the target application is already running and reachable.

Environment variables:

- `GEMINI_API_KEY` -> Gemini access
- `SWAGGER_PATH` -> optional Swagger path or URL
- `FORCE_REGENERATE` -> regenerate specs even when valid ones already exist
- `LLM_CACHE_VERSION` -> bump when prompt strategy changes

---

## Error Handling

- Validation failures trigger one repair attempt
- Invalid outputs are skipped
- Temporary Gemini failures such as rate limits are retried with backoff
- Cached responses may be reused to reduce repeated API calls

---

## Non-Goals

- No framework redesign
- No Playwright config changes
- No complex validation engine
- No multi-LLM orchestration
- No complex caching layer

---

## Summary

This system demonstrates:

- AI-driven test generation
- contract-aware automation
- deterministic test generation inputs
- CI-integrated quality gating
- simple rate-limit-aware caching
