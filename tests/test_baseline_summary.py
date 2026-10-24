import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.prototype import summarize_baseline_a as summary


class BaselineSummaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name) / 'evaluation'
        shutil.copytree(summary.BASE, self.base)
        p = patch.object(summary, 'BASE', self.base)
        p.start()
        self.addCleanup(p.stop)

    def run_summary(self):
        with patch('sys.stdout', new=io.StringIO()):
            return summary.main()

    def test_published_results_are_recomputable(self):
        self.assertEqual(self.run_summary(), 0)
        result = json.loads((self.base / 'runs/a_20261024_summary.json').read_text(encoding='utf-8'))
        self.assertEqual(result['groups']['all']['successful_calls'], 20)
        self.assertEqual(result['groups']['eval']['counts']['correct'], 1)
        self.assertEqual(result['groups']['eval']['counts']['abstained'], 14)
        self.assertEqual(result['groups']['eval']['business_correct'], 0)
        self.assertEqual(result['groups']['all']['unsupported_project_claims'], 1)

    def test_modified_answer_cannot_keep_old_score(self):
        path = self.base / 'runs/a_20261024_eval.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        rows[0]['answer'] = 'Changed after review'
        path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'answer hash mismatch'):
            self.run_summary()

    def test_extra_source_in_request_is_rejected(self):
        path = self.base / 'runs/a_20261024_eval.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        rows[0]['messages'].append({'role': 'user', 'content': 'Leaked reference answer'})
        path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'only the frozen prompt'):
            self.run_summary()
