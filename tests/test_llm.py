import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from bizcodeqa.config import load_env
from bizcodeqa.llm import chat, NoRedirect


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LLM_BASE_URL': 'https://example.test/v1/',
                             'LLM_API_KEY': 'test-secret', 'LLM_MODEL': 'test-model'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_request_and_completion(self):
        with patch('urllib.request.OpenerDirector.open') as opened:
            opened.return_value.__enter__.return_value = io.StringIO(json.dumps(
                {'choices': [{'message': {'content': 'OK'}}], 'usage': {'total_tokens': 7}}))
            result = chat([{'role': 'user', 'content': 'ping'}])
            request = opened.call_args.args[0]
            self.assertEqual(request.full_url, 'https://example.test/v1/chat/completions')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
            self.assertEqual(json.loads(request.data)['model'], 'test-model')
            self.assertEqual(result['content'], 'OK')

    def test_deepseek_thinking_disabled(self):
        os.environ['LLM_THINKING'] = 'disabled'
        with patch('urllib.request.OpenerDirector.open') as opened:
            opened.return_value.__enter__.return_value = io.StringIO(
                '{"choices": [{"message": {"content": "OK"}}]}')
            chat([])
            self.assertEqual(json.loads(opened.call_args.args[0].data)['thinking'],
                             {'type': 'disabled'})

    def test_invalid_thinking_fails_before_network(self):
        os.environ['LLM_THINKING'] = 'invalid'
        with self.assertRaisesRegex(ValueError, 'thinking mode'):
            chat([])

    def test_http_errors_are_redacted(self):
        for code in (400, 401, 403, 404, 429, 500):
            with self.subTest(code=code), patch('urllib.request.OpenerDirector.open',
                    side_effect=HTTPError('https://test-secret', code, 'test-secret', {}, None)):
                with self.assertRaises(RuntimeError) as error:
                    chat([])
                self.assertNotIn('test-secret', str(error.exception))
                self.assertIn(str(code), str(error.exception))

    def test_network_failure_is_redacted(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=URLError('test-secret')):
            with self.assertRaisesRegex(RuntimeError, 'network/TLS/timeout'):
                chat([])

    def test_empty_completion_fails(self):
        with patch('urllib.request.OpenerDirector.open') as opened:
            opened.return_value.__enter__.return_value = io.StringIO('{"choices": []}')
            with self.assertRaisesRegex(RuntimeError, 'no non-empty'):
                chat([])

    def test_missing_key_fails_before_network(self):
        os.environ['LLM_API_KEY'] = ''
        with self.assertRaisesRegex(ValueError, 'LLM_API_KEY'):
            chat([])

    def test_remote_http_rejected(self):
        os.environ['LLM_BASE_URL'] = 'http://example.test/v1'
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            chat([])

    def test_redirect_does_not_forward_credentials(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))

    def test_env_preserves_process_override(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.env'
            path.write_text('LLM_MODEL=file-model\nEXTRA=value\n', encoding='utf-8')
            load_env(path)
            self.assertEqual(os.environ['LLM_MODEL'], 'test-model')
            self.assertEqual(os.environ['EXTRA'], 'value')


if __name__ == '__main__':
    unittest.main()
