import { test, expect } from '@playwright/test';
import { ApiHelper } from '../../utils/api-helper';

test.describe('/api/validate-email API', () => {
    test('should return 200 for valid email validation', async ({ request }) => {
        const apiHelper = new ApiHelper(request);
        const endpoint = '/api/validate-email';
        const payload = {
            email: 'buyer@example.com',
        };

        const response = await apiHelper.post(endpoint, payload);
        const body = await response.json();

        expect(response.status()).toBe(200);
        expect(body.valid).toBe(true);
        expect(typeof body.message).toBe('string');
    });
});
