"""Planning transaction/retry contracts; structural adapter is a controlled double.

Real selected-Backchain packaging is exercised separately by test_prompt_entry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from spec_fixtures import specified

ROOT = Path(__file__).resolve().parents[1]
BACKCHAIN = Path(os.environ.get('WORKFLOW_TEST_BACKCHAIN_ROOT', ROOT.parent / 'backchain'))
sys.path.insert(0, str(ROOT / 'skills/workflow/scripts'))
import store
from workflow_core import WorkflowKernel, WorkflowError


class PlanningCallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / 'workspace'
        self.repo.mkdir()
        self.run = self.base / 'run'
        self.kernel = WorkflowKernel(ROOT / 'skills/workflow/scripts/workflow')
        self.definition = specified({'version': 1, 'name': 'callback', 'goal': 'Make one checked report.',
            'steps': [{'id': 'report', 'kind': 'command', 'needs': [],
                       'argv': [sys.executable, '-c', "from pathlib import Path; Path('report.txt').write_text('checked')"],
                       'outputs': ['report.txt'],
                       'verify': [[sys.executable, '-c', "from pathlib import Path; assert Path('report.txt').read_text() == 'checked'"]]}]})
        self.spec_file = self.base / 'spec.json'
        self.spec_file.write_text(json.dumps(self.definition['specification']))
        self.plan = self.base / 'plan.json'
        self.plan.write_text(json.dumps({'goal': self.definition['goal']}))
        self.bindings = self.base / 'bindings.json'
        self.bindings.write_text(json.dumps({'report': self.definition['steps'][0]}))
        self.initial = self.kernel.init_spec(spec_file=self.spec_file, backchain_root=self.base,
            run_dir=self.run, repo=self.repo)
        self.calls = []
        self.fail_next = False

    def compile(self, root, plan, bindings, staging):
        self.calls.append(staging)
        staging.mkdir(parents=True)
        (staging / 'attempt.txt').write_text('retained structural packaging attempt')
        if self.fail_next:
            self.fail_next = False
            raise ValueError('controlled packaging failure')
        # The real adapter produces v1 projection; the new-run boundary promotes it.
        result = {key: value for key, value in self.definition.items() if key != 'specification'}
        result['version'] = 1
        return result, {'controlled_adapter': True}

    def accept(self):
        adapter = type('Adapter', (), {'compile_backchain': staticmethod(self.compile)})()
        with patch.object(self.kernel, '_adapters', return_value=adapter):
            return self.kernel.accept_plan(run_dir=self.run, action_id=self.initial['action_id'],
                plan_file=self.plan, bindings_file=self.bindings)

    def test_response_loss_replays_without_packaging_or_execution_and_conflicts_reject(self):
        accepted = self.accept()
        self.assertEqual(self.accept()['action_id'], accepted['action_id'])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.repo / 'report.txt').exists())
        self.assertEqual(self.kernel.run(run_dir=self.run)['status'], 'complete')
        self.assertEqual(self.accept()['status'], 'complete')
        self.assertEqual(len(self.calls), 1)
        receipt = next((self.run / 'receipts').glob('*.md'))
        self.assertEqual(store.read_record(receipt)['specification_sha256'], accepted['specification_sha256'])
        self.bindings.write_text(self.bindings.read_text() + '\n')
        with self.assertRaisesRegex(WorkflowError, 'conflicts'):
            self.accept()

    def test_failed_packaging_keeps_attempt_and_allows_corrected_callback(self):
        self.fail_next = True
        with self.assertRaisesRegex(WorkflowError, 'controlled packaging failure'):
            self.accept()
        cold = self.kernel.next(run_dir=self.run)
        self.assertEqual(cold['action_id'], self.initial['action_id'])
        self.assertEqual(cold['kind'], 'planning')
        self.assertEqual(self.accept()['kind'], 'command')
        self.assertEqual(len(set(self.calls)), 2)
        self.assertTrue(all((path / 'attempt.txt').is_file() for path in self.calls))

    def test_plan_acceptance_recovers_each_transaction_cut_without_recompiling(self):
        real_transaction = store.transaction
        for cut in range(1, 5):
            with self.subTest(cut=cut):
                if cut > 1:
                    self.run = self.base / f'run-{cut}'
                    self.initial = self.kernel.init_spec(spec_file=self.spec_file, backchain_root=self.base,
                        run_dir=self.run, repo=self.repo)
                def interrupted(directory, writes):
                    def fault(event, index):
                        if event == 'after-target' and index == cut:
                            raise RuntimeError('controlled crash')
                    return real_transaction(directory, writes, fault=fault)
                before = len(self.calls)
                with patch.object(store, 'transaction', side_effect=interrupted):
                    with self.assertRaisesRegex(RuntimeError, 'controlled crash'):
                        self.accept()
                recovered = self.kernel.next(run_dir=self.run)
                self.assertEqual(recovered['kind'], 'command')
                self.assertEqual(self.accept()['action_id'], recovered['action_id'])
                self.assertEqual(len(self.calls), before + 1)
                self.assertFalse((self.repo / 'report.txt').exists())

    @unittest.skipUnless((BACKCHAIN / 'harness/run-prompt.sh').is_file(), 'Backchain source checkout unavailable')
    def test_spec_file_uses_real_selected_backchain_before_execution(self):
        self.run = self.base / 'real-run'
        planning = self.kernel.init_spec(spec_file=self.spec_file, backchain_root=BACKCHAIN,
            run_dir=self.run, repo=self.repo)
        self.plan.write_text(json.dumps({
            'goal': self.definition['goal'], 'initial_state': [],
            'steps': [{'id': 'report', 'statement': 'The checked report exists.',
                       'produces': ['checked report exists'], 'inputs': [], 'origin': 'seed'}],
            'parallel_groups': [], 'unresolved': [], 'goal_needs': ['checked report exists'],
        }))
        binding = {key: value for key, value in self.definition['steps'][0].items()
                   if key not in {'id', 'needs'}}
        self.bindings.write_text(json.dumps({'report': binding}))
        packet = self.kernel.accept_plan(run_dir=self.run, action_id=planning['action_id'],
            plan_file=self.plan, bindings_file=self.bindings)
        self.assertEqual(packet['kind'], 'command')
        self.assertEqual(packet['original_goal'], self.definition['goal'])
        self.assertFalse((self.repo / 'report.txt').exists())
        self.assertEqual(self.kernel.run(run_dir=self.run)['status'], 'complete')
        self.assertEqual((self.repo / 'report.txt').read_text(), 'checked')

    def test_packaging_rejects_aliased_staging_parent_before_adapter_effects(self):
        external = self.base / 'external'
        external.mkdir()
        (self.run / 'planning').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(WorkflowError, 'symlink'):
            self.accept()
        self.assertEqual(self.calls, [])
        self.assertEqual(list(external.iterdir()), [])
        self.assertFalse((self.repo / 'report.txt').exists())

    def test_frozen_plan_artifact_tamper_blocks_execution(self):
        self.accept()
        state = store.read_record(self.run / 'state.md')
        (self.run / state['planner']['bindings_path']).write_text('{}')
        with self.assertRaisesRegex(WorkflowError, 'artifact changed'):
            self.kernel.run(run_dir=self.run)
        self.assertFalse((self.repo / 'report.txt').exists())


if __name__ == '__main__':
    unittest.main()
