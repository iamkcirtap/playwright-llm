import { test, expect } from '@playwright/test';

test('successful checkout flow', async ({ page }) => {
  // Frontend target is the checkout page on http://localhost:3000
  await page.goto('http://localhost:3000');

  // Fill email field using input[name] selector
  await page.locator('input[name="email"]').fill('test@example.com');

  // Fill card number field using input[name] selector
  await page.locator('input[name="cardNumber"]').fill('4111222233334444');

  // Fill expiry field using input[name] selector
  await page.locator('input[name="expiry"]').fill('12/25');

  // Fill CVV field using input[name] selector
  await page.locator('input[name="cvv"]').fill('123');

  // Fill amount field using input[name] selector
  await page.locator('input[name="amount"]').fill('100.00');

  // Submit form by clicking a button with the text "Checkout"
  await page.getByRole('button', { name: 'Checkout' }).click();

  // Assert a visible success state that reflects successful checkout
  // Prefer waiting for visible success UI states rather than using timeouts
  await expect(page.getByText('Checkout successful!')).toBeVisible();
});