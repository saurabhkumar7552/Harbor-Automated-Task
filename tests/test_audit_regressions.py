"""Regressions found during the repository audit; no live providers or Docker."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from stem_factory import contracts
from stem_factory.adapters.base import Adapter, Response
from stem_factory.cli import main
from stem_factory.errors import FactoryError, RunHaltError
from stem_factory.factory import Factory
from stem_factory.generation import GenerationFactory
from stem_factory.images import versioned_image
from stem_factory.task_spec import relative_path, validate_proposal
from stem_factory.process import ProcessFailure
from stem_factory.reporting import atomic_json
from stem_factory.state import Journal, RunLock, State
from tests.fixtures import config, proposal
from tests.test_manifest_generation import configuration, models, bundle
from tests.test_workflow import agents, FakeValidator


class AuditRegressions(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows process query')
    def test_recover_active_windows_lock_never_calls_os_kill(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d)/'.lock'
            lock.write_text(str(os.getpid()))
            with patch('os.kill', side_effect=AssertionError('Do not signal Windows process')):
                with self.assertRaisesRegex(FactoryError, 'active process'):
                    with RunLock(d, recover=True):
                        pass
            self.assertTrue(lock.exists())

    def test_dead_and_invalid_lock_pids_are_handled_conservatively(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d)/'.lock'
            lock.write_text('987654321')
            with patch('stem_factory.state.check_process_alive', side_effect=ProcessLookupError):
                with RunLock(d, recover=True):
                    self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())
            lock.write_text('0')
            with self.assertRaisesRegex(FactoryError, 'Cannot establish stale lock'):
                with RunLock(d, recover=True):
                    pass

    def test_account_halt_survives_cached_replay_and_report_records_reason(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = config(d), agents()
            def blocked(*args):
                raise RunHaltError('Provider usage limit prevented a model call; run stopped immediately')
            a['author'].function = blocked
            for _ in range(2):
                with self.assertRaises(RunHaltError):
                    Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(len(a['author'].calls), 1)
            report = json.loads((c.output/'report.json').read_text(encoding='utf-8'))
            self.assertIn('usage limit', report['last_stop'])
            self.assertEqual(report['calls_reserved'], 1)

    def test_cached_identity_mismatch_halts_instead_of_spending_on_repair(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(d)
            c.output.mkdir()
            state, a = State(c), agents()
            journal = Journal(state, a)
            journal.call('author', 'original', contracts.PROPOSAL, 'request')
            with self.assertRaises(RunHaltError):
                journal.call('author', 'new policy', contracts.PROPOSAL, 'request')
            self.assertEqual(state.data['calls'], 1)

    def test_explicit_uncertain_retry_uses_fresh_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(d)
            c.output.mkdir()
            state, a, seen = State(c), agents(), []
            def invoke(prompt, schema, workspace, timeout=None):
                seen.append(workspace)
                self.assertFalse(list(workspace.iterdir()))
                if len(seen) == 1:
                    (workspace/'response-schema.json').write_text('{}')
                    raise KeyboardInterrupt()
                value = proposal()
                return Response(value, json.dumps(value), '')
            a['author'].invoke = invoke
            with self.assertRaises(KeyboardInterrupt):
                Journal(state, a).call('author', 'same policy', contracts.PROPOSAL, 'pending')
            Journal(state, a, retry_uncertain=True).call('author', 'same policy', contracts.PROPOSAL, 'pending')
            self.assertNotEqual(seen[0], seen[1])
            self.assertTrue((seen[0]/'response-schema.json').exists())
            self.assertEqual(state.data['calls'], 2)

    def test_manifest_files_preserve_exact_content_and_allow_empty_fixtures(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), models()
            original = a['author'].function
            def author(index, prompt, schema):
                if set(schema.get('properties', {})) == {'proposal', 'implementation'}:
                    result = original(index, prompt, schema)
                    result['implementation']['starter_files'] = [
                        {'path': 'input.txt', 'content': 'record  \n\n'}, {'path': 'empty.dat', 'content': ''}]
                    return result
                if schema is contracts.MANIFEST_IMPLEMENTATION:
                    b = bundle()
                    b['starter_files'] = [{'path': 'input.txt', 'content': 'record  \n\n'},
                                          {'path': 'empty.dat', 'content': ''}]
                    return b
                return original(index, prompt, schema)
            a['author'].function = author
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 1)
            package = Path(result['candidates'][0]['package_path'])
            self.assertEqual((package/'environment/starter/input.txt').read_bytes(), b'record  \n\n')
            self.assertEqual((package/'environment/starter/empty.dat').read_bytes(), b'')

    def test_registry_port_does_not_count_as_an_image_version(self):
        for image in ('registry:5000/team/image', 'python:latest', 'python:LATEST',
                      'python@sha256:abc', 'python:', ''):
            with self.subTest(image=image):
                self.assertFalse(versioned_image(image))
        self.assertTrue(versioned_image('registry:5000/team/image:1.2'))
        self.assertTrue(versioned_image('python@sha256:'+'a'*64))

    def test_manifest_rejects_windows_device_paths_and_overlapping_artifacts(self):
        from tests.test_manifest_generation import manifest
        from stem_factory.task_spec import request_settings
        for name in ('CON', 'nested/NUL.txt', 'com1.py', 'folder./file', '../outside'):
            with self.subTest(name=name), self.assertRaises(FactoryError):
                relative_path(name)
        p = manifest()
        p['output_manifest'] = [{'path': '/work/result', 'purpose': 'file'},
                                {'path': '/work/result/child', 'purpose': 'conflicting file'}]
        with self.assertRaisesRegex(FactoryError, 'overlap'):
            validate_proposal(p, {**request_settings({'difficulty': 'hard'}), 'domain': 'Physics'})

    def test_legacy_cli_accepts_null_candidate_ceiling(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(d, max_candidates=None)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--config', str(c.path), 'run', '--target', '5', '--dry-run']), 0)
            self.assertFalse(c.output.exists())

    def test_account_timeout_transcript_is_saved_before_halt(self):
        class Dummy(Adapter):
            def command(self, schema, workspace): return ['fake-cli']
            def parse(self, text): raise AssertionError('No parsing after a transport failure')
        with tempfile.TemporaryDirectory() as d:
            c = config(d)
            workspace = Path(d)/'workspace'
            workspace.mkdir()
            with patch('stem_factory.adapters.base.run', side_effect=ProcessFailure(
                    'timeout', 'authentication required', 'provider error')):
                with self.assertRaises(RunHaltError):
                    Dummy(c.roles['author']).invoke('prompt', {}, workspace)
            transcript = json.loads((workspace/'transport.json').read_text(encoding='utf-8'))
            self.assertIn('authentication required', transcript['stdout'])


if __name__ == '__main__':
    unittest.main()
