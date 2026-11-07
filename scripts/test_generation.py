"""Offline contract, validation, reuse, and single-repair regressions."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
stub = types.ModuleType('llm_client')
stub.call_llm = lambda *args, **kwargs: ''
with patch.dict(sys.modules, {'llm_client': stub}):
    import validator as v
    import generate_tests as g
from swagger_loader import extract_response_expectations as extract

API_CODE = """import { test, expect } from '@playwright/test';
import { ApiHelper } from '../../utils/api-helper';

test.describe('/api/checkout API', () => {
  test('should successfully process a payment', async ({ request }) => {
    const apiHelper = new ApiHelper(request);
    const payload = {
      "cardNumber": "4242424242424242",
      "expiry": "12/34",
      "cvv": "123",
      "amount": 1000
    };

    const response = await apiHelper.post('/api/checkout', payload);
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.status).toBe('success');
    expect(body.message).toBe('Payment processed successfully!');
  });
});"""
WEB_CODE = """import { test, expect } from '@playwright/test';

test('should successfully complete a checkout transaction', async ({ page }) => {
  await page.goto('/');

  await page.locator('input[name="email"]').fill('buyer@example.com');
  await page.locator('input[name="cardNumber"]').fill('4242424242424242');
  await page.locator('input[name="expiry"]').fill('12/34');
  await page.locator('input[name="cvv"]').fill('123');
  await page.locator('input[name="amount"]').fill('100.00');

  await page.locator('button[type="submit"]').click();

  await expect(page.getByText('✅ Payment processed successfully!')).toBeVisible();
});"""

ROUTES = set(g.REQUIRED_API_ENDPOINTS)
def contract(endpoint='/api/checkout', status=200, fields=None):
    fields = fields or {'status': {'type': 'string', 'enum': ['success']}, 'message': {'type': 'string'}}
    return {'paths': {endpoint: {'post': {'responses': {str(status): {'schema': {'type': 'object', 'properties': fields}}}}}}}

class RegressionChecks(unittest.TestCase):
    def setUp(self):
        self.api = API_CODE
        self.web = WEB_CODE
        self.expected = extract(contract(), '/api/checkout')
    def valid(self, code, expected=None):
        return v.validate_test_cases(code, allowed_api_endpoints=ROUTES, api_expectations=expected or self.expected)
    def test_existing_specs(self):
        for endpoint in ROUTES:
            fields = {'status': {'type': 'string'}, 'message': {'type': 'string'}} if endpoint.endswith('checkout') else {'valid': {'type': 'boolean'}, 'message': {'type': 'string'}}
            expected = extract(contract(endpoint, fields=fields), endpoint)
            self.assertTrue(self.valid(API_CODE.replace('/api/checkout', endpoint).replace("body.status).toBe('success')", 'body.valid).toBe(true)') if not endpoint.endswith('checkout') else API_CODE, expected), endpoint)
        self.assertTrue(v.validate_test_cases(self.web, require_e2e_structure=True))
    def test_wrong_route(self):
        self.assertFalse(self.valid(API_CODE.replace('/api/checkout', '/api/validate-card')))
    def test_route_only_in_description(self):
        self.assertFalse(self.valid(self.api.replace("post('/api/checkout', payload)", "get('/api/checkout')")))
    def test_tautological_status(self):
        self.assertFalse(self.valid(self.api.replace('expect(response.status()).toBe(200)', 'expect(200).toBe(200)')))
    def test_logging_is_not_asserting(self):
        code = self.api.replace("expect(body.status).toBe('success');", 'console.log(body.status);').replace("expect(body.message).toBe('Payment processed successfully!');", 'console.log(body.message);')
        self.assertFalse(self.valid(code))
    def test_comment_is_not_asserting(self):
        self.assertFalse(self.valid(self.api.replace('expect(response.status())', '// expect(response.status())')))
    def test_unrelated_body(self):
        self.assertFalse(self.valid(self.api.replace('await response.json()', "{status:'success', message:'ok'}")))
    def test_unfilled_inputs(self):
        self.assertFalse(v.validate_test_cases(self.web.replace(".fill('buyer@example.com')", ''), require_e2e_structure=True))
    def test_constant_success(self):
        code = self.web.replace("await expect(page.getByText('✅ Payment processed successfully!')).toBeVisible()", "expect('✅ Payment processed successfully!').toBeTruthy()")
        self.assertFalse(v.validate_test_cases(code, require_e2e_structure=True))
    def test_absolute_navigation(self):
        self.assertFalse(v.validate_test_cases(self.web.replace("goto('/')", "goto('http://localhost:3000')"), require_e2e_structure=True))
    def test_201_contract(self):
        expected = extract(contract(status=201), '/api/checkout')
        self.assertTrue(self.valid(self.api.replace('toBe(200)', 'toBe(201)'), expected))
        self.assertFalse(self.valid(self.api, expected))
    def test_swagger2_reference(self):
        doc = contract()
        schema = doc['paths']['/api/checkout']['post']['responses']['200'].pop('schema')
        doc['definitions'] = {'Result': schema}
        doc['paths']['/api/checkout']['post']['responses']['200']['schema'] = {'$ref':'#/definitions/Result'}
        self.assertEqual(extract(doc, '/api/checkout')['field_names'], ['status', 'message'])
    def test_openapi3_references_allof(self):
        doc = contract(status=201)
        schema = doc['paths']['/api/checkout']['post']['responses']['201'].pop('schema')
        doc['components'] = {'schemas': {'Result': {'allOf':[schema]}}, 'responses': {'Created': {'content': {'application/json': {'schema': {'$ref':'#/components/schemas/Result'}}}}}}
        doc['paths']['/api/checkout']['post']['responses']['201'] = {'$ref':'#/components/responses/Created'}
        self.assertEqual(extract(doc, '/api/checkout')['expected_status'], 201)
    def test_missing_contract(self):
        with self.assertRaisesRegex(ValueError, 'JSON response schema'):
            extract({'paths':{'/api/checkout':{'post':{'responses':{'200':{'description':'ok'}}}}}}, '/api/checkout')
    def test_ambiguous_success(self):
        doc = contract()
        doc['paths']['/api/checkout']['post']['responses']['201'] = {'description':'created'}
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            extract(doc, '/api/checkout')
    def test_changed_fields(self):
        expected = extract(contract(fields={'success':{'type':'boolean','const':True}}), '/api/checkout')
        self.assertFalse(self.valid(self.api, expected))
        self.assertTrue(self.valid(self.api.replace("expect(body.status).toBe('success')", 'expect(body.success).toBe(true)'), expected))
    def test_repair_receives_and_rechecks_contract(self):
        expected = extract(contract(status=201), '/api/checkout')
        with patch.object(v, 'repair_test_cases', return_value=self.api.replace('toBe(200)', 'toBe(201)')) as repair:
            self.assertIsNotNone(v.validate_and_repair_test_cases(self.api, ROUTES, api_expectations=expected))
            self.assertIn('201', repair.call_args[0][1])
        with patch.object(v, 'repair_test_cases', return_value=self.api) as repair:
            self.assertIsNone(v.validate_and_repair_test_cases(self.api, ROUTES, api_expectations=expected))
            self.assertEqual(repair.call_count, 1)
    def test_reuse_rechecks_contract(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.object(g, 'FORCE_REGENERATE', False):
            path = Path(directory) / 'checkout.spec.ts'
            path.write_text(API_CODE, encoding='utf-8')
            self.assertTrue(g.should_reuse_existing_spec(path, ROUTES, api_expectations=self.expected))
            self.assertFalse(g.should_reuse_existing_spec(path, ROUTES, api_expectations=extract(contract(status=201), '/api/checkout')))

    def test_prompt_and_workflow(self):
        self.assertEqual((ROOT / '.github/workflows/ci.yml').read_text().count('branches: [master]'),2)
        prompt = g.generate_e2e_test
        self.assertIn("page.goto('/')", (ROOT / 'prompts/e2e_test_generation.md').read_text())

class ExecutionGuardChecks(unittest.TestCase):
    def test_execution_bypasses_are_rejected(self):
        bypasses = [
            "test.skip(true, 'disabled');",
            "test.fixme(true, 'disabled');",
            "test.info().skip();",
            "const skip = test.skip; skip();",
            "test['skip'](true, 'disabled');",
            "const skip = test['skip']; skip();",
            "const note = `${test.skip(true)}`;",
            "test.describe.only('focused', () => {});",
            "await page.route('**/api/checkout', route => route.fulfill({status: 200}));",
            "await page.context().route('**/*', route => route.continue());",
            "await page.routeFromHAR('cached.har');",
            "await page.routeWebSocket('**/*', socket => socket.close());",
            "const intercept = page.route;",
            "await page['route']('**/*', handler);",
        ]
        for bypass in bypasses:
            with self.subTest(bypass=bypass):
                code = WEB_CODE.replace("await page.goto('/')", bypass + "\n  await page.goto('/')")
                self.assertIsNotNone(v.find_validation_error(code, require_e2e_structure=True))
                api = API_CODE.replace('const apiHelper', bypass + '\n const apiHelper')
                self.assertIsNotNone(v.find_validation_error(api, ROUTES, api_expectations=extract(contract(), '/api/checkout')))

    def test_strings_and_comments_do_not_trigger_guards(self):
        additions = [
            "// test.skip(true); page.route('**/*', handler);\n",
            "/* test.fixme(true); */\n",
            "const note = \"test.skip and page.route are forbidden\";\n",
            "const note = `Do not use test.skip\nor page.route`;\n",
        ]
        for addition in additions:
            with self.subTest(addition=addition):
                self.assertTrue(v.validate_test_cases(addition + WEB_CODE, require_e2e_structure=True))

    def test_repair_cannot_preserve_skip(self):
        broken = WEB_CODE.replace("await page.goto('/')", "test.skip(true, 'disabled'); await page.goto('/')")
        with patch.object(v, 'repair_test_cases', return_value=broken) as repair:
            self.assertIsNone(v.validate_and_repair_test_cases(broken, require_e2e_structure=True))
            self.assertEqual(repair.call_count, 1)

    def test_reuse_rejects_bypassed_spec(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.object(g, 'FORCE_REGENERATE', False):
            path = Path(directory) / 'checkout.spec.ts'
            path.write_text(WEB_CODE.replace("await page.goto('/')", "test.skip(true); await page.goto('/')"), encoding='utf-8')
            self.assertFalse(g.should_reuse_existing_spec(path, require_e2e_structure=True))


if __name__ == '__main__':
    unittest.main()
