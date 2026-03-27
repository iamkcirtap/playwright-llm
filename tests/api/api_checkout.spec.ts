import { test, expect } from '@playwright/test';

test.describe('API - Checkout', () => {
  const BASE_API_URL = 'http://localhost:8080';

  test('should successfully process a checkout with valid data', async ({ request }) => {
    const payload = {
      email: 'test@example.com',
      cardNumber: '4111222233334444',
      expiry: '12/25',
      cvv: '123',
      amount: 100.0
    };

    const response = await request.post(`${BASE_API_URL}/api/checkout`, {
      data: payload,
    });

    expect(response.status()).toBe(200);

    const responseBody = await response.json();
    expect(responseBody).toHaveProperty('status');
    expect(responseBody.status).toBe('success');
    expect(responseBody).toHaveProperty('message');
    expect(responseBody.message).toBe('Checkout successful');
  });
});