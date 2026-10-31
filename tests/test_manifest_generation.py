"""Tool-neutral integration tests: fixture models, no generated code execution."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from stem_factory import contracts, task_spec
from stem_factory.cli import main
from stem_factory.config import load
from stem_factory.errors import FactoryError
from stem_factory.generation import GenerationFactory, GenerationValidator
from stem_factory.packaging import create_package, static_check
from stem_factory.reporting import tree_hash
from stem_factory.validation import Validator
from tests.fixtures import proposal, review
from tests.test_generation import generation_config
from tests.test_workflow import FakeAdapter


def manifest(domain='Physics', difficulty='hard', task_id='shell-orbit-summary'):
    p = proposal(task_id)
    p.update(domain=domain, difficulty=difficulty, specialization='Orbital measurements',
        problem_statement='Summarize observed orbital readings using /work/analyze.sh and /work/result.tsv.',
        functional_requirements=['Summarize orbital data', 'Reject malformed records'],
        dependencies=[], output_manifest=[{'path': '/work/analyze.sh', 'purpose': 'Analysis command'},
                                          {'path': '/work/result.tsv', 'purpose': 'Tabular output'}],
        starting_environment='POSIX shell and awk in a Linux container',
        environment_plan={'language': 'POSIX shell', 'submission_format': 'script and table',
            'tools': [{'name': 'awk', 'version': '1.36.1', 'purpose': 'Aggregate numeric readings'}],
            'base_image': 'alpine:3.20.3', 'setup_steps': [],
            'verifier_image': 'alpine:3.20.3', 'verifier_setup_steps': [],
            'resources': {'cpus': 2, 'memory_mb': 1024, 'agent_timeout_sec': 300,
                          'verifier_timeout_sec': 45}})
    return p


def bundle():
    return {'instruction': 'Produce /work/analyze.sh and /work/result.tsv to summarize orbital data; reject malformed records.',
        'starter_files': [{'path': 'measurements.tsv', 'content': '1\t4\n2\t8\n'}],
        'reference_files': [{'path': 'solve.sh', 'content': '#!/bin/sh\nprintf "orbital reference placeholder fixture\\n" > /work/result.tsv\n'}],
        'verifier_files': [{'path': 'verify.sh', 'content': '#!/bin/sh\n# test_orbit and test_invalid\ntest -f /work/result.tsv\n'}],
        'reference_command': ['sh', '/solution/files/solve.sh'],
        'verifier_command': ['sh', '/tests/private/verify.sh'],
        'test_cases': [{'id': 'test_orbit', 'purpose': 'Check orbital aggregation'},
                       {'id': 'test_invalid', 'purpose': 'Check malformed input'}],
        'requirements_traceability': [
            {'requirement': 'Summarize orbital data', 'tests': ['test_orbit']},
            {'requirement': 'Reject malformed records', 'tests': ['test_invalid']}]}


def configuration(directory, **request):
    c = generation_config(directory, max_candidates=2)
    data = json.loads(c.path.read_text())
    data['generation']['request'] = {'difficulty': 'hard', 'count': 1, **request}
    data['generation']['workflow'] = {'reviewer_passes': 1, 'author_repairs': 1}
    c.path.write_text(json.dumps(data))
    return load(c.path)


def models(difficulty='hard', reject=False):
    def author(index, prompt, schema):
        if set(schema.get('properties', {})) == {'proposal', 'implementation'}:
            return {'proposal': manifest(difficulty=difficulty), 'implementation': bundle()}
        if schema is contracts.MANIFEST_IMPLEMENTATION:
            return bundle()
        return manifest(difficulty=difficulty)
    def reviewer(index, prompt, schema):
        r = review(not reject)
        r['difficulty'] = difficulty
        r['dependent_steps'] = 1  # No universal medium-only three-step gate.
        return r
    a = FakeAdapter(author)
    return {'author': a, 'implementer': a, 'reviewer': FakeAdapter(reviewer)}


class ManifestGeneration(unittest.TestCase):
    def test_non_python_pipeline_uses_one_contract_and_resumes_without_calls(self):
        with tempfile.TemporaryDirectory() as d:
            c, adapters = configuration(d), models(reject=True)
            before = tree_hash(c.existing_tasks)
            with patch('subprocess.Popen', side_effect=AssertionError('No task/setup execution')):
                result = GenerationFactory(c, adapters=adapters).run(1)
                resumed = GenerationFactory(c, adapters=adapters).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 3)
            self.assertEqual(resumed['calls_reserved'], 3)
            self.assertEqual(len(adapters['reviewer'].calls), 1)
            self.assertIn('test PLAN', adapters['reviewer'].calls[0])
            self.assertNotIn('Python 3.13 standard library only', adapters['author'].calls[0])
            package = Path(result['candidates'][0]['package_path'])
            meta = tomllib.loads((package/'task.toml').read_text())
            self.assertEqual(meta['metadata']['difficulty'], 'hard')
            self.assertEqual(meta['artifacts'], ['/work/analyze.sh', '/work/result.tsv'])
            self.assertEqual(meta['agent']['network_mode'], 'no-network')
            self.assertEqual(meta['environment']['cpus'], 2)
            self.assertEqual(meta['verifier']['environment']['memory_mb'], 1024)
            self.assertEqual(meta['verifier']['timeout_sec'], 45.0)
            self.assertEqual((package/'environment/Dockerfile').read_text().splitlines()[0], 'FROM alpine:3.20.3')
            self.assertNotIn('solution', (package/'environment/Dockerfile').read_text())
            self.assertNotIn('private', (package/'environment/.dockerignore').read_text())
            self.assertEqual(result['candidates'][0]['language'], 'POSIX shell')
            self.assertEqual(result['candidates'][0]['environment_plan']['resources']['cpus'], 2)
            self.assertEqual(len(result['candidates'][0]['submission_artifacts']), 2)
            self.assertEqual(result['candidates'][0]['review_status'], 'repaired_without_rereview')
            self.assertEqual(tree_hash(c.existing_tasks), before)
            static_check(package, c.validation['image'])

    def test_easy_is_not_rejected_by_medium_criteria(self):
        with tempfile.TemporaryDirectory() as d:
            c, adapters = configuration(d, difficulty='easy'), models('easy')
            result = GenerationFactory(c, adapters=adapters).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 3)
            self.assertEqual(result['candidates'][0]['difficulty'], 'easy')

    def test_zero_repairs_preserves_review_concerns_and_still_packages(self):
        with tempfile.TemporaryDirectory() as d:
            c, adapters = configuration(d), models(reject=True)
            c.generation['workflow']['author_repairs'] = 0
            result = GenerationFactory(c, adapters=adapters).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 3)
            self.assertEqual(result['candidates'][0]['repairs_performed'], 1)
            self.assertEqual(result['candidates'][0]['review_status'], 'repaired_without_rereview')

    def test_configuration_and_fixed_selections_are_validated(self):
        for request in ({'difficulty': 'impossible'}, {'tools': 5}, {'count': True},
                        {'constraints': {'network_during_evaluation': 'false'}}, {'unknown': 'value'}):
            with self.subTest(request=request), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(FactoryError):
                    configuration(d, **request)
        request = {**task_spec.request_settings({'language': 'Julia'}), 'domain': 'Physics'}
        with self.assertRaisesRegex(FactoryError, 'language'):
            task_spec.validate_proposal(manifest(difficulty='medium'), request)
        fixed = {**task_spec.request_settings({'difficulty': 'hard', 'language': 'POSIX shell',
                 'tools': ['awk'], 'dependencies': [], 'submission_format': 'script and table'}),
                 'domain': 'Physics'}
        task_spec.validate_proposal(manifest(), fixed)
        wrong = manifest()
        wrong['environment_plan']['tools'][0]['name'] = 'sed'
        with self.assertRaisesRegex(FactoryError, 'tool names'):
            task_spec.validate_proposal(wrong, fixed)
        fixed['dependencies'] = ['bc']
        pinned = manifest()
        pinned['dependencies'] = [{'name': 'bc', 'version': '1.07.1', 'purpose': 'Decimal arithmetic'}]
        task_spec.validate_proposal(pinned, fixed)
        pinned['dependencies'][0]['version'] = '>=1.0'
        with self.assertRaisesRegex(FactoryError, 'exact tool and dependency versions'):
            task_spec.validate_proposal(pinned, fixed)

    def test_subject_assignment_does_not_stall_when_candidate_fails(self):
        with tempfile.TemporaryDirectory() as d:
            c = configuration(d)
            c.generation['subjects'] = ['Physics', 'Chemistry']
            factory = GenerationFactory(c, adapters=models())
            self.assertEqual(factory.run_request({'index': 1})['domain'], 'Physics')
            self.assertEqual(factory.run_request({'index': 2})['domain'], 'Chemistry')
            schema = factory.proposal_schema({'index': 2})
            with self.assertRaisesRegex(FactoryError, 'Chemistry'):
                contracts.validate(manifest('Physics'), schema)

    def test_cli_uses_configured_count_without_starting_models(self):
        with tempfile.TemporaryDirectory() as d:
            c = configuration(d, count=2)
            with redirect_stdout(io.StringIO()) as output, patch('subprocess.Popen', side_effect=AssertionError('no processes')):
                self.assertEqual(main(['--config', str(c.path), 'generate', '--dry-run']), 0)
            data = json.loads(output.getvalue())
            self.assertEqual(data['target'], 2)
            self.assertEqual(data['profile'], 'manifest-v1')
            self.assertEqual(data['difficulty'], 'hard')
            self.assertFalse(c.output.exists())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--config', str(c.path), 'generate', '--target', '1', '--dry-run']), 0)
            self.assertEqual(json.loads(output.getvalue())['target'], 1)

    def test_manifest_rejects_traversal_traceability_and_setup_injection(self):
        for kind in ('traversal', 'setup', 'leakage'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                c = configuration(d)
                p, b = manifest(), bundle()
                if kind == 'traversal': b['reference_files'][0]['path'] = '../escape.sh'
                elif kind == 'traceability': b['requirements_traceability'][0]['tests'] = ['invented']
                elif kind == 'setup': p['environment_plan']['setup_steps'] = ['echo ok\nCOPY /solution /work']
                else: b['starter_files'][0]['content'] = b['reference_files'][0]['content']
                evidence = {'profile': 'manifest-v1', 'task_request': {**c.generation['request'], 'domain': 'Physics'},
                            'proposal': p, 'implementation': b}
                with self.assertRaises(FactoryError):
                    create_package(Path(d)/'package', p, b, c.validation['image'], evidence)
                self.assertFalse((Path(d)/'escape.sh').exists())

    def test_tampered_verifier_and_extra_public_files_fail_static_validation(self):
        with tempfile.TemporaryDirectory() as d:
            c = configuration(d)
            result = GenerationFactory(c, adapters=models()).run(1)
            package = Path(result['candidates'][0]['package_path'])
            with patch('subprocess.Popen', side_effect=AssertionError('No legacy runtime execution')):
                legacy = Validator(c).validate(package, Path(d)/'legacy.json')
            self.assertFalse(legacy['passed'])
            self.assertIn('dedicated Harbor runner', legacy['error'])
            verifier = package/'tests/private/verify.sh'
            verifier.write_text('exit 0\n', newline='\n')
            report = GenerationValidator(c).validate(package, Path(d)/'validation.json')
            self.assertFalse(report['passed'])
            self.assertIn('differs from declared content', report['error'])
            verifier.write_text(bundle()['verifier_files'][0]['content'], newline='\n')
            (package/'environment/leaked-private.txt').write_text('unexpected', newline='\n')
            with self.assertRaisesRegex(FactoryError, 'Unexpected or missing'):
                static_check(package, c.validation['image'])


if __name__ == '__main__':
    unittest.main()
