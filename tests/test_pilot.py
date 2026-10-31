import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stem_factory import contracts
from stem_factory.cli import main
from stem_factory.config import load
from stem_factory.errors import ConfigError, FactoryError
from stem_factory.factory import Factory, dry_plan
from stem_factory.state import Journal, State
from tests.fixtures import config
from tests.test_workflow import agents, FakeValidator


def execution(config_value, **controls):
    data = json.loads(config_value.path.read_text())
    data['execution'] = controls
    config_value.path.write_text(json.dumps(data))
    return load(config_value.path)


class Pilot(unittest.TestCase):
    def test_execution_controls_reject_non_booleans_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            for controls in ({'live_enabled': 'false'}, {'live_enabled': 0},
                             {'stop_on_validation_failure': None}, {'allow_paid': True}):
                with self.subTest(controls=controls), self.assertRaises(ConfigError):
                    execution(c, **controls)

    def test_disabled_run_stops_before_probes_calls_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            c = execution(config(directory), live_enabled=False)
            a, validator = agents(), FakeValidator()
            with patch.object(a['author'], 'preflight') as probe, \
                    patch.object(validator, 'doctor') as doctor:
                with self.assertRaisesRegex(ConfigError, 'Live execution is disabled'):
                    Factory(c, adapters=a, validator=validator).run(1)
                probe.assert_not_called()
                doctor.assert_not_called()
            self.assertFalse(c.output.exists())
            self.assertTrue(all(not adapter.calls for adapter in a.values()))

    def test_disabled_journal_cannot_reserve_or_invoke(self):
        with tempfile.TemporaryDirectory() as directory:
            c = execution(config(directory), live_enabled=False)
            state, a = State(c), agents()
            with self.assertRaisesRegex(ConfigError, 'Live execution is disabled'):
                Journal(state, a).call('author', 'spec', contracts.PROPOSAL, 'request')
            self.assertEqual(state.data['calls'], 0)
            self.assertFalse(c.output.exists())
            self.assertEqual(a['author'].calls, [])

    def test_validation_failure_halts_with_retries_and_replacements_available(self):
        with tempfile.TemporaryDirectory() as directory:
            c = execution(config(directory, max_candidates=3, max_revisions=2),
                          stop_on_validation_failure=True)
            a, validator = agents(), FakeValidator(False)
            result = Factory(c, adapters=a, validator=validator).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(result['calls_reserved'], 4)
            self.assertEqual(len(result['candidates']), 1)
            self.assertEqual(result['candidates'][0]['status'], 'rejected')
            self.assertTrue(result['halted'])
            self.assertEqual(validator.calls, 1)
            self.assertTrue((c.output / 'validation/candidate-001-revision-00.json').is_file())
            self.assertTrue((c.output / 'failed/candidate-001-revision-00/solution/solve.sh').is_file())
            self.assertEqual(list((c.output / 'accepted').iterdir()), [])
            counts = [len(adapter.calls) for adapter in a.values()]
            with self.assertRaisesRegex(FactoryError, 'Run halted'):
                Factory(c, adapters=a, validator=validator).run(1)
            self.assertEqual([len(adapter.calls) for adapter in a.values()], counts)
            self.assertEqual(validator.calls, 1)
            self.assertTrue(json.loads((c.output / 'report.json').read_text())['halted'])

    def test_static_validation_failure_also_halts(self):
        with tempfile.TemporaryDirectory() as directory:
            c = execution(config(directory, max_revisions=2), stop_on_validation_failure=True)
            a, validator = agents(), FakeValidator()
            with patch('stem_factory.factory.static_check', side_effect=FactoryError('static failure')):
                result = Factory(c, adapters=a, validator=validator).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(result['calls_reserved'], 4)
            self.assertTrue(result['halted'])
            self.assertEqual(validator.calls, 0)
            self.assertIn('static failure', (c.output / 'failed/candidate-001-revision-00.json').read_text())

    def test_validation_operating_system_failure_is_preserved_and_halts(self):
        with tempfile.TemporaryDirectory() as directory:
            c = execution(config(directory), stop_on_validation_failure=True)
            validator = FakeValidator()
            with patch.object(validator, 'validate', side_effect=OSError('fixture access failure')):
                result = Factory(c, adapters=agents(), validator=validator).run(1)
            self.assertTrue(result['halted'])
            self.assertEqual(result['accepted'], 0)
            self.assertIn('fixture access failure', (c.output / 'failed/candidate-001-revision-00.json').read_text())

    def test_shipped_pilot_schema_boundaries_and_safe_cli_dry_run(self):
        data = json.loads((Path(__file__).resolve().parents[1] / 'config/pilot.models.yaml').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tasks').mkdir()
            data.update(repository=str(root), existing_tasks=str(root / 'tasks'), output=str(root / 'pilot'))
            path = root / 'pilot.models.yaml'
            path.write_text(json.dumps(data))
            c = load(path)
            self.assertEqual(c.limits['max_candidates'], 1)
            self.assertEqual(c.limits['max_revisions'], 3)
            self.assertFalse(c.execution['live_enabled'])
            self.assertTrue(c.execution['stop_on_validation_failure'])
            self.assertEqual(set(c.roles), {'author', 'reviewer', 'implementer'})
            self.assertNotEqual(c.roles['author'].model, c.roles['reviewer'].model)
            with patch('stem_factory.process.run', side_effect=AssertionError('unexpected subprocess')):
                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    code = main(['--config', str(path), 'run', '--target', '1', '--dry-run'])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(capture.getvalue()), dry_plan(c, 1))
            self.assertFalse(c.output.exists())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--config', str(path), 'run', '--target', '2', '--dry-run']), 2)
