import { test, expect } from '@playwright/test';
import { ApiHelper } from '../../utils/api-helper';

test.describe('/api/validate-card API', () => {
  test('should validate a credit card number successfully', async ({ request }) => {
    const apiHelper = new ApiHelper(request);
    const endpoint = '/api/validate-card';
    const payload = {
      cardNumber: '4242424242424242',
    };

    const response = await apiHelper.post(endpoint, payload);
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.message).toBe('Card number validated');
    expect(body.valid).toBe(true);
  });
});