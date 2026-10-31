"""Offline control-plane tests; fixtures never establish real task quality/isolation."""
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stem_factory import contracts
from stem_factory.adapters.codex import CodexAdapter
from stem_factory.cli import main
from stem_factory.config import load
from stem_factory.errors import FactoryError
from stem_factory.environment import inspect_environment
from stem_factory.generation import GenerationFactory, GenerationValidator, preflight, require_entitlements
from stem_factory.packaging import create_package, static_check
from stem_factory.reporting import tree_hash
import tomllib
from stem_factory.process import ProcessResult
from tests.fixtures import config, proposal, implementation, review, audit
from tests.test_workflow import FakeAdapter, FakeValidator


def generation_config(directory, **limits):
    c = config(directory, **limits)
    data = json.loads(c.path.read_text())
    data['roles']['implementer'] = data['roles']['author'].copy()
    data['generation'] = {'subjects': ['Physics'], 'entitlements': {
        name: {'model': data['roles'][name]['model'], 'source': 'MOCK entitlement evidence, not real account access'}
        for name in ('author', 'reviewer')}}
    data['execution'] = {'live_enabled': True, 'stop_on_validation_failure': True}
    c.path.write_text(json.dumps(data))
    return load(c.path)


def providers(reject=False):
    def author(index, prompt, schema):
        return implementation() if schema is contracts.IMPLEMENTATION else proposal()
    a = FakeAdapter(author)
    r = FakeAdapter(lambda index, prompt, schema: audit() if schema is contracts.AUDIT else review(not reject))
    return {'author': a, 'implementer': a, 'reviewer': r}


class GenerationTests(unittest.TestCase):
    def test_preflight_checks_each_provider_once_without_task_image(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = generation_config(d), providers()
            validator = FakeValidator()
            with patch.object(validator, 'image_identity', side_effect=AssertionError('task image not needed')), \
                 patch.object(a['author'], 'preflight') as author, \
                 patch.object(a['reviewer'], 'preflight') as reviewer:
                GenerationFactory(c, adapters=a, validator=validator).preflight()
            author.assert_called_once()
            reviewer.assert_called_once()

    def test_environment_change_after_repair_cannot_publish_stale_content(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d, max_candidates=1)
            a = providers(True)
            invoke = a['author'].function
            def change_after_implementation(index, prompt, schema):
                value = invoke(index, prompt, schema)
                if schema is contracts.IMPLEMENTATION:
                    example = c.existing_tasks / 'new-example'
                    (example / 'environment').mkdir(parents=True)
                    (example / 'task.toml').write_text('schema_version = "1.3"\n')
                    (example / 'environment/Dockerfile').write_text('FROM python:3.13.0-slim-bookworm\nWORKDIR /changed\n')
                return value
            a['author'].function = change_after_implementation
            result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(result['candidates'][0]['status'], 'rejected')
            self.assertIn('Environment changed', result['candidates'][0]['reason'])
            self.assertEqual(len(a['reviewer'].calls), 1)

    def test_real_adapter_wiring_is_strict_and_legacy_injection_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            f = GenerationFactory(c)
            self.assertIs(f.adapters['author'], f.adapters['implementer'])
            self.assertTrue(all(a.strict_isolation for a in f.adapters.values()))
            with patch('stem_factory.adapters.base.run', side_effect=AssertionError('no host process')), \
                 patch('stem_factory.validation.run', side_effect=AssertionError('no Docker')):
                with self.assertRaises(FactoryError):
                    f.run(1)
            self.assertFalse(c.output.exists())
            with self.assertRaises(FactoryError):
                GenerationFactory(c, adapters={'author': CodexAdapter(c.roles['author'])})

    def test_static_preflight_reports_separate_blockers_without_processes(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            with patch('subprocess.Popen', side_effect=AssertionError('no process')), \
                 patch('stem_factory.adapters.base.run', side_effect=AssertionError('no CLI')):
                result = preflight(c, 5)
            self.assertFalse(result['ready_for_live_generation'])
            self.assertEqual(result['authentication_status'], 'Unverified; no authentication probe performed')
            for item in result['isolation'].values():
                self.assertEqual(item['static_evidence'], 'invalid')
                self.assertEqual(item['isolated_health'], 'not_implemented')
                self.assertFalse(item['ready_for_execution'])
            self.assertFalse(c.output.exists())

    def test_five_accepted_subjects_with_mocked_providers(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            subjects = ['Physics', 'Mathematics', 'Chemistry', 'Engineering', 'Statistics']
            c.generation['subjects'] = subjects
            vocabularies = ['isotopes radiation decay half lives', 'polynomial roots sturm sequences intervals',
                            'molecules reaction equilibrium concentrations', 'circuits impedance voltage resistance',
                            'samples likelihood quantiles confidence bootstrap']
            count = [0]
            def author(index, prompt, schema):
                if schema is contracts.IMPLEMENTATION:
                    i = implementation()
                    i['instruction'] = vocabularies[count[0] - 1] + ' /work/task.py'
                    return i
                slot = count[0]
                count[0] += 1
                p = proposal('fixture-' + str(slot))
                p.update(domain=subjects[slot], title=vocabularies[slot],
                         problem_statement=vocabularies[slot], learning_objective=vocabularies[slot])
                return p
            a = FakeAdapter(author)
            r = FakeAdapter(lambda index, prompt, schema: audit() if schema is contracts.AUDIT else review())
            result = GenerationFactory(c, adapters={'author': a, 'implementer': a, 'reviewer': r},
                                       validator=FakeValidator()).run(5)
            self.assertEqual(result['accepted'], 5)
            self.assertEqual(result['calls_reserved'], 15)
            self.assertEqual(len(list((c.output / 'accepted').iterdir())), 5)

    def test_generation_validation_is_static_and_reports_runtime_checks_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            stage = Path(d) / 'stage'
            create_package(stage, proposal(), implementation(), c.validation['image'],
                           {'proposal': proposal(), 'implementation': implementation()})
            validator = GenerationValidator(c)
            with patch('stem_factory.validation.run', side_effect=AssertionError('Docker is not run')):
                result = validator.validate(stage, Path(d) / 'validation.json')
            self.assertTrue(result['passed'])
            self.assertFalse(result['docker_build_verified'])
            self.assertEqual(result['harbor_execution'], 'not_run')
            self.assertIn('Docker image build', result['checks_not_run'])

    def test_role_separation_and_no_harbor(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = generation_config(d), providers()
            before = tree_hash(c.existing_tasks)
            with patch('stem_factory.validation.run', side_effect=AssertionError('external process forbidden')):
                result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(len(a['author'].calls), 2)
            self.assertEqual(len(a['reviewer'].calls), 1)
            self.assertIn('environment_spec', a['author'].calls[0])
            self.assertIn('verified_environment', a['reviewer'].calls[0])
            self.assertIn('verified_environment', a['author'].calls[1])
            self.assertNotIn('difficulty_rationale', a['reviewer'].calls[0].split('BEGIN UNTRUSTED INPUT DATA')[1])
            self.assertEqual(tree_hash(c.existing_tasks), before)

    def test_configuration_rejects_role_overrides(self):
        for change in ('same_model', 'different_cli', 'different_implementer', 'provider_override'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                c = generation_config(d)
                data = json.loads(c.path.read_text())
                if change == 'same_model':
                    data['roles']['reviewer']['model'] = data['roles']['author']['model']
                elif change == 'different_cli':
                    data['roles']['reviewer']['executable'] = 'other-cli'
                elif change == 'different_implementer':
                    data['roles']['implementer']['model'] = 'other-model'
                else:
                    data['roles']['reviewer']['args'] = ['--oss']
                c.path.write_text(json.dumps(data))
                with self.assertRaises(FactoryError):
                    load(c.path)

    def test_unverified_and_stale_evidence_block_before_calls_or_writes(self):
        for evidence in (None, {'model': 'other-model', 'source': 'mock'}):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as d:
                c, a = generation_config(d), providers()
                c.generation['entitlements']['author'] = evidence
                with self.assertRaises(FactoryError):
                    GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
                self.assertFalse(c.output.exists())
                self.assertEqual(a['author'].calls, [])

    def test_revision_bound_and_fresh_review(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = generation_config(d, max_candidates=1, max_revisions=3), providers(True)
            result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(len(a['author'].calls), 3)  # initial proposal, repair, implementation
            self.assertEqual(len(a['reviewer'].calls), 1)  # one review only
            self.assertIn('Specify units', a['author'].calls[1])
            self.assertIn('Specify units', a['author'].calls[2])
            self.assertEqual(result['candidates'][0]['repairs_performed'], 1)
            self.assertEqual(result['candidates'][0]['review_status'], 'repaired_without_rereview')
            self.assertEqual(result['candidates'][0]['package_validation_status'], 'offline_valid')
            self.assertEqual(result['candidates'][0]['harbor_execution_status'], 'not_run')
            self.assertTrue(result['candidates'][0]['review_findings'])

    def test_environment_inspection_drives_package_metadata_and_is_fingerprinted(self):
        with tempfile.TemporaryDirectory() as d:
            tasks = Path(d) / 'tasks'
            example = tasks / 'sample'
            (example / 'environment').mkdir(parents=True)
            (example / 'task.toml').write_text('''schema_version = "1.3"
artifacts = ["/work/sample.py"]
[agent]
timeout_sec = 300.0
network_mode = "public"
[verifier]
timeout_sec = 45.0
network_mode = "no-network"
environment_mode = "separate"
[verifier.environment]
network_mode = "no-network"
build_timeout_sec = 450.0
os = "linux"
cpus = 1
memory_mb = 384
[environment]
network_mode = "public"
build_timeout_sec = 500.0
os = "linux"
cpus = 1
memory_mb = 768
''')
            dockerfile = example / 'environment' / 'Dockerfile'
            dockerfile.write_text('FROM python:3.13.0-slim-bookworm\nWORKDIR /work\n')
            (example / 'environment' / '.dockerignore').write_text('**\n!Dockerfile\n')
            selected = 'python:3.13.0-slim-bookworm'
            spec = inspect_environment(tasks, selected)
            self.assertEqual(spec['runtime']['base_image'], selected)
            self.assertEqual(spec['runtime']['working_directory'], '/work')
            self.assertTrue(spec['fingerprint'])

            c = generation_config(d)
            implementation_bundle = implementation()
            stage = Path(d) / 'package'
            evidence = {'proposal': proposal(), 'implementation': implementation_bundle,
                        'environment_spec': spec, 'environment_fingerprint': spec['fingerprint']}
            create_package(stage, proposal(), implementation_bundle, selected, evidence)
            metadata = tomllib.loads((stage / 'task.toml').read_text())
            self.assertEqual(metadata['agent']['timeout_sec'], 300.0)
            self.assertEqual(metadata['verifier']['timeout_sec'], 45.0)
            self.assertEqual(metadata['verifier']['environment']['memory_mb'], 384)
            self.assertEqual(static_check(stage, selected)['environment_fingerprint'], spec['fingerprint'])

            dockerfile.write_text('FROM python:3.13.0-slim-bookworm\nWORKDIR /task\n')
            changed = inspect_environment(tasks, selected)
            self.assertNotEqual(spec['fingerprint'], changed['fingerprint'])

    def test_malformed_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = generation_config(d, max_candidates=1, max_revisions=0), providers()
            a['author'].function = lambda *args: {'task_id': 'broken'}
            result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(a['reviewer'].calls, [])

    def test_duplicate_and_near_duplicate_rejected(self):
        for identifier in ('coupled-decay', 'renamed-decay'):
            with self.subTest(identifier=identifier), tempfile.TemporaryDirectory() as d:
                c, a = generation_config(d, max_candidates=1, max_revisions=0), providers()
                existing = c.existing_tasks / identifier
                existing.mkdir()
                p = proposal()
                (existing / 'instruction.md').write_text(p['title'] + ' ' + p['problem_statement'] + ' ' + p['learning_objective'])
                result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
                self.assertEqual(result['accepted'], 0)
                self.assertEqual(a['reviewer'].calls, [])

    def test_validation_failure_archives_partial_package_and_halts(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d, max_candidates=1)
            result = GenerationFactory(c, adapters=providers(), validator=FakeValidator(False)).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(list((c.output / 'staging').iterdir()), [])
            self.assertEqual(list((c.output / 'accepted').iterdir()), [])
            self.assertTrue(list((c.output / 'failed').rglob('solve.sh')))
            self.assertEqual(result['candidates'][0]['package_validation_status'], 'failed')
            self.assertFalse(result['halted'])

    def test_partial_write_failure_never_publishes(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            def partial(stage, *args):
                stage.mkdir()
                (stage / 'partial').write_text('incomplete')
                raise OSError('mock interrupted write')
            with patch('stem_factory.factory.create_package', side_effect=partial):
                result = GenerationFactory(c, adapters=providers(), validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(list((c.output / 'staging').iterdir()), [])
            self.assertTrue(list((c.output / 'failed').glob('candidate-001-revision-00-env-*/partial')))

    def test_dry_run_no_calls_processes_or_output_and_old_commands_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            with patch('stem_factory.adapters.base.run', side_effect=AssertionError('CLI forbidden')), \
                 patch('stem_factory.validation.run', side_effect=AssertionError('runtime forbidden')), \
                 patch('stem_factory.generation.GenerationFactory', side_effect=AssertionError('factory forbidden')), \
                 redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['--config', str(c.path), 'generate', '--dry-run']), 0)
            result = json.loads(out.getvalue())
            self.assertFalse(result['harbor_required'])
            self.assertFalse(result['docker_required_for_preflight'])
            self.assertEqual(result['inference_calls'], 0)
            self.assertFalse(c.output.exists())
            self.assertEqual(main(['--config', str(c.path), 'run', '--dry-run']), 2)

    def test_generation_schema_is_local_only(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            p, i = proposal(), implementation()
            stage = Path(d) / 'package'
            create_package(stage, p, i, c.validation['image'], {'proposal': p, 'implementation': i})
            with patch('stem_factory.validation.run', side_effect=AssertionError('Harbor forbidden')):
                self.assertEqual(GenerationValidator(c).schema(stage)['local_template']['static'], 'PASS')
            (stage / 'task.toml').write_text('invalid metadata')
            with self.assertRaises((FactoryError, ValueError)):
                static_check(stage, c.validation['image'])

    def test_subject_mix_uses_accepted_count_and_exact_domain(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            c.generation['subjects'] = ['Physics', 'Mathematics']
            f = GenerationFactory(c, adapters=providers(), validator=FakeValidator())
            class StateFixture:
                data = {'candidates': [{'status': 'rejected'}, {'status': 'accepted'}]}
            f.state = StateFixture()
            self.assertEqual(f.subject(), 'Mathematics')
            self.assertIn('Required domain: Mathematics', f.author_request([], {}))
            with self.assertRaises(FactoryError):
                f.validate_proposal(proposal())

    def test_disabled_live_run_no_process_or_output(self):
        with tempfile.TemporaryDirectory() as d:
            c = replace(generation_config(d), execution={'live_enabled': False, 'stop_on_validation_failure': True})
            with patch('stem_factory.validation.run', side_effect=AssertionError('external process forbidden')):
                with self.assertRaises(FactoryError):
                    GenerationFactory(c, adapters=providers()).run(1)
            self.assertFalse(c.output.exists())
