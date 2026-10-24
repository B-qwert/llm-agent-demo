import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bizcodeqa import baseline


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.questions = self.root / 'questions.json'
        self.prompt = self.root / 'prompt.json'
        self.questions.write_text(json.dumps({'source_commit_sha': 'a' * 40, 'questions': [
            {'question_id': 'Q1', 'question': 'How does borrowing work?', 'split': 'dev'},
            {'question_id': 'Q2', 'question': 'How does return work?', 'split': 'eval'}]}))
        self.prompt.write_text(json.dumps({'system': 'Do not invent.', 'user_prefix': 'Question: '}))
        self.out = self.root / 'results.jsonl'
        for attribute, value in [('DATASET', self.questions), ('PROMPT', self.prompt)]:
            p = patch.object(baseline, attribute, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'LLM_BASE_URL': 'https://example.test',
                                   'LLM_MODEL': 'test-model', 'LLM_API_KEY': 'private-secret'}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(baseline, 'load_env')
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(baseline.subprocess, 'check_output', return_value='b' * 40)
        p.start()
        self.addCleanup(p.stop)

    def run_silent(self, *args):
        with patch('sys.stdout', new=io.StringIO()):
            return baseline.main(['--output', str(self.out), *args])

    def test_preview_never_calls_api_or_creates_results(self):
        with patch.object(baseline, 'chat') as call:
            self.assertEqual(self.run_silent(), 0)
            call.assert_not_called()
            self.assertFalse(self.out.exists())

    def test_rejects_gold_fields_in_question_file(self):
        dataset = json.loads(self.questions.read_text())
        dataset['questions'][0]['reference_answer'] = 'secret gold'
        self.questions.write_text(json.dumps(dataset))
        with self.assertRaises(ValueError):
            self.run_silent()

    def test_isolated_requests_resume_and_no_key_in_artifact(self):
        response = {'content': 'Cannot determine.', 'model': 'test-model',
                    'usage': {'total_tokens': 12}, 'finish_reason': 'stop'}
        with patch.object(baseline, 'chat', return_value=response) as call:
            self.assertEqual(self.run_silent('--split', 'all', '--execute'), 0)
            self.assertEqual(call.call_count, 2)
            for invocation in call.call_args_list:
                self.assertEqual(len(invocation.args[0]), 2)
                self.assertEqual([m['role'] for m in invocation.args[0]], ['system', 'user'])
            self.assertNotIn('private-secret', self.out.read_text())
            call.reset_mock()
            self.assertEqual(self.run_silent('--split', 'all', '--execute', '--resume'), 0)
            call.assert_not_called()
            with self.assertRaises(ValueError):
                self.run_silent('--execute', '--resume', '--max-tokens', '2048')
            call.assert_not_called()

    def test_error_stops_batch_and_redacts_details(self):
        with patch.object(baseline, 'chat', side_effect=RuntimeError('private-secret upstream body')) as call:
            self.assertEqual(self.run_silent('--split', 'all', '--execute'), 1)
            self.assertEqual(call.call_count, 1)
        row = json.loads(self.out.read_text())
        self.assertEqual(row['status'], 'error')
        self.assertNotIn('private-secret', self.out.read_text())

    def test_truncated_answer_is_not_success(self):
        response = {'content': 'partial...', 'model': 'test-model', 'usage': {}, 'finish_reason': 'length'}
        with patch.object(baseline, 'chat', return_value=response):
            self.assertEqual(self.run_silent('--execute'), 1)
        self.assertEqual(json.loads(self.out.read_text())['status'], 'incomplete')
