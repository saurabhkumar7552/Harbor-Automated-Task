from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
from ..contracts import loads
from ..errors import ConfigError, FactoryError
from ..process import run, ProcessFailure
from ..reporting import atomic_json


@dataclass
class Response:
    value: dict
    transcript: str
    stderr: str
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None


class Adapter(ABC):
    help_args = ['--help']
    required_flags = ()
    allowed_args = {}  # flag -> number of values. No permission/tool overrides.
    requires_launcher = False

    def __init__(self, role):
        self.role = role
        self.help = None

    def inspect(self):
        executable = shutil.which(self.role.executable)
        if not executable and Path(self.role.executable).is_file():
            executable = self.role.executable
        if not executable:
            return {'available': False, 'reason': 'executable unavailable'}
        version = run([executable, '--version'], timeout=15, max_bytes=262144)
        result = run([executable, *self.help_args], timeout=15, max_bytes=524288)
        if version.returncode or result.returncode:
            return {'available': False, 'reason': 'version/help probe failed'}
        self.help = result.stdout + result.stderr
        missing = [flag for flag in self.required_flags if flag not in self.help]
        return {'available': not missing, 'version': version.stdout.strip(), 'missing_flags': missing,
                'help': self.help, 'launcher_required': self.requires_launcher}

    def preflight(self):
        info = self.inspect()
        if not info['available']:
            raise ConfigError(f'{self.role.adapter}: unavailable or incompatible CLI interface')
        if self.requires_launcher and not self.role.launcher:
            raise ConfigError(f'{self.role.adapter}: configure an audited isolation launcher; native tool denial is not guaranteed')
        if self.role.launcher and not (shutil.which(self.role.launcher[0]) or Path(self.role.launcher[0]).is_file()):
            raise ConfigError('Isolation launcher unavailable')
        self.check_args()
        self.check_effort()

    def check_args(self):
        index = 0
        while index < len(self.role.args):
            flag = self.role.args[index]
            count = self.allowed_args.get(flag)
            if count is None or flag not in self.help or index + count >= len(self.role.args):
                raise ConfigError(f'{self.role.adapter}: unsupported provider argument')
            if any(v.startswith('-') for v in self.role.args[index+1:index+1+count]):
                raise ConfigError('Provider argument value cannot be a flag')
            index += 1 + count

    def check_effort(self):
        if self.role.effort:
            raise ConfigError(f'{self.role.adapter}: effort is unsupported by this adapter/interface')

    @abstractmethod
    def command(self, schema, workspace):
        """Return argv; prompt is always supplied on stdin."""

    @abstractmethod
    def parse(self, text):
        """Decode the provider envelope explicitly; reject ambiguous output."""

    def invoke(self, prompt, schema, workspace, timeout=None):
        argv = [*self.role.launcher, *self.command(schema, workspace)]
        env = os.environ.copy()
        # Child CLIs retain their normal auth; prompts/config never receive secret values.
        try:
            result = run(argv, stdin=prompt, cwd=workspace,
                         timeout=min(self.role.timeout, timeout or self.role.timeout),
                         max_bytes=self.role.max_output_bytes, env=env)
        except ProcessFailure as exc:
            atomic_json(workspace / 'transport.json', {'stdout': exc.stdout, 'stderr': exc.stderr,
                                                      'incomplete': True, 'error': str(exc)})
            raise
        atomic_json(workspace / 'transport.json', {'stdout': result.stdout, 'stderr': result.stderr,
                                                  'returncode': result.returncode})
        if result.returncode:
            raise FactoryError(f'{self.role.adapter}: CLI exited unsuccessfully (output omitted)')
        response = self.parse(result.stdout)
        response.transcript, response.stderr = result.stdout, result.stderr
        return response


def response_value(text):
    if not isinstance(text, str):
        raise FactoryError('CLI JSON payload must be text')
    value = loads(text)
    if not isinstance(value, dict):
        raise FactoryError('CLI result is not a JSON object')
    return value
