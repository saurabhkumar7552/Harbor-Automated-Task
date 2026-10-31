"""Offline control-plane tests: fake adapters, no generated-code execution."""
import tempfile
import unittest
from unittest.mock import patch

from stem_factory.factory import Factory
from stem_factory.state import State
from tests.fixtures import config, implementation, proposal
from tests.test_workflow import FakeAdapter, FakeValidator, agents


class PreAuditStructure(unittest.TestCase):
    def test_bad_syntax_skips_paid_audit_and_preserves_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory, max_candidates=1, max_revisions=0)
            a = agents()
            bundle = implementation()
            bundle['tests_python'] = 'def broken('
            a['implementer'] = FakeAdapter(lambda *args: bundle)
            with patch('subprocess.Popen', side_effect=AssertionError('no processes')):
                result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(len(a['reviewer'].calls), 1)  # proposal review only
            feedback = State(c).data['candidates'][0]['final_findings']
            self.assertEqual(feedback['structural_validation']['code'], 'IMPLEMENTATION_STRUCTURE')

    def test_valid_bundle_keeps_independent_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory), agents()
            with patch('subprocess.Popen', side_effect=AssertionError('no processes')):
                result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(len(a['reviewer'].calls), 2)
            self.assertEqual(result['calls_reserved'], 4)

    def test_resumed_audit_also_checks_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory, max_candidates=1, max_revisions=0)
            c.output.mkdir()
            a = agents()
            bundle = implementation()
            bundle['mutants'][1]['code'] = bundle['mutants'][0]['code']
            state = State(c)
            state.data['candidates'] = [{'index': 1, 'revision': 0, 'status': 'audit',
                                         'proposal': proposal(), 'implementation': bundle}]
            state.save()
            with patch('subprocess.Popen', side_effect=AssertionError('no processes')):
                result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(a['reviewer'].calls, [])


if __name__ == '__main__':
    unittest.main()
