import { test, expect } from '@playwright/test';

test('should successfully complete a checkout transaction', async ({ page }) => {
  await page.goto('http://localhost:3000');

  await page.locator('input[name="email"]').fill('buyer@example.com');
  await page.locator('input[name="cardNumber"]').fill('4242424242424242');
  await page.locator('input[name="expiry"]').fill('12/34');
  await page.locator('input[name="cvv"]').fill('123');
  await page.locator('input[name="amount"]').fill('100.00');

  await page.locator('button[type="submit"]').click();

  await expect(page.getByText('✅ Payment processed successfully!')).toBeVisible();
});