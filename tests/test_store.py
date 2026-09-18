"""Exercise the extracted storage boundary, including interrupted transactions."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'skills/workflow/scripts'))
import store


class StoreTests(unittest.TestCase):
    def test_markdown_round_trip_and_duplicate_key_rejection(self):
        value = {'goal': 'Résumé \u2192 result', 'steps': ['a', 'b']}
        self.assertEqual(store.loads(store.dumps(value)), value)
        with self.assertRaises(store.StorageError):
            store.loads('```workflow-state\n{"a":1,"a":2}\n```\n')

    def test_partial_transaction_recovers_state_and_receipt_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            store.write_record(root / 'state.md', {'step': 'a'})
            def crash(_point, index):
                if index == 1:
                    raise RuntimeError('simulated interrupted writer')
            with self.assertRaises(RuntimeError):
                store.transaction(root, {
                    'receipts/a.md': store.dumps({'step': 'a', 'status': 'succeeded'}),
                    'state.md': store.dumps({'step': 'b'}),
                }, fault=crash)
            self.assertTrue((root / 'transaction.md').is_file())
            self.assertTrue(store.recover(root))
            self.assertEqual(store.read_record(root / 'state.md'), {'step': 'b'})
            self.assertEqual(store.read_record(root / 'receipts/a.md')['status'], 'succeeded')
            self.assertFalse(store.recover(root))

    def test_transaction_rejects_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / 'run'
            root.mkdir()
            target = pathlib.Path(tmp) / 'outside'
            target.write_text('original')
            (root / 'link').symlink_to(target)
            for name in ('../outside', 'link'):
                with self.subTest(name=name), self.assertRaises(store.StorageError):
                    store.transaction(root, {name: 'replacement'})
            self.assertEqual(target.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
