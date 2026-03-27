import { test, expect } from '@playwright/test';

test.describe('API - /api/validate-card', () => {
  test('should successfully validate a card with valid details', async ({ request }) => {
    const response = await request.post('http://localhost:8080/api/validate-card', {
      data: {
        cardNumber: '4111222233334444',
        expiry: '12/25',
        cvv: '123',
      },
    });

    expect(response.status()).toBe(200);

    const responseBody = await response.json();
    expect(responseBody).toHaveProperty('valid');
    expect(responseBody.valid).toBe(true);
  });
});