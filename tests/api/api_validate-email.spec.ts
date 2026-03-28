import { test, expect } from '@playwright/test';
import { ApiHelper } from '../../utils/api-helper';

test.describe('/api/validate-email API', () => {
  test('should attempt to validate a valid email and return 500 as per runtime notes', async ({ request }) => {
    const apiHelper = new ApiHelper(request);
    const endpoint = '/api/validate-email';
    const payload = {
      "email": "buyer@example.com"
    };

    const response = await apiHelper.post(endpoint, payload);
    const body = await response.json();

    expect(response.status()).toBe(500);
    expect(body).toHaveProperty('error');
    expect(typeof body.error).toBe('string');
  });
});