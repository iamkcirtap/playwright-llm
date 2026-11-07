"""Offline provider adapter, retry, credential, and cache regressions."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

stub = types.ModuleType('env_loader')
stub.load_local_env = lambda: None

def load(provider='gemini', model='model-a,model-b', **env):
    with patch.dict(sys.modules, {'env_loader': stub}), patch.dict(os.environ, {'LLM_PROVIDER':provider, 'LLM_MODEL':model,
                               'LLM_CACHE_ENABLED':'false', 'LLM_MAX_RETRIES':'2',
                               **env}, clear=True):
        spec = importlib.util.spec_from_file_location('tested_llm', Path(__file__).with_name('llm_client.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

def http(code):
    return urllib.error.HTTPError('https://provider.invalid', code, 'test', {}, io.BytesIO(b'private error'))

class ProviderChecks(unittest.TestCase):
    def test_default_gemini_models(self):
        c = load(model='')
        self.assertEqual(c.MODEL_FALLBACK_ORDER[0], 'gemini-2.5-flash')
    def test_bad_provider(self):
        with self.assertRaisesRegex(ValueError,'LLM_PROVIDER'):
            load('typo')
    def test_models_required(self):
        for provider in ('openai','anthropic'):
            with self.assertRaisesRegex(ValueError,'LLM_MODEL'):
                load(provider, '')
    def test_only_selected_key(self):
        for provider, variable in (('gemini','GEMINI_API_KEY'),('openai','OPENAI_API_KEY'),('anthropic','ANTHROPIC_API_KEY')):
            c = load(provider)
            with patch.dict(os.environ, {variable:'selected-key'}, clear=True):
                self.assertEqual(c.load_api_key(),'selected-key')
            with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, variable):
                c.load_api_key()
    def test_openai_response_and_body(self):
        c = load('openai')
        response = {'status':'completed','output':[{'type':'reasoning'}, {'type':'message','role':'assistant','content':[{'type':'output_text','text':' code '}]}]}
        with patch.object(c, 'post_json', return_value=response) as send:
            self.assertEqual(c.request_model('model','prompt',123,'secret'),'code')
            url, headers, body = send.call_args.args
            self.assertEqual(url,'https://api.openai.com/v1/responses')
            self.assertEqual(headers['Authorization'],'Bearer secret')
            self.assertEqual(body,{'model':'model','input':'prompt','max_output_tokens':123,'store':False})
    def test_anthropic_response_and_body(self):
        c = load('anthropic')
        response = {'stop_reason':'end_turn','content':[{'type':'thinking','thinking':'hidden'}, {'type':'text','text':' code '}]}
        with patch.object(c, 'post_json', return_value=response) as send:
            self.assertEqual(c.request_model('model','prompt',123,'secret'),'code')
            url, headers, body = send.call_args.args
            self.assertEqual(url,'https://api.anthropic.com/v1/messages')
            self.assertEqual(headers,{'x-api-key':'secret','anthropic-version':'2026-10-21'})
            self.assertEqual(body['messages'],[{'role':'user','content':'prompt'}])
            self.assertEqual(body['max_tokens'],123)
    def test_gemini_sdk_is_lazy_and_request_works(self):
        c = load()
        response = types.SimpleNamespace(text=' code ', candidates=[])
        client = MagicMock()
        client.__enter__.return_value.models.generate_content.return_value = response
        api = types.ModuleType('google.genai')
        api.Client = MagicMock(return_value=client)
        api.types = types.SimpleNamespace(HttpOptions=lambda **k:k, GenerateContentConfig=lambda **k:k)
        with patch.dict(sys.modules, {'google.genai':api}):
            self.assertEqual(c.request_model('model','prompt',123,'secret'),'code')
            client.__enter__.return_value.models.generate_content.assert_called_once_with(model='model', contents='prompt', config={'max_output_tokens':123})
            client.__exit__.assert_called_once()
    def test_incomplete_and_empty_outputs_rejected(self):
        for provider, response in [('openai',{'status':'incomplete','output':[]}), ('openai',{'status':'completed','output':[]}), ('anthropic',{'stop_reason':'max_tokens','content':[{'type':'text','text':'partial'}]}), ('anthropic',{'stop_reason':'end_turn','content':[]})]:
            c=load(provider)
            with patch.object(c,'post_json',return_value=response), self.assertRaises(ValueError):
                c.request_model('model','prompt',100,'secret')
    def test_http_serialization_and_timeout(self):
        c=load('openai')
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"ok": true}'
        with patch.object(c.urllib.request,'urlopen',return_value=response) as send:
            self.assertEqual(c.post_json('https://example.invalid',{'Authorization':'Bearer secret'},{'input':'hello'}),{'ok':True})
            request=send.call_args.args[0]
            self.assertEqual(request.method,'POST')
            self.assertEqual(json.loads(request.data),{'input':'hello'})
            self.assertEqual(send.call_args.kwargs['timeout'],120)
    def test_transient_retry(self):
        for provider, status in [('gemini',503),('openai',500),('anthropic',529)]:
            c=load(provider)
            with patch.object(c,'load_api_key',return_value='secret'), patch.object(c,'request_model',side_effect=[http(status),'code']) as send, patch.object(c.time,'sleep') as sleep:
                self.assertEqual(c.call_llm('prompt'),'code')
                self.assertEqual(send.call_count,2)
                sleep.assert_called_once_with(1)
    def test_quota_fallback_stays_in_provider(self):
        c=load('openai')
        with patch.object(c,'load_api_key',return_value='secret'), patch.object(c,'request_model',side_effect=[http(429),http(429),'code']) as send, patch.object(c.time,'sleep'):
            self.assertEqual(c.call_llm('prompt'),'code')
            self.assertEqual([call.args[0] for call in send.call_args_list],['model-a','model-a','model-b'])
    def test_auth_and_invalid_fail_fast(self):
        for status in (400,401,403,404):
            c=load('anthropic')
            with patch.object(c,'load_api_key',return_value='secret'), patch.object(c,'request_model',side_effect=http(status)) as send, patch.object(c.time,'sleep') as sleep, self.assertRaises(RuntimeError):
                c.call_llm('prompt')
            self.assertEqual(send.call_count,1)
            sleep.assert_not_called()
    def test_retry_exhaustion(self):
        c=load('openai', 'only-model')
        with patch.object(c,'load_api_key',return_value='secret'), patch.object(c,'request_model',side_effect=http(429)) as send, patch.object(c.time,'sleep'), self.assertRaises(RuntimeError):
            c.call_llm('prompt')
        self.assertEqual(send.call_count,2)
    def test_cache_identity(self):
        c=load('openai')
        base=c.get_cache_path('key','model','prompt',100)
        self.assertNotEqual(base,c.get_cache_path('key','other','prompt',100))
        self.assertNotEqual(base,c.get_cache_path('key','model','changed',100))
        self.assertNotEqual(base,c.get_cache_path('key','model','prompt',200))
        c.LLM_PROVIDER='anthropic'
        self.assertNotEqual(base,c.get_cache_path('key','model','prompt',100))
        self.assertEqual(c.get_cache_path('../escape','model','prompt',100).parent,c.CACHE_DIR)
    def test_cache_reuse_without_network_or_key(self):
        c=load('openai')
        with tempfile.TemporaryDirectory() as folder:
            c.CACHE_DIR=Path(folder);c.USE_CACHE=True
            with patch.object(c,'load_api_key',return_value='secret'), patch.object(c,'request_model',return_value='code'):
                self.assertEqual(c.call_llm('prompt',cache_key='key'),'code')
            with patch.object(c,'load_api_key',side_effect=AssertionError('key needed')), patch.object(c,'request_model',side_effect=AssertionError('network used')):
                self.assertEqual(c.call_llm('prompt',cache_key='key'),'code')
    def test_failed_responses_not_cached(self):
        c=load('openai')
        with tempfile.TemporaryDirectory() as folder:
            c.CACHE_DIR=Path(folder);c.USE_CACHE=True
            with patch.object(c,'load_api_key',return_value='secret'),patch.object(c,'request_model',side_effect=ValueError('incomplete')), self.assertRaises(RuntimeError):
                c.call_llm('prompt',cache_key='key')
            self.assertEqual(list(c.CACHE_DIR.iterdir()),[])
    def test_invalid_retry_count(self):
        with self.assertRaisesRegex(ValueError,'positive'):
            load(LLM_MAX_RETRIES='0')

if __name__ == '__main__':
    unittest.main()
