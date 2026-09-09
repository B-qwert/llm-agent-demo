import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bizcodeqa.check import main


class ReportTests(unittest.TestCase):
    def test_failure_exit_code_and_redaction(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / 'result.json'
            with patch('sys.argv', ['check', '--only', 'llm', '--report', str(report)]), \
                 patch('bizcodeqa.check.load_env'), \
                 patch('bizcodeqa.check.llm_check', side_effect=ValueError('Invalid header test-secret')), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(main(), 1)
            self.assertNotIn('test-secret', report.read_text())
            self.assertNotIn('test-secret', output.getvalue())
            self.assertEqual(json.loads(report.read_text())['results'][0]['status'], 'FAIL')
