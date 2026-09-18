"""Process-death and malformed-record tests at durable transaction boundaries.

These tests kill only disposable child processes at deterministic store cuts.
They establish local process-crash recovery, not physical power-loss durability.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

from spec_fixtures import specified

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/workflow/scripts'
sys.path.insert(0, str(SCRIPTS))
import store

CLI = Path(os.environ.get('WEAVE_TEST_CLI', SCRIPTS / 'workflow'))


class RecoveryMatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='weave-crash-matrix-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / 'workspace'
        self.workspace.mkdir()
        self.run = self.base / 'run'

    def call(self, *args, ok=True):
        p = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                           capture_output=True, text=True, timeout=20)
        value = json.loads(p.stdout)
        if ok:
            self.assertEqual(p.returncode, 0, value)
        else:
            self.assertNotEqual(p.returncode, 0, value)
        return value

    def init_agents(self):
        definition = specified(
            {
                'version': 1,
                'name': 'crash-matrix',
                'goal': 'Accept both independent leaves',
                'steps': [
                    {
                        'id': x,
                        'kind': 'agent',
                        'needs': [],
                        'prompt': 'Write only ' + x + '.txt',
                        'outputs': [x + '.txt'],
                    }
                    for x in ['A', 'B']
                ],
            }
        )
        path = self.base / 'workflow.json'
        path.write_text(json.dumps(definition))
        self.call('init', '--workflow', path, '--run-dir', self.run, '--repo', self.workspace,
                  '--max-active', 2, '--shared-workspace-disjoint')

    def crash_store(self, root, cut, recovery=False):
        code = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1]); import store
root=Path(sys.argv[2]); cut=int(sys.argv[3]); recovery=sys.argv[4]=='1'
if recovery:
    original=store._write_target
    count=[0]
    def write(*args):
        original(*args); count[0]+=1
        if count[0]==cut: os._exit(73)
    store._write_target=write
    store.recover(root)
else:
    if cut==0:
        store._roll_forward=lambda *a,**k: os._exit(73)
    def fault(point,index):
        if index==cut: os._exit(73)
    store.transaction(root, {'a.md':store.dumps({'value':'new-a'}),
                            'nested/b.md':store.dumps({'value':'new-b'}),
                            'state.md':store.dumps({'generation':2})},
                      ['old-one.md','old-two.md'], fault=fault)
'''
        p = subprocess.run([sys.executable, '-c', code, str(SCRIPTS), str(root), str(cut),
                            '1' if recovery else '0'], capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 73, p.stderr)

    def storage_fixture(self, root):
        root.mkdir()
        store.write_record(root/'state.md', {'generation': 1})
        (root/'old-one.md').write_text('old-one')
        (root/'old-two.md').write_text('old-two')

    def assert_recovered(self, root):
        self.assertTrue(store.recover(root))
        self.assertEqual(store.read_record(root/'state.md'), {'generation': 2})
        self.assertEqual(store.read_record(root/'a.md'), {'value': 'new-a'})
        self.assertEqual(store.read_record(root/'nested/b.md'), {'value': 'new-b'})
        self.assertFalse((root/'old-one.md').exists())
        self.assertFalse((root/'old-two.md').exists())
        self.assertFalse(store.recover(root))

    def test_process_death_after_journal_and_every_write_delete_cut(self):
        for cut in range(6):
            with self.subTest(cut=cut):
                root = self.base / f'cut-{cut}'
                self.storage_fixture(root)
                self.crash_store(root, cut)
                self.assertTrue((root/'transaction.md').exists())
                self.assert_recovered(root)

    def test_recovery_can_itself_crash_and_resume_without_losing_a_target(self):
        root = self.base / 'double-crash'
        self.storage_fixture(root)
        self.crash_store(root, 0)
        self.crash_store(root, 2, recovery=True)
        self.assert_recovered(root)

    def test_malformed_pending_journal_is_rejected_before_any_target_is_written(self):
        for bad in ['duplicate', 'escape', 'symlink', 'wrong-version']:
            with self.subTest(bad=bad):
                root = self.base / bad
                self.storage_fixture(root)
                self.crash_store(root, 0)
                journal = store.read_record(root/'transaction.md')
                if bad == 'duplicate':
                    journal['writes'].append(dict(journal['writes'][0]))
                elif bad == 'escape':
                    journal['writes'].append({'path': '../outside', 'text': 'bad'})
                elif bad == 'symlink':
                    outside = self.base / 'outside'
                    outside.write_text('preserved')
                    (root/'alias').symlink_to(outside)
                    journal['writes'].append({'path': 'alias', 'text': 'bad'})
                else:
                    journal['version'] = 999
                store.write_record(root/'transaction.md', journal)
                with self.assertRaises(store.StorageError):
                    store.recover(root)
                self.assertEqual(store.read_record(root/'state.md'), {'generation': 1})
                self.assertFalse((root/'a.md').exists())
                self.assertTrue((root/'old-one.md').exists())
                if bad == 'symlink':
                    self.assertEqual(outside.read_text(), 'preserved')

    def crash_kernel_transition(self, cut, operation, action=None, result=None):
        code = r'''
import os, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import store
from workflow_core import WorkflowKernel
kernel=WorkflowKernel(Path(sys.argv[2])); run=Path(sys.argv[3]); cut=int(sys.argv[4]); op=sys.argv[5]
original=store.transaction
fired=[False]
def transaction(root,writes,deletes=None,**kwargs):
    target=op=='claim' or any(p.startswith('receipts/') for p in writes)
    if target and not fired[0]:
        fired[0]=True
        def fault(point,index):
            if index==cut: os._exit(74)
        kwargs['fault']=fault
    return original(root,writes,deletes,**kwargs)
store.transaction=transaction
if op=='claim': kernel.claim_ready(run_dir=run,limit=2,request_id='recover-the-same-claim')
else: kernel.complete(run_dir=run,action_id=sys.argv[6],result_file=Path(sys.argv[7]))
'''
        p = subprocess.run([sys.executable, '-c', code, str(CLI.parent), str(CLI), str(self.run),
                            str(cut), operation, action or '', str(result or '')],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 74, p.stderr)

    def test_claim_crash_cuts_preserve_one_identity_per_step_and_request_replay(self):
        for cut in [1, 2]:
            with self.subTest(cut=cut):
                self.run = self.base / f'claim-run-{cut}'
                self.init_agents()
                self.crash_kernel_transition(cut, 'claim')
                cold = self.call('next', '--run-dir', self.run)
                self.assertEqual({p['step_id'] for p in cold['active_packets']}, {'A','B'})
                ids = {p['action_id'] for p in cold['active_packets']}
                replay = self.call('claim-ready', '--run-dir', self.run, '--limit', 2,
                                   '--request-id', 'recover-the-same-claim')
                self.assertTrue(replay['claim_replayed'])
                self.assertEqual(set(replay['claimed_action_ids']), ids)
                self.assertEqual(len(store.read_record(self.run/'state.md')['attempts']), 2)

    def test_acceptance_crash_cuts_recover_receipt_without_reexecuting_callback(self):
        for cut in [1, 2, 3]:
            with self.subTest(cut=cut):
                self.run = self.base / f'complete-run-{cut}'
                self.init_agents()
                claim = self.call('claim-ready', '--run-dir', self.run, '--limit', 2,
                                  '--request-id', 'first')
                a, b = sorted(claim['claimed_packets'], key=lambda p:p['step_id'])
                self.call('prepare-dispatch', '--run-dir', self.run, '--action', a['action_id'])
                self.call('dispatch', '--run-dir', self.run, '--action', a['action_id'], '--handle', 'simulated-A')
                (self.workspace/'A.txt').write_text('A-'+str(cut))
                result = self.base / f'result-{cut}.json'
                result.write_text(json.dumps({'status':'succeeded','summary':'deterministic fixture'}))
                self.crash_kernel_transition(cut, 'complete', a['action_id'], result)
                cold = self.call('next', '--run-dir', self.run)
                self.assertNotEqual(cold['status'], 'complete')
                self.assertEqual([p['action_id'] for p in cold['active_packets']], [b['action_id']])
                state = store.read_record(self.run/'state.md')
                self.assertEqual(set(state['completed']), {'A'})
                receipt = state['completed']['A']['receipt_path']
                self.assertTrue((self.run/receipt).is_file())
                before = (self.workspace/'A.txt').stat().st_mtime_ns
                replay = self.call('complete', '--run-dir', self.run, '--action', a['action_id'], '--result', result)
                self.assertEqual([p['action_id'] for p in replay['active_packets']], [b['action_id']])
                self.assertEqual((self.workspace/'A.txt').stat().st_mtime_ns, before)

    def test_resealed_malformed_frontier_state_still_fails_semantic_validation(self):
        self.init_agents()
        self.call('claim-ready', '--run-dir', self.run, '--limit', 2, '--request-id', 'first')
        valid = store.read_record(self.run/'state.md')
        for mutation in ['duplicate-action', 'duplicate-step', 'capacity', 'lease', 'complete-active']:
            with self.subTest(mutation=mutation):
                state = json.loads(json.dumps(valid))
                if mutation == 'duplicate-action':
                    state['active_actions'][1]['id'] = state['active_actions'][0]['id']
                elif mutation == 'duplicate-step':
                    state['active_actions'][1]['step_id'] = state['active_actions'][0]['step_id']
                elif mutation == 'capacity':
                    state['active_actions'].append(dict(state['active_actions'][0]))
                elif mutation == 'lease':
                    state['active_actions'][0]['workspace_lease']['paths'] = ['unowned.txt']
                else:
                    state['status'] = 'complete'
                unsealed = {k:v for k,v in state.items() if k!='state_sha256'}
                state['state_sha256'] = hashlib.sha256(json.dumps(unsealed,ensure_ascii=False,allow_nan=False,
                                                                  sort_keys=True,separators=(',',':')).encode()).hexdigest()
                store.write_record(self.run/'state.md', state)
                error = self.call('next', '--run-dir', self.run, ok=False)
                self.assertNotIn('hash does not match', error['error'], error)
        store.write_record(self.run/'state.md', valid)
        self.assertEqual(self.call('next', '--run-dir', self.run)['active_count'], 2)


if __name__ == '__main__':
    unittest.main()
