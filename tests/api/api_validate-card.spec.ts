import { test, expect } from '@playwright/test';
import { ApiHelper } from '../../utils/api-helper';

test.describe('/api/validate-card API', () => {
  test('should validate card number', async ({ request }) => {
    const apiHelper = new ApiHelper(request);
    const payload = {
      cardNumber: '4242424242424242'
    };

    const response = await apiHelper.post('/api/validate-card', payload);
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.valid).toBe(true);
    expect(body.message).toBe('Card number validated');
  });
});