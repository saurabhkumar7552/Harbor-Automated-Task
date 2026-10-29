from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from stem_factory.errors import ContractError, FactoryError
from stem_factory.packaging import create_package, static_check, check_implementation
from stem_factory.process import ProcessResult, run
from stem_factory.reporting import no_secrets, redact, tree_hash
from stem_factory.validation import Validator
from tests.fixtures import config, proposal, implementation, review, audit


def evidence():
    return {'proposal': proposal(), 'implementation': implementation(), 'review': review(), 'audit': audit()}


class SafetyAndValidation(unittest.TestCase):
    def test_package_hidden_context_and_exact_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            path = Path(directory) / 'stage'
            create_package(path, proposal(), implementation(), c.validation['image'], evidence())
            result = static_check(path, c.validation['image'])
            self.assertEqual(result['static'], 'PASS')
            self.assertNotIn('COPY', (path / 'environment/Dockerfile').read_text())
            self.assertEqual(set(p.name for p in (path / 'environment').iterdir()), {'Dockerfile', '.dockerignore'})
            self.assertNotIn(implementation()['reference_python'], (path / 'instruction.md').read_text())
            (path / 'environment/answer.py').write_text('answer')
            with self.assertRaises(FactoryError):
                static_check(path, c.validation['image'])

    def test_package_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            path = Path(directory) / 'stage'
            create_package(path, proposal(), implementation(), c.validation['image'], evidence())
            (path / 'solution/solve.sh').write_text('#!/bin/bash\nmalicious-command\n')
            with self.assertRaises(FactoryError):
                static_check(path, c.validation['image'])

    def test_bad_mutants_and_no_tests_rejected(self):
        for mutation in ('syntax', 'duplicate', 'reference', 'few_tests'):
            bundle = implementation()
            if mutation == 'syntax':
                bundle['mutants'][0]['code'] = 'def broken('
            elif mutation == 'duplicate':
                bundle['mutants'][0]['code'] = bundle['mutants'][1]['code']
            elif mutation == 'reference':
                bundle['mutants'][0]['code'] = bundle['reference_python']
            else:
                bundle['tests_python'] = 'import unittest\n'
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                check_implementation(bundle)

    def test_container_commands_are_fixed_offline_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                return ProcessResult('', '', 0, .01)
            with patch('stem_factory.validation.run', side_effect=transport):
                Validator(c).container(Path(directory) / 'package', Path(directory) / 'work', 'sha256:' + 'a'*64)
            argv = calls[0]
            self.assertEqual(argv[argv.index('--network') + 1], 'none')
            self.assertIn('--read-only', argv)
            self.assertIn('--cap-drop', argv)
            self.assertIn('--pids-limit', argv)
            self.assertIn('65534:65534', argv)
            self.assertEqual(argv[argv.index('--pull') + 1], 'never')
            self.assertNotIn('--privileged', argv)
            self.assertNotIn('/var/run/docker.sock', ' '.join(argv))
            self.assertNotIn('API_KEY', ' '.join(argv))
            self.assertEqual(calls[-1][1:3], ['rm', '--force'])

    def test_container_cleanup_after_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                if argv[1] == 'run':
                    raise FactoryError('timeout')
                return ProcessResult('', '', 0, .01)
            with patch('stem_factory.validation.run', side_effect=transport), self.assertRaises(FactoryError):
                Validator(config(directory)).container(Path(directory), Path(directory), 'image')
            self.assertEqual(calls[-1][1:3], ['rm', '--force'])

    def test_offline_build_command_and_image_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                return ProcessResult('sha256:' + 'a'*64 if argv[1] == 'image' else 'built', '', 0, .01)
            with patch('stem_factory.validation.run', side_effect=transport):
                result = Validator(config(directory)).build(Path(directory), 'tests', 'fixture-tag')
            self.assertEqual(result['image_id'], 'sha256:' + 'a'*64)
            self.assertIn('--pull=false', calls[0])
            self.assertEqual(calls[0][calls[0].index('--network') + 1], 'none')
            self.assertEqual(calls[0][-1], str(Path(directory) / 'tests'))

    def test_full_validation_order_and_mutation_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            stage = Path(directory) / 'stage'
            create_package(stage, proposal(), implementation(), c.validation['image'], evidence())
            validator = Validator(c)
            calls = []
            def container(package, work, image_id, reference=False, baked_tests=False):
                calls.append((reference, baked_tests))
                if reference:
                    (work / 'task.py').write_text(implementation()['reference_python'])
                    return ProcessResult('', '', 0, .01)
                if (work / 'task.py').exists() and (work / 'task.py').read_text() == implementation()['reference_python']:
                    return ProcessResult('', 'Ran 8 tests\nOK\n', 0, .01)
                return ProcessResult('', 'Ran 8 tests\nFAILED (failures=3)\n', 1, .01)
            with patch.object(validator, 'schema', return_value={'schema': 'PASS'}), \
                 patch.object(validator, 'image_identity', return_value='image-id'), \
                 patch.object(validator, 'build', return_value={'image_id': 'built-image'}), \
                 patch.object(validator, 'container', side_effect=container), \
                 patch('stem_factory.validation.run', return_value=ProcessResult('', '', 0, .01)):
                result = validator.validate(stage, Path(directory) / 'validation.json')
            self.assertTrue(result['passed'])
            self.assertEqual(len(result['checks']), 6)
            self.assertEqual(sum(reference for reference, _ in calls), 2)
            self.assertTrue(all(baked for reference, baked in calls if not reference))

    def test_mutant_must_fail_assertions_not_import(self):
        report = {'checks': []}
        Validator.record(report, 'mutant', ProcessResult('', 'Ran 8 tests\nFAILED (failures=3)\n', 1, .01), False, True)
        for output, code in (('FAILED (errors=1)\n', 1), ('FAILED (failures=1, errors=1)\n', 1),
                             ('permission denied', 125), ('Ran 8 tests\nOK\n', 0)):
            with self.assertRaises(FactoryError):
                Validator.record(report, 'mutant', ProcessResult('', output, code, .01), False, True)

    def test_reference_requires_observed_test_count(self):
        for output in ('OK\n', 'Ran 0 tests\nOK\n', 'Ran 7 tests\nOK\n'):
            with self.assertRaises(FactoryError):
                Validator.record({'checks': []}, 'reference', ProcessResult('', output, 0, .01), True)

    def test_secret_values_redacted_and_rejected(self):
        with patch.dict(os.environ, {'FIXTURE_API_KEY': 'secret-fixture-value'}):
            self.assertNotIn('secret-fixture-value', redact('value=secret-fixture-value'))
            with self.assertRaises(FactoryError):
                no_secrets('value=secret-fixture-value')

    def test_process_uses_argument_array_and_bounded_output(self):
        result = run([sys.executable, '-I', '-c', 'import sys; print(sys.argv[1])', 'x;$(do-not-run)'], max_bytes=10000)
        self.assertEqual(result.stdout.strip(), 'x;$(do-not-run)')
        with self.assertRaises(FactoryError):
            run([sys.executable, '-I', '-c', 'print("x"*100000)'], max_bytes=4096)

    def test_process_timeout(self):
        with self.assertRaises(FactoryError):
            run([sys.executable, '-I', '-c', 'import time; time.sleep(10)'], timeout=.1)

    def test_missing_harbor_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            stage = Path(directory) / 'stage'
            create_package(stage, proposal(), implementation(), c.validation['image'], evidence())
            result = Validator(c).validate(stage, Path(directory) / 'validation.json')
            self.assertFalse(result['passed'])
            self.assertIn('Harbor', result['error'])
            self.assertFalse(result['benchmark_executed'])
