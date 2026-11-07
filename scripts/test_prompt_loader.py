"""Offline Markdown loading and generation-to-repair context regressions."""

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prompt_loader
from test_generation import API_CODE, WEB_CODE, ROOT, ROUTES, contract, g, v


class PromptChecks(unittest.TestCase):
    def test_markdown_templates_load(self):
        templates = list((ROOT / 'prompts').rglob('*.md'))
        self.assertEqual(len(templates), 14)
        self.assertFalse(list((ROOT / 'prompts').rglob('*.txt')))
        for path in templates:
            with self.subTest(prompt=path.stem):
                self.assertEqual(prompt_loader.get_prompt_path(path.stem).resolve(), path)
                self.assertTrue(prompt_loader.load_prompt(path.stem).startswith('# '))
        with self.assertRaisesRegex(FileNotFoundError, 'missing_prompt.md'):
            prompt_loader.load_prompt('missing_prompt')

    def test_documentation_links_and_optional_policy(self):
        for name in ('README.md', 'AGENTS.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'prompts/[^`\s)]+\.txt')
            for reference in re.findall(r'prompts/[A-Za-z0-9_/-]+\.md', text):
                self.assertTrue((ROOT / reference).is_file(), reference)
        for path in (ROOT / 'prompts/optional').glob('*.md'):
            self.assertNotRegex(path.read_text(encoding='utf-8').lower(), 'prefer runtime behavior')

    def test_original_context_reaches_one_repair_using_only_active_prompts(self):
        used = []

        def load(name):
            used.append(name)
            return prompt_loader.load_prompt(name)

        swagger = {'paths': {}}
        for endpoint in ROUTES:
            fields = {'status': {'type': 'string'}} if endpoint.endswith('checkout') else {'valid': {'type': 'boolean'}}
            swagger['paths'].update(contract(endpoint, fields=fields)['paths'])

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(g, 'API_TESTS_DIR', Path(directory) / 'api'), \
                patch.object(g, 'WEB_TESTS_DIR', Path(directory) / 'web'), \
                patch.object(g, 'FORCE_REGENERATE', True), \
                patch.object(g, 'load_prompt', side_effect=load), \
                patch.object(v, 'load_prompt', side_effect=load):
            for endpoint in sorted(ROUTES):
                valid = API_CODE.replace('/api/checkout', endpoint)
                if not endpoint.endswith('checkout'):
                    valid = valid.replace("body.status).toBe('success')", 'body.valid).toBe(true)')
                with patch.object(g, 'call_llm', return_value='invalid'), \
                        patch.object(v, 'call_llm', return_value=valid) as repair:
                    g.generate_one_api_test(endpoint, swagger, ROUTES)
                    prompt = repair.call_args.args[0]
                    self.assertNotRegex(prompt, r'\{\{[A-Z_]+\}\}')
                    self.assertIn(endpoint, prompt)
                    self.assertIn('Original generation requirements', prompt)
                    self.assertIn('Target Swagger expectations', prompt)
                    for value in g.DETERMINISTIC_PAYLOADS[endpoint].values():
                        self.assertIn(str(value), prompt)
                    self.assertEqual(g.get_api_test_file_path(endpoint).read_text(encoding='utf-8'), valid)
                    repair.assert_called_once()
            with patch.object(g, 'call_llm', return_value='invalid'), \
                    patch.object(v, 'call_llm', return_value=WEB_CODE) as repair:
                g.generate_e2e_tests()
                prompt = repair.call_args.args[0]
                self.assertNotRegex(prompt, r'\{\{[A-Z_]+\}\}')
                for value in g.CHECKOUT_E2E_PLAN['sampleValues'].values():
                    self.assertIn(value, prompt)
                self.assertIn('inputSelectors', prompt)
                self.assertIn(g.CHECKOUT_E2E_PLAN['successText'], prompt)
                self.assertEqual(g.get_e2e_test_file_path('checkout').read_text(encoding='utf-8'), WEB_CODE)
                repair.assert_called_once()
        self.assertEqual(set(used), {'core_context', 'api_test_generation', 'e2e_test_generation', 'repair_generation'})


if __name__ == '__main__':
    unittest.main()
