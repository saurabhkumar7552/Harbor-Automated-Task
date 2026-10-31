"""Mock-only Docker transport tests; never run a daemon, container or model."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stem_factory import contracts
from stem_factory.adapters.codex import CodexAdapter
from stem_factory.adapters.docker_codex import DockerCodexAdapter
from stem_factory.config import load
from stem_factory.cli import main
from stem_factory.errors import FactoryError
from stem_factory.generation import GenerationFactory, preflight
from stem_factory.process import ProcessFailure, ProcessResult
from tests.test_generation import generation_config
from tests.fixtures import proposal, implementation, review, audit
from tests.test_workflow import FakeValidator


IMAGE = 'sha256:' + 'a' * 64


def docker_config(directory, enabled=True):
    c = generation_config(directory)
    data = json.loads(c.path.read_text())
    data['execution']['live_enabled'] = enabled
    data['generation'].update(transport='docker', docker={
        'image': IMAGE, 'auth_volume': 'MOCK-credential-volume',
        'cpus': 1, 'memory_mb': 1024, 'pids_limit': 128})
    for role in data['roles'].values():
        role['executable'] = 'codex'
    c.path.write_text(json.dumps(data))
    return load(c.path)


def answer(value=None):
    value = {'mock': True} if value is None else value
    return '\n'.join(json.dumps(event) for event in (
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(value)}},
        {'type': 'turn.completed', 'usage': {'fixture_tokens': 1}}))


class DockerTransport(unittest.TestCase):
    def transport(self, calls, *, output=None, start_error=None, residual=False):
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            tail = argv[1:]
            stdout = ''
            if tail[:2] == ['context', 'inspect']:
                stdout = 'npipe:////./pipe/MOCK-Docker'
            elif tail[:1] == ['version']:
                stdout = 'linux'
            elif tail[:2] == ['image', 'inspect']:
                stdout = IMAGE + ' linux'
            elif tail[:2] == ['volume', 'inspect']:
                stdout = 'local plain'
            elif tail[:1] == ['start']:
                if start_error:
                    raise start_error
                stdout = answer() if output is None else output
            elif tail[:2] == ['container', 'ls'] and residual:
                stdout = 'MOCK-survivor'
            return ProcessResult(stdout, '', 0, .01)
        return run

    def workspace(self, c, name='request-author'):
        workspace = c.output / 'agent-work' / name
        workspace.mkdir(parents=True)
        return workspace

    def test_configuration_rejects_incompatible_or_unbounded_settings(self):
        for change in ('tag', 'host_path', 'resources', 'unknown', 'launcher', 'executable', 'host_env', 'strict'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                c = docker_config(d)
                data = json.loads(c.path.read_text())
                settings = data['generation']['docker']
                if change == 'tag':
                    settings['image'] = 'codex:latest'
                elif change == 'host_path':
                    settings['auth_volume'] = 'C:/Users/operator'
                elif change == 'resources':
                    settings['pids_limit'] = 0
                elif change == 'unknown':
                    settings['network'] = 'host'
                elif change == 'strict':
                    data['generation']['transport'] = 'strict'
                else:
                    for role in data['roles'].values():
                        role[{'launcher': 'launcher', 'executable': 'executable', 'host_env': 'required_env'}[change]] = {
                            'launcher': ['wrapper'], 'executable': 'host-codex.exe', 'host_env': ['CODEX_ACCESS_TOKEN']}[change]
                c.path.write_text(json.dumps(data))
                with self.assertRaises(FactoryError):
                    load(c.path)

    def test_explicit_docker_wiring_shared_health_and_no_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            f = GenerationFactory(c)
            self.assertIsInstance(f.adapters['author'], DockerCodexAdapter)
            self.assertIs(f.adapters['author'], f.adapters['implementer'])
            self.assertIs(f.adapters['author'].health, f.adapters['reviewer'].health)
            with self.assertRaises(FactoryError):
                GenerationFactory(c, adapters={'author': CodexAdapter(c.roles['author'])})

    def test_dry_run_reports_new_contract_and_missing_runtime_without_processes(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d, enabled=False)
            c.generation['docker'].update(image=None, auth_volume=None)
            with patch('subprocess.Popen', side_effect=AssertionError('no process')):
                r = preflight(c, 5)
            self.assertEqual(r['transport'], 'docker')
            self.assertEqual(r['target'], 5)
            self.assertEqual(r['difficulty'], 'medium')
            self.assertFalse(r['ready_for_live_generation'])
            self.assertIn('tools', r['isolation']['author'])
            self.assertTrue(any('image ID' in b for b in r['blockers']))
            self.assertTrue(any('authentication volume' in b for b in r['blockers']))
            self.assertFalse(c.output.exists())

    def test_disabled_and_missing_prerequisites_stop_before_commands_or_writes(self):
        for disabled in (True, False):
            with self.subTest(disabled=disabled), tempfile.TemporaryDirectory() as d:
                c = docker_config(d, enabled=not disabled)
                if not disabled:
                    c.generation['docker']['image'] = None
                a = DockerCodexAdapter(c, c.roles['author'])
                with patch('stem_factory.adapters.docker_codex.run', side_effect=AssertionError('no process')):
                    with self.assertRaises(FactoryError):
                        a.preflight()
                    with self.assertRaises(FactoryError):
                        a.invoke('MOCK', {}, c.output / 'absent')
                self.assertFalse(c.output.exists())

    def test_request_is_scoped_bounded_structured_and_removed(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            work = self.workspace(c)
            a = DockerCodexAdapter(c, c.roles['author'])
            calls = []
            with patch.dict('os.environ', {'DOCKER_HOST': ''}), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=self.transport(calls)):
                self.assertEqual(a.invoke('MOCK private prompt', {'type': 'object'}, work).value, {'mock': True})
            create = next(argv for argv, _ in calls if argv[1] == 'create')
            self.assertEqual(create[create.index('--network') + 1], 'bridge')
            for flag in ('--read-only', '--cap-drop', '--security-opt', '--pids-limit', '--memory', '--cpus', '--init'):
                self.assertIn(flag, create)
            self.assertEqual(create[create.index('--pull') + 1], 'never')
            self.assertEqual(create[create.index('--user') + 1], '1000:1000')
            self.assertEqual(create[create.index('--entrypoint') + 1], '/usr/bin/timeout')
            self.assertIn('--kill-after=5s', create)
            self.assertIn(f'type=bind,source={work.resolve()},target=/work,readonly', create)
            self.assertIn('type=volume,source=MOCK-credential-volume,target=/codex-home,volume-nocopy', create)
            self.assertIn('/work/response-schema.json', create)
            self.assertEqual(create[create.index('--model') + 1], c.roles['author'].model)
            self.assertNotIn('--privileged', create)
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', create)
            self.assertNotIn('docker.sock', ' '.join(create))
            self.assertNotIn('MOCK private prompt', ' '.join(create))
            self.assertEqual(next(kwargs['stdin'] for argv, kwargs in calls if argv[1] == 'start'), 'MOCK private prompt')
            self.assertEqual(calls[-2][0][1:4], ['rm', '--force', '--volumes'])
            self.assertEqual(calls[-1][0][1:3], ['container', 'ls'])

    def test_invalid_workspace_and_old_material_cannot_be_mounted(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            a = DockerCodexAdapter(c, c.roles['author'])
            work = self.workspace(c)
            (work / 'old-transcript.json').write_text('MOCK')
            for bad in (work, Path(d)):
                with self.subTest(bad=bad), patch.object(a, '_metadata'):
                    with self.assertRaises(FactoryError):
                        a.invoke('MOCK', {}, bad)
            self.assertFalse((work / 'response-schema.json').exists())

    def test_timeout_and_cancellation_remove_daemon_side_container(self):
        for error in (ProcessFailure('MOCK timeout', '', ''), ProcessFailure('MOCK overflow', '', ''), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as d:
                c = docker_config(d)
                a = DockerCodexAdapter(c, c.roles['author'])
                calls = []
                with patch('stem_factory.adapters.docker_codex.run', side_effect=self.transport(calls, start_error=error)):
                    with self.assertRaises(type(error)):
                        a._execute(['--version'])
                self.assertEqual(calls[-2][0][1:4], ['rm', '--force', '--volumes'])
                self.assertEqual(calls[-1][0][1:3], ['container', 'ls'])
                self.assertFalse(a.health['cleanup_failed'])

    def test_uncertain_cleanup_blocks_both_roles_without_more_processes(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            f = GenerationFactory(c)
            a, r = f.adapters['author'], f.adapters['reviewer']
            calls = []
            with patch('stem_factory.adapters.docker_codex.run', side_effect=self.transport(calls, residual=True)):
                with self.assertRaisesRegex(FactoryError, 'cleanup'):
                    a._execute(['--version'])
            with patch('stem_factory.adapters.docker_codex.run', side_effect=AssertionError('no further processes')):
                with self.assertRaisesRegex(FactoryError, 'cleanup'):
                    r.preflight()
                self.assertTrue((c.output / 'docker-cleanup-blocked.json').exists())
                with self.assertRaisesRegex(FactoryError, 'cleanup'):
                    DockerCodexAdapter(c, c.roles['reviewer']).preflight()

    def test_bad_daemon_image_volume_or_remote_context_never_starts_container(self):
        for target, output in (('version', 'windows'), ('image', 'sha256:changed linux'),
                               ('volume', 'missing-driver'), ('context', 'ssh://MOCK-remote')):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as d:
                c = docker_config(d)
                a = DockerCodexAdapter(c, c.roles['author'])
                calls = []
                normal = self.transport(calls)
                def transport(argv, **kwargs):
                    if argv[1] == target:
                        calls.append((argv, kwargs))
                        return ProcessResult(output, '', 0, .01)
                    return normal(argv, **kwargs)
                with patch.dict('os.environ', {'DOCKER_HOST': ''}), \
                     patch('stem_factory.adapters.docker_codex.run', side_effect=transport):
                    with self.assertRaises(FactoryError):
                        a.preflight()
                self.assertFalse(any(argv[1] in ('create', 'start') for argv, _ in calls))

    def test_preflight_probes_have_no_credentials_no_network_and_no_inference(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            a = DockerCodexAdapter(c, c.roles['author'])
            calls, created = [], []
            normal = self.transport(calls)
            def transport(argv, **kwargs):
                if argv[1] == 'create':
                    created.append(argv)
                if argv[1] == 'start':
                    calls.append((argv, kwargs))
                    text = 'codex-cli 0.165.0' if created[-1][-1] == '--version' else ' '.join(CodexAdapter.required_flags)
                    return ProcessResult(text, '', 0, .01)
                return normal(argv, **kwargs)
            with patch.dict('os.environ', {'DOCKER_HOST': ''}), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=transport):
                a.preflight()
            self.assertEqual(len(created), 2)
            for argv in created:
                self.assertEqual(argv[argv.index('--network') + 1], 'none')
                self.assertNotIn('--mount', argv)
                self.assertNotIn('--model', argv)
            self.assertFalse(c.output.exists())

    def test_malformed_response_is_rejected_after_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            a = DockerCodexAdapter(c, c.roles['reviewer'])
            calls = []
            with patch.object(a, '_metadata'), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=self.transport(calls, output='not JSON')):
                with self.assertRaises(FactoryError):
                    a.invoke('MOCK', {}, self.workspace(c))
            self.assertEqual(calls[-1][0][1:3], ['container', 'ls'])

    def test_health_works_disabled_without_auth_and_cannot_take_inference_input(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d, enabled=False)
            c.generation['docker']['auth_volume'] = None
            a = DockerCodexAdapter(c, c.roles['author'])
            calls, created = [], []
            normal = self.transport(calls)
            def transport(argv, **kwargs):
                if argv[1] == 'create':
                    created.append(argv)
                if argv[1] == 'start':
                    calls.append((argv, kwargs))
                    text = 'codex-cli 0.165.0' if created[-1][-1] == '--version' else ' '.join(CodexAdapter.required_flags)
                    return ProcessResult(text, '', 0, .01)
                return normal(argv, **kwargs)
            with patch.dict('os.environ', {'DOCKER_HOST': ''}), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=transport):
                result = a.check_image()
            self.assertEqual(result['inference_calls'], 0)
            self.assertFalse(result['ready_for_live_generation'])
            self.assertFalse(any(argv[1] == 'volume' for argv, _ in calls))
            for argv in created:
                self.assertNotIn('--mount', argv)
            with patch('stem_factory.adapters.docker_codex.run', side_effect=AssertionError('no process')):
                for args, options in ((['exec', '-'], {}), (['--version'], {'prompt': 'MOCK'}),
                                       (['exec', '--help'], {'network': 'bridge'}),
                                       (['--version'], {'workspace': Path(d)})):
                    with self.assertRaises(FactoryError):
                        a._execute(args, probe=True, **options)

    def test_context_override_and_bind_backed_auth_volume_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            a = DockerCodexAdapter(c, c.roles['author'])
            calls = []
            normal = self.transport(calls)
            def transport(argv, **kwargs):
                if argv[1] == 'context':
                    return ProcessResult('ssh://MOCK-remote', '', 0, .01)
                return normal(argv, **kwargs)
            with patch.dict('os.environ', {'DOCKER_HOST': 'npipe:////./pipe/MOCK', 'DOCKER_CONTEXT': 'MOCK-remote'}), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=transport):
                with self.assertRaisesRegex(FactoryError, 'local daemon'):
                    a.preflight()
            def volume_transport(argv, **kwargs):
                if argv[1] == 'volume':
                    return ProcessResult('local custom', '', 0, .01)
                return normal(argv, **kwargs)
            with patch.dict('os.environ', {'DOCKER_HOST': ''}), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=volume_transport):
                with self.assertRaisesRegex(FactoryError, 'credential volume'):
                    a.preflight()
            self.assertFalse(any(argv[1] in ('create', 'start') for argv, _ in calls))

    def test_five_tasks_through_real_docker_adapter_with_only_mocked_transport(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            domains = ['Physics', 'Mathematics', 'Chemistry', 'Engineering', 'Statistics']
            words = ['isotopes radiation decay half lives', 'polynomial roots sturm sequences intervals',
                     'molecules reaction equilibrium concentrations', 'circuits impedance voltage resistance',
                     'samples likelihood quantiles confidence bootstrap']
            c.generation['subjects'] = domains
            calls, created, models, requests = [], [], [], []
            normal = self.transport(calls)
            count = 0
            def transport(argv, **kwargs):
                nonlocal count
                if argv[1] == 'create':
                    created.append(argv)
                if argv[1] == 'start':
                    create = created[-1]
                    mounts = [v for v in create if v.startswith('type=bind,source=')]
                    if not mounts:
                        text = 'codex-cli 0.165.0' if create[-1] == '--version' else ' '.join(CodexAdapter.required_flags)
                    else:
                        path = Path(mounts[0].removeprefix('type=bind,source=').split(',target=')[0])
                        schema = json.loads((path / 'response-schema.json').read_text())
                        models.append(create[create.index('--model') + 1])
                        requests.append(path)
                        if schema == contracts.PROPOSAL:
                            value = proposal('fixture-' + str(count))
                            value.update(domain=domains[count], title=words[count],
                                         problem_statement=words[count], learning_objective=words[count])
                            count += 1
                        elif schema == contracts.IMPLEMENTATION:
                            value = implementation()
                            value['instruction'] = words[count - 1] + ' /work/task.py'
                        elif schema == contracts.REVIEW:
                            value = review()
                        else:
                            self.assertEqual(schema, contracts.AUDIT)
                            value = audit()
                        text = answer(value)
                    calls.append((argv, kwargs))
                    return ProcessResult(text, '', 0, .01)
                return normal(argv, **kwargs)
            with patch.dict('os.environ', {'DOCKER_HOST': ''}), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=transport), \
                 patch('stem_factory.validation.run', side_effect=AssertionError('real Docker forbidden')):
                result = GenerationFactory(c, validator=FakeValidator()).run(5)
            self.assertEqual(result['accepted'], 5)
            self.assertEqual(models.count(c.roles['author'].model), 10)
            self.assertEqual(models.count(c.roles['reviewer'].model), 5)
            self.assertEqual(len(requests), len(set(requests)))
            names = [argv[argv.index('--name') + 1] for argv in created]
            self.assertEqual(len(names), len(set(names)))

    def test_health_cli_is_explicit_docker_only_and_does_not_enable_generation(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d, enabled=False)
            with patch.object(DockerCodexAdapter, 'check_image', return_value={'inference_calls': 0}), \
                 patch('stem_factory.cli.Factory', side_effect=AssertionError('no factory')), \
                 redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['--config', str(c.path), 'generation-health']), 0)
            self.assertEqual(json.loads(out.getvalue())['inference_calls'], 0)
            self.assertFalse(load(c.path).execution['live_enabled'])
            self.assertFalse(c.output.exists())
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            with patch('subprocess.Popen', side_effect=AssertionError('no host process')), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--config', str(c.path), 'generation-health']), 2)

    def test_unconfirmed_model_and_linked_workspace_fail_before_container_creation(self):
        with tempfile.TemporaryDirectory() as d:
            c = docker_config(d)
            a = DockerCodexAdapter(c, c.roles['author'])
            c.generation['entitlements']['reviewer'] = None
            with patch('stem_factory.adapters.docker_codex.run', side_effect=AssertionError('no process')):
                with self.assertRaises(FactoryError):
                    a.invoke('MOCK', {}, c.output / 'not-created')
            work = self.workspace(c)
            with patch.object(a, '_metadata'), patch.object(Path, 'is_symlink', return_value=True), \
                 patch('stem_factory.adapters.docker_codex.run', side_effect=AssertionError('no process')):
                with self.assertRaisesRegex(FactoryError, 'symlinks'):
                    a.invoke('MOCK', {}, work)
            self.assertEqual(list(work.iterdir()), [])
