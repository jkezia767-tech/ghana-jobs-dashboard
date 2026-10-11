"""Offline regression tests use copies of supplied data and mocked network failures."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import cloud_run as cloud
import refresh_jobs as jobs

ROOT = Path(__file__).resolve().parents[1]

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'data', self.root / 'data')
        jobs.configure(self.root)
        self.before = jobs.load_records()

    def tearDown(self):
        self.temp.cleanup()

    def test_real_data_offline_build(self):
        with patch.object(jobs.session, 'get', side_effect=AssertionError('Unexpected network')):
            cloud.publish(self.root, cloud.fallback_report(None, 'Not run on GitHub yet', 'Imported laptop data'), 0)
        page = (self.root / '_site/index.html').read_text()
        self.assertIn('Not run on GitHub yet', page)
        self.assertIn('version.json', page)
        # Embedded JSON must contain exactly the supplied records.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page, 'html.parser')
        payload = soup.find('script', {'type': 'application/json'})
        self.assertEqual(len(json.loads(payload.string)), len(self.before))
        self.assertEqual((self.root / 'data/jobs_current.csv').read_bytes(),
                         (ROOT / 'data/jobs_current.csv').read_bytes())

    def test_total_source_failure_retains_all_records(self):
        with patch.object(jobs, 'read_rules', side_effect=ValueError('Simulated offline failure')):
            with contextlib.redirect_stdout(io.StringIO()):
                code = jobs.refresh()
        self.assertEqual(code, 2)
        after = jobs.load_records()
        self.assertEqual(after.to_json(), self.before.to_json())
        report = json.loads((self.root / 'logs/refresh_latest.json').read_text())
        self.assertTrue(all(r['result'] == 'Failed' for r in report['sources']))
        cloud.publish(self.root, report, code)
        self.assertIn('Failed', (self.root / '_site/index.html').read_text())

    def test_timeout_publishes_interruption_not_fake_success(self):
        import subprocess
        with patch('sys.argv', ['cloud_run.py', '--collect', '--project-dir', str(self.root)]), \
             patch.object(cloud.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test', 1)):
            self.assertEqual(cloud.main(), 0)
        report = json.loads((self.root / 'logs/refresh_latest.json').read_text())
        self.assertTrue(all('Interrupted' in r['result'] for r in report['sources']))
        self.assertEqual(jobs.load_records().to_json(), self.before.to_json())

if __name__ == '__main__':
    unittest.main()
