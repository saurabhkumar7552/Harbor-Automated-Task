"""Fixed local Docker operations only. This module never invokes Harbor execution."""
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid
from .errors import FactoryError
from .packaging import static_check
from .process import run
from .reporting import atomic_json, redact, tree_hash


SCHEMA_SCRIPT = '''import json,sys,tomllib
if sys.argv[2] != '-': sys.path.insert(0,sys.argv[2])
from harbor.models.task.config import TaskConfig
from harbor.models.task.task import Task
from importlib.metadata import version
from pathlib import Path
p=Path(sys.argv[1]); raw=tomllib.loads((p/'task.toml').read_text(encoding='utf-8'))
def known(raw,cls):
    if set(raw)-set(cls.model_fields): raise ValueError('Unknown Harbor metadata field')
known(raw,TaskConfig)
cfg=TaskConfig.model_validate(raw)
for key in ('task','agent','verifier','environment'):
    known(raw[key],type(getattr(cfg,key)))
known(raw['verifier']['environment'],type(cfg.verifier.environment))
if not Task.is_valid_dir(p): raise ValueError('Invalid Harbor task directory')
task=Task(p)
print(json.dumps({'version':version('harbor'),'schema':'PASS'}))
'''


class Validator:
    def __init__(self, config):
        self.config = config
        self.settings = config.validation
        self.docker = self.settings['docker_executable']

    def doctor(self):
        result = {'harbor': {'available': False}, 'docker': {'available': False}}
        python = self.settings['harbor_python']
        if python:
            try:
                # Only --version/--help inspection; never execute Harbor subcommands.
                entry = "import sys; sys.path.insert(0,sys.argv.pop(1)); from harbor.cli.main import app; app()"
                site = self.settings['harbor_site_packages'] or '-'
                probes = {}
                for args in (['--version'], ['--help'], ['task', '--help']):
                    proc = run([python, '-B', '-c', entry, site, *args], timeout=20, max_bytes=524288)
                    probes[' '.join(args)] = {'returncode': proc.returncode, 'output': redact(proc.stdout + proc.stderr)}
                result['harbor'] = {'available': all(v['returncode'] == 0 for v in probes.values()), 'probes': probes}
            except FactoryError as exc:
                result['harbor']['reason'] = str(exc)
        else:
            result['harbor']['reason'] = 'Configure harbor_python and optional harbor_site_packages; not installed here'
        try:
            proc = run([self.docker, 'version', '--format', '{{json .}}'], timeout=20)
            result['docker'] = {'available': proc.returncode == 0, 'version': redact(proc.stdout),
                                'reason': None if proc.returncode == 0 else 'Docker daemon or CLI unavailable'}
        except FactoryError as exc:
            result['docker']['reason'] = str(exc)
        return result

    def schema(self, package):
        python = self.settings['harbor_python']
        if not python:
            raise FactoryError('Harbor schema validation unavailable; configure an existing Harbor Python environment')
        proc = run([python, '-B', '-c', SCHEMA_SCRIPT, str(package), self.settings['harbor_site_packages'] or '-'],
                   timeout=20, max_bytes=262144)
        if proc.returncode:
            raise FactoryError('Installed Harbor schema validation failed; no benchmark was started')
        return json.loads(proc.stdout)

    def image_identity(self):
        proc = run([self.docker, 'image', 'inspect', self.settings['image'], '--format', '{{.Id}}'], timeout=20)
        if proc.returncode or not re.fullmatch(r'sha256:[a-f0-9]{64}', proc.stdout.strip()):
            raise FactoryError('Validation image must already exist locally; factory never pulls or installs dependencies')
        return proc.stdout.strip()

    def build(self, package, context, tag):
        directory = package / context
        proc = run([self.docker, 'build', '--pull=false', '--network', 'none', '--tag', tag,
                    '--file', str(directory / 'Dockerfile'), str(directory)],
                   timeout=self.settings['timeout'], max_bytes=self.settings['max_output_bytes'])
        if proc.returncode:
            raise FactoryError(f'{context} image build failed (no dependencies were installed by the factory)')
        inspect = run([self.docker, 'image', 'inspect', tag, '--format', '{{.Id}}'], timeout=15)
        if inspect.returncode or not re.fullmatch(r'sha256:[a-f0-9]{64}', inspect.stdout.strip()):
            raise FactoryError('Built image identity could not be established')
        return {'image_id': inspect.stdout.strip(), 'build_output': redact(proc.stdout + proc.stderr)}

    def container(self, package, work, image_id, reference=False, baked_tests=False):
        name = 'stem-factory-' + uuid.uuid4().hex
        for path in (package, work):
            if ',' in str(path):
                raise FactoryError('Docker bind paths cannot contain commas')
        argv = [self.docker, 'run', '--rm', '--pull', 'never', '--name', name,
                '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--pids-limit', '64', '--memory', '512m',
                '--cpus', '1', '--user', '65534:65534', '--ipc', 'none',
                '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',
                '--tmpfs', '/logs:rw,nosuid,nodev,noexec,size=16m,mode=1777',
                '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONHASHSEED=0', '--env', 'TZ=UTC',
                '--mount', f'type=bind,source={work},target=/work' + ('' if reference else ',readonly')]
        if reference or not baked_tests:
            argv += ['--mount', f'type=bind,source={package / ("solution" if reference else "tests")},target=/{"solution" if reference else "tests"},readonly']
        argv += [
                '--workdir', '/work', '--entrypoint', '/bin/bash', image_id,
                '/solution/solve.sh' if reference else '/tests/test.sh']
        try:
            return run(argv, timeout=self.settings['timeout'], max_bytes=self.settings['max_output_bytes'])
        finally:
            # Killing the client alone does not stop daemon-side containers.
            cleanup = run([self.docker, 'rm', '--force', name], timeout=15, max_bytes=65536)
            if cleanup.returncode and 'No such container' not in cleanup.stderr:
                raise FactoryError('Container cleanup failed; inspect Docker before resuming')

    def validate(self, package, report_path):
        package = Path(package).resolve()
        report = {'passed': False, 'package': str(package), 'checks': [], 'benchmark_executed': False,
                  'input_hash': tree_hash(package, exclude={'authoring/validation.json'})}
        tags = []
        try:
            report['static'] = static_check(package, self.settings['image'])
            if report['static'].get('profile') == 'manifest-v1':
                raise FactoryError('Manifest runtime execution needs a dedicated Harbor runner; this validator supports legacy Python packages only')
            report['harbor'] = self.schema(package)
            image_id = self.image_identity()
            report['image_id'] = image_id
            report['built_images'] = {}
            for context in ('environment', 'tests'):
                tag = 'stem-factory:' + uuid.uuid4().hex
                tags.append(tag)
                report['built_images'][context] = self.build(package, context, tag)
            if self.image_identity() != image_id:
                raise FactoryError('Base image tag changed during build; use an immutable digest')
            agent_image = report['built_images']['environment']['image_id']
            verifier_image = report['built_images']['tests']['image_id']
            evidence = json.loads((package / 'authoring/evidence.json').read_text(encoding='utf-8'))
            # Independent clean runs exercise the actual packaged solve.sh and test.sh.
            for index in range(2):
                with tempfile.TemporaryDirectory(prefix='stem-reference-') as folder:
                    work = Path(folder)
                    work.chmod(0o777)
                    setup = self.container(package, work, agent_image, reference=True)
                    if setup.returncode or {p.name for p in work.iterdir()} != {'task.py'}:
                        raise FactoryError('Reference setup failed or produced unexpected artifacts')
                    result = self.container(package, work, verifier_image, baked_tests=True)
                    self.record(report, f'reference-clean-{index + 1}', result, expect_pass=True)
            with tempfile.TemporaryDirectory(prefix='stem-baseline-') as folder:
                result = self.container(package, Path(folder), verifier_image, baked_tests=True)
                self.record(report, 'empty-start-must-fail', result, expect_pass=False, assertion_required=False)
            for index, mutant in enumerate(evidence['implementation']['mutants']):
                with tempfile.TemporaryDirectory(prefix='stem-mutant-') as folder:
                    work = Path(folder)
                    (work / 'task.py').write_text(mutant['code'], encoding='utf-8', newline='\n')
                    result = self.container(package, work, verifier_image, baked_tests=True)
                    self.record(report, f'mutant-{index + 1}', result, expect_pass=False, assertion_required=True)
            static_check(package, self.settings['image'])
            if tree_hash(package, exclude={'authoring/validation.json'}) != report['input_hash']:
                raise FactoryError('Package changed during validation')
            report['passed'] = True
        except (FactoryError, OSError, ValueError) as exc:
            report['error'] = redact(str(exc))
        finally:
            for tag in tags:
                try:
                    cleanup = run([self.docker, 'image', 'rm', tag], timeout=15, max_bytes=65536)
                    if cleanup.returncode and 'No such image' not in cleanup.stderr:
                        report.update(passed=False, error='Temporary build tag cleanup failed')
                except FactoryError:
                    report.update(passed=False, error='Temporary build tag cleanup failed')
            atomic_json(report_path, report)
        return report

    @staticmethod
    def record(report, name, result, expect_pass, assertion_required=False):
        output = result.stdout + result.stderr
        entry = {'name': name, 'returncode': result.returncode, 'elapsed': result.elapsed,
                 'output': redact(output)}
        report['checks'].append(entry)
        if expect_pass:
            counts = re.findall(r'Ran (\d+) tests?', output)
            ok = result.returncode == 0 and counts and int(counts[-1]) >= 8 and re.search(r'^OK\s*$', output, re.M)
        else:
            ok = result.returncode == 1 and re.search(r'^FAILED \(', output, re.M)
            if assertion_required:
                # A missing API/import error is not evidence of catching a conceptual mistake.
                ok = ok and re.search(r'FAILED \(failures=[1-9][0-9]*\)', output)
        if not ok:
            raise FactoryError(f'{name}: expected validation outcome not observed')
