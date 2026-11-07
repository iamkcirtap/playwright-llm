# Phase 1 plan

> Optional reference: not loaded by the active happy-path generation flow.

Prepare a minimal Playwright generation plan from Swagger and runtime context.

## Requirements

- Include only supported /api/... routes from the contract
- Must cover /api/checkout, /api/validate-card, /api/validate-email
- Exclude /api/health
- Keep Swagger contract expectations when runtime differs
- Use deterministic realistic payloads
- Choose stable schema-based assertions when possible
- Include one stable checkout happy-path E2E flow using email, cardNumber, expiry, cvv, amount
- Keep output minimal, complete, and machine-readable

## Output

## Output

Return JSON only. The shape below is illustrative; derive status, payload, and assertions from the supplied Swagger, rather than copying example values.

```json
{
    "api": [
        {
            "endpoint": "/api/checkout",
            "method": "POST",
            "payload": {},
            "expectedStatus": 200,
            "keyAssertions": ["status", "message"]
        }
    ],
    "e2e": {
        "flow": "checkout",
        "fields": ["email", "cardNumber", "expiry", "cvv", "amount"],
        "success": ["success message"]
    }
}
```
