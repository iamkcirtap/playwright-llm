import { test, expect } from '@playwright/test';
import { ApiHelper } from '../../utils/api-helper';

test.describe('/api/checkout API', () => {
  test('should process checkout successfully', async ({ request }) => {
    const apiHelper = new ApiHelper(request);
    const endpoint = '/api/checkout';
    const payload = {
      cardNumber: '4242424242424242',
      expiry: '12/34',
      cvv: '123',
      amount: 1000
    };

    const response = await apiHelper.post(endpoint, payload);
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.status).toBe('success');
    expect(body.message).toBeDefined();
  });
});