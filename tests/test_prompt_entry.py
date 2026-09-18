"""Exercise the complete prompt entry using the real selected Backchain packager."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills/workflow/scripts/workflow'
BACKCHAIN = Path(os.environ.get('WORKFLOW_TEST_BACKCHAIN_ROOT', ROOT.parent / 'backchain'))


@unittest.skipUnless((BACKCHAIN / 'harness/run-prompt.sh').is_file(), 'Backchain source checkout unavailable')
class PromptEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.run = self.root / 'run'
        self.request = 'Write a report.\nPreserve the exact original request.\n'
        prompt = self.root / 'request.txt'
        prompt.write_text(self.request)
        self.first = self.call('init', '--prompt-file', prompt, '--backchain-root', BACKCHAIN,
                               '--repo', self.repo, '--run-dir', self.run)

    def call(self, *args, success=True):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        payload = json.loads(result.stdout)
        if success:
            self.assertEqual(result.returncode, 0, payload)
        else:
            self.assertNotEqual(result.returncode, 0, payload)
        return payload

    def candidates(self, goal=None):
        plan = {'goal': self.request if goal is None else goal, 'initial_state': [],
                'steps': [{'id':'S1','statement':'A report has been written',
                           'produces':['report written'],'inputs':[],'origin':'seed'}],
                'parallel_groups': [], 'unresolved': [], 'goal_needs':['report written']}
        bindings = {'S1': {'kind':'command', 'argv':[sys.executable, '-c',
                    "from pathlib import Path; Path('report.txt').write_text('done')"],
                    'outputs':['report.txt']}}
        plan_path, bindings_path = self.root / 'plan.json', self.root / 'bindings.json'
        plan_path.write_text(json.dumps(plan))
        bindings_path.write_text(json.dumps(bindings))
        return plan_path, bindings_path

    def test_prompt_to_real_backchain_package_to_verified_execution(self):
        self.assertEqual(self.first['original_goal'], self.request)
        cold = self.call('next', '--run-dir', self.run)
        self.assertEqual(cold['action_id'], self.first['action_id'])
        plan, bindings = self.candidates()
        accepted = self.call('accept-plan', '--run-dir', self.run, '--action', cold['action_id'],
                             '--plan', plan, '--bindings', bindings)
        self.assertEqual(accepted['kind'], 'command')
        self.assertEqual(accepted['step_id'], 'S1')
        self.assertEqual(accepted['original_goal'], self.request)
        terminal = self.call('run', '--run-dir', self.run)
        self.assertEqual(terminal['status'], 'complete')
        self.assertEqual((self.repo/'report.txt').read_text(), 'done')
        self.assertEqual(self.call('next', '--run-dir', self.run)['status'], 'complete')

    def test_changed_goal_does_not_replace_the_planning_action(self):
        plan, bindings = self.candidates(goal='A different request')
        self.call('accept-plan', '--run-dir', self.run, '--action', self.first['action_id'],
                  '--plan', plan, '--bindings', bindings, success=False)
        current = self.call('next', '--run-dir', self.run)
        self.assertEqual(current['action_id'], self.first['action_id'])
        self.assertEqual(current['original_goal'], self.request)
        self.assertFalse((self.repo/'report.txt').exists())

    def test_prompt_entry_preserves_crlf_and_unicode_bytes(self):
        exact = 'Résumé\r\nKeep these line endings.\r\n'
        prompt = self.root / 'windows-request.txt'
        prompt.write_bytes(exact.encode('utf-8'))
        run = self.root / 'windows-run'
        packet = self.call('init', '--prompt-file', prompt, '--backchain-root', BACKCHAIN,
                           '--repo', self.repo, '--run-dir', run)
        self.assertEqual(packet['original_goal'].encode('utf-8'), prompt.read_bytes())
        self.assertEqual(self.call('next', '--run-dir', run)['original_goal'], exact)


if __name__ == '__main__':
    unittest.main()
