# Checkout happy-path test

## Task

Generate exactly one `test()` covering the complete checkout happy path. Do not add negative or edge-case scenarios.

## Supplied context

The checkout plan supplies selectors and success text established by the existing checkout spec, plus fixed sample values:

{{E2E_PLAN}}

## Required actions

1. Import `test` and `expect` from `@playwright/test` and use the `page` fixture.
2. Navigate with `await page.goto('/');` to respect the configured frontend baseURL.
3. Fill email, cardNumber, expiry, cvv, and amount before submitting. For each field, use a direct `await page.locator('<supplied input selector>').fill('<supplied sample value>');` call. Inline both selector and sample value as string literals.
4. Submit with `await page.locator('button[type="submit"]').click();`.
5. After submission, assert `await expect(page.getByText('✅ Payment processed successfully!')).toBeVisible();` using the plan's exact success text.

## Requirements

- Use the plan's selectors, fixed values, and success text exactly.
- The known checkout inputs support `input[name="..."]`; use those selectors directly. Alternative selectors require an updated verified plan and compatible validator.
- Do not introduce page objects, locator aliases, helper wrappers, guessed labels, or assumed data-testid attributes.
- Let the awaited visible assertion wait for success; do not use manual sleeps or network timing assumptions.

## Output

Return the complete `.spec.ts` file only.
