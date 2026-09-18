"""Characterization of a documented limitation, not a passing isolation claim."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from ownership_probe import probe


class OwnershipBoundaryTests(unittest.TestCase):
    def test_receipts_cannot_prove_writer_identity_in_a_cooperative_shared_workspace(self):
        observed=probe()
        self.assertIs(observed['assumption_supported'],False)
        self.assertFalse(observed['observation']['b_worker_wrote_output'])
        self.assertEqual(observed['observation']['b_contents'],'written-by-A-verifier')
        self.assertEqual(observed['observation']['workflow_status'],'complete')


if __name__=='__main__':unittest.main()
