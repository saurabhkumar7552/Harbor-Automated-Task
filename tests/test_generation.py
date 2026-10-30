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
from stem_factory.generation import GenerationFactory, GenerationValidator, preflight, require_entitlements
from stem_factory.packaging import create_package, static_check
from stem_factory.reporting import tree_hash
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
            self.assertEqual(result['calls_reserved'], 20)
            self.assertEqual(len(list((c.output / 'accepted').iterdir())), 5)

    def test_full_generation_validator_only_emits_docker_commands(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            stage = Path(d) / 'stage'
            create_package(stage, proposal(), implementation(), c.validation['image'],
                           {'proposal': proposal(), 'implementation': implementation()})
            validator = GenerationValidator(c)
            commands = []
            def transport(argv, **kwargs):
                commands.append(argv)
                self.assertEqual(argv[0], c.validation['docker_executable'])
                self.assertNotIn('harbor', ' '.join(argv).lower())
                return ProcessResult('sha256:' + 'a' * 64 if argv[1:3] == ['image', 'inspect'] else '', '', 0, .01)
            def container(package, work, image_id, reference=False, baked_tests=False):
                if reference:
                    (work / 'task.py').write_text(implementation()['reference_python'])
                    return ProcessResult('', '', 0, .01)
                success = (work / 'task.py').is_file() and (work / 'task.py').read_text() == implementation()['reference_python']
                return ProcessResult('', 'Ran 8 tests\n' + ('OK\n' if success else 'FAILED (failures=3)\n'),
                                     0 if success else 1, .01)
            with patch('stem_factory.validation.run', side_effect=transport), \
                 patch.object(validator, 'container', side_effect=container):
                result = validator.validate(stage, Path(d) / 'validation.json')
            self.assertTrue(result['passed'])
            self.assertEqual(len(result['checks']), 6)
            self.assertTrue(commands)
            self.assertFalse(result['benchmark_executed'])

    def test_role_separation_and_no_harbor(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = generation_config(d), providers()
            before = tree_hash(c.existing_tasks)
            with patch('stem_factory.validation.run', side_effect=AssertionError('external process forbidden')):
                result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(len(a['author'].calls), 2)
            self.assertEqual(len(a['reviewer'].calls), 2)
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
            c, a = generation_config(d, max_candidates=1, max_revisions=2), providers(True)
            result = GenerationFactory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(len(a['author'].calls), 3)
            self.assertEqual(len(a['reviewer'].calls), 3)
            self.assertIn('Specify units', a['author'].calls[1])
            self.assertNotIn('Specify units', a['reviewer'].calls[1])

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
            c = generation_config(d)
            result = GenerationFactory(c, adapters=providers(), validator=FakeValidator(False)).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(list((c.output / 'staging').iterdir()), [])
            self.assertEqual(list((c.output / 'accepted').iterdir()), [])
            self.assertTrue((c.output / 'failed/candidate-001-revision-00/solution/solve.sh').exists())
            with self.assertRaises(FactoryError):
                GenerationFactory(c, adapters=providers(), validator=FakeValidator()).run(1)

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
            self.assertTrue((c.output / 'failed/candidate-001-revision-00/partial').exists())

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
