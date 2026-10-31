"""Opt-in Docker confinement; permits tools and standard guest CLI authentication.

This transport does not implement or claim the separate strict-isolation contract.
All containers are disposable; daemon-side cleanup is verified after every attempt.
"""
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from .base import Adapter
from .codex import CodexAdapter
from ..config import require_live_execution
from ..errors import ConfigError, FactoryError, RunHaltError
from ..process import run, ProcessFailure
from ..reporting import atomic_json, no_secrets
from .provider_failures import stop_if_account_blocked


def assessment(config):
    settings = config.generation['docker']
    blockers = []
    if settings['image'] is None:
        blockers.append('Configure an existing immutable Linux Codex image ID; no image is built or pulled automatically')
    if settings['auth_volume'] is None:
        blockers.append('Configure an existing dedicated Codex authentication volume; no credentials are copied or login performed')
    if (config.output / 'docker-cleanup-blocked.json').exists():
        blockers.append('A previous Docker cleanup is uncertain; operator investigation is required before retry')
    return {'mode': 'docker', 'tools': 'permitted inside the container',
            'network': 'Docker bridge; not provider-only egress',
            'authentication': 'standard CLI credential volume, readable by guest tools',
            'confinement': 'unverified until runtime testing', 'ready_for_execution': False,
            'blockers': blockers}


class DockerCodexAdapter(Adapter):
    def __init__(self, config, role, health=None):
        if not config.generation or config.generation.get('transport') != 'docker':
            raise ConfigError('Docker adapter requires explicitly selected docker generation transport')
        super().__init__(role)
        self.config = config
        self.settings = config.generation['docker']
        self.docker = config.validation['docker_executable']
        self.health = health if health is not None else {'cleanup_failed': False}

    def inspect(self):
        # Static only; never start Docker or a container as a side effect of inspection.
        return {**assessment(self.config), 'available': False}

    def command(self, schema, workspace):
        raise ConfigError('Docker commands require the managed create/start/cleanup lifecycle')

    def parse(self, text):
        return CodexAdapter.parse(self, text)

    def check_effort(self):
        CodexAdapter.check_effort(self)

    def _configured(self, probe=False):
        if not probe:
            require_live_execution(self.config)
            from ..generation import require_entitlements
            require_entitlements(self.config)
        if self.health['cleanup_failed'] or (self.config.output / 'docker-cleanup-blocked.json').exists():
            raise RunHaltError('Docker cleanup is uncertain; further requests are blocked until operator investigation')
        blockers = []
        if self.settings['image'] is None:
            blockers.append('Configure an existing immutable Linux Codex image ID; no image is built or pulled automatically')
        if not probe and self.settings['auth_volume'] is None:
            blockers.append('Configure an existing dedicated Codex authentication volume; no credentials are copied or login performed')
        if blockers:
            raise ConfigError('; '.join(blockers))
        self.check_effort()

    def _metadata(self, timeout=60, probe=False):
        self._configured(probe=probe)
        deadline = time.monotonic() + timeout
        def query(args):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FactoryError('Docker metadata command timed out')
            return run([self.docker, *args], timeout=min(15, remaining), max_bytes=65536)
        # Bind mounts must refer to this host, not an accidentally selected remote daemon.
        host = os.environ.get('DOCKER_HOST')
        if not host or os.environ.get('DOCKER_CONTEXT'):
            context = query(['context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'])
            if context.returncode:
                raise ConfigError('Docker context endpoint could not be established')
            host = context.stdout.strip()
        if not host.startswith(('npipe://', 'unix:///')):
            raise ConfigError('Docker model transport requires a local daemon endpoint')
        server = query(['version', '--format', '{{.Server.Os}}'])
        if server.returncode or server.stdout.strip() != 'linux':
            raise ConfigError('Docker requires a reachable Linux daemon; no service is started automatically')
        image = query(['image', 'inspect', self.settings['image'], '--format', '{{.Id}} {{.Os}}'])
        if image.returncode or image.stdout.strip() != self.settings['image'] + ' linux':
            raise ConfigError('Pinned Linux Codex image is unavailable; no build or pull is attempted')
        if not probe:
            volume = query(['volume', 'inspect', self.settings['auth_volume'],
                            '--format', '{{.Driver}} {{if .Options}}custom{{else}}plain{{end}}'])
            if volume.returncode or volume.stdout.strip() != 'local plain':
                raise ConfigError('Dedicated local Codex credential volume is unavailable; no volume is created')

    def preflight(self):
        self._metadata()
        self._probe_cli()

    def check_image(self):
        """Explicit non-inference health operation, also usable with live disabled."""
        self._metadata(probe=True)
        version = self._probe_cli()
        return {'image': self.settings['image'], 'codex_version': version,
                'cli_compatible': True, 'authentication': 'not checked; credentials not mounted',
                'network': 'none', 'inference_calls': 0, 'ready_for_live_generation': False,
                'note': 'CLI health only; adversarial isolation and authenticated inference remain unverified'}

    def _probe_cli(self):
        # Offline and credential-free, either explicit health or enabled live preflight.
        version = self._execute(['--version'], probe=True)
        help_result = self._execute(['exec', '--help'], probe=True)
        if version.returncode or not re.fullmatch(r'codex-cli \d+\.\d+\.\d+\s*', version.stdout.strip()):
            raise ConfigError('Pinned image does not provide a compatible Codex CLI')
        if help_result.returncode or any(flag not in help_result.stdout + help_result.stderr
                                         for flag in CodexAdapter.required_flags):
            raise ConfigError('Pinned Codex image lacks the required structured CLI interface')
        return version.stdout.strip()

    def _workspace(self, workspace):
        workspace = Path(workspace)
        # Check spelling and ancestors before resolving indirection.
        for path in (workspace, *workspace.parents):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ConfigError('Docker request workspace must not use symlinks or junctions')
        workspace = workspace.resolve(strict=True)
        root = (self.config.output / 'agent-work').resolve()
        if workspace == root or not workspace.is_relative_to(root) or not workspace.is_dir():
            raise ConfigError('Docker workspace must be a request directory under output/agent-work')
        if ',' in str(workspace):
            raise ConfigError('Docker bind paths cannot contain commas')
        # Schema is opened with exclusive creation in invoke(); reject other material
        # instead of exposing old transcripts, sibling state or attacker-created links.
        if any(workspace.iterdir()):
            raise ConfigError('Docker request workspace must be empty; use a fresh request directory')
        return workspace

    def _execute(self, args, *, workspace=None, prompt='', network='none', timeout=20, probe=False):
        if probe and (args not in (['--version'], ['exec', '--help']) or workspace is not None or prompt or network != 'none'):
            raise ConfigError('Image health permits only credential-free, offline version/help probes')
        self._configured(probe=probe)
        if timeout <= 0:
            raise FactoryError('Docker request timed out')
        name = 'stem-model-' + uuid.uuid4().hex
        argv = [self.docker, 'create', '--name', name, '--pull', 'never', '--interactive', '--init',
                '--network', network, '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--pids-limit', str(self.settings['pids_limit']),
                '--memory', str(self.settings['memory_mb']) + 'm', '--cpus', str(self.settings['cpus']),
                '--user', '1000:1000', '--ipc', 'none',
                '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777',
                '--tmpfs', '/home/node:rw,nosuid,nodev,noexec,size=64m,uid=1000,gid=1000,mode=0700',
                '--env', 'HOME=/home/node', '--env', 'CODEX_SQLITE_HOME=/tmp',
                '--env', 'CODEX_HOME=' + ('/codex-home' if workspace else '/home/node'),
                '--workdir', '/work', '--entrypoint', '/usr/bin/timeout']
        if workspace is not None:
            argv += ['--mount', f'type=bind,source={workspace},target=/work,readonly',
                     '--mount', f'type=volume,source={self.settings["auth_volume"]},target=/codex-home,volume-nocopy']
        # A guest watchdog bounds work even if the host Docker client disappears.
        # Its actual enforcement under adversarial tools still needs runtime audit.
        argv += [self.settings['image'], '--signal=TERM', '--kill-after=5s',
                 str(math.ceil(timeout)) + 's', 'codex', *args]
        deadline = time.monotonic() + timeout
        try:
            created = run(argv, timeout=min(timeout, 15), max_bytes=65536)
            if created.returncode:
                raise FactoryError('Docker request container creation failed; no host fallback')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FactoryError('Docker request timed out before start')
            return run([self.docker, 'start', '--attach', '--interactive', name], stdin=prompt,
                       timeout=remaining, max_bytes=self.role.max_output_bytes)
        finally:
            # Kill the daemon-side container even when the CLI times out, overflows,
            # loses its pipe or receives cancellation. Killing its client is insufficient.
            try:
                run([self.docker, 'rm', '--force', '--volumes', name], timeout=15, max_bytes=65536)
                remaining = run([self.docker, 'container', 'ls', '--all', '--quiet',
                                 '--filter', 'name=^/' + name + '$'], timeout=15, max_bytes=65536)
                if remaining.returncode or remaining.stdout.strip():
                    raise FactoryError('Container removal could not be confirmed')
            except (FactoryError, OSError):
                self.health['cleanup_failed'] = True
                try:
                    atomic_json(self.config.output / 'docker-cleanup-blocked.json', {
                        'container': name, 'reason': 'Removal not confirmed; investigate before restarting'})
                except OSError:
                    # The current process remains blocked even if persistence fails.
                    pass
                raise RunHaltError('Docker cleanup is uncertain; stopping the run until operator investigation') from None

    def invoke(self, prompt, schema, workspace, timeout=None):
        limit = min(self.role.timeout, timeout if timeout is not None else self.role.timeout)
        deadline = time.monotonic() + limit
        self._metadata(timeout=limit)  # Disabled/missing runtime fails before schema or model call.
        no_secrets(prompt)
        workspace = self._workspace(workspace)
        with (workspace / 'response-schema.json').open('x', encoding='utf-8') as stream:
            json.dump(schema, stream)
        args = ['exec', '--ignore-user-config', '--ignore-rules', '--sandbox', 'read-only',
                '--skip-git-repo-check', '--ephemeral', '--json', '--model', self.role.model,
                '--output-schema', '/work/response-schema.json']
        if self.role.effort:
            args += ['-c', 'model_reasoning_effort=' + json.dumps(self.role.effort)]
        args += ['-']
        try:
            result = self._execute(args, workspace=workspace, prompt=prompt, network='bridge',
                                   timeout=deadline - time.monotonic())
        except ProcessFailure as exc:
            atomic_json(workspace / 'transport.json', {'stdout': exc.stdout, 'stderr': exc.stderr})
            stop_if_account_blocked(exc.stdout + '\n' + exc.stderr)
            raise
        atomic_json(workspace / 'transport.json', {'stdout': result.stdout, 'stderr': result.stderr,
                                                  'returncode': result.returncode})
        if result.returncode:
            stop_if_account_blocked(result.stdout + '\n' + result.stderr)
            raise FactoryError('Containerized Codex exited unsuccessfully; check authentication/runtime, no fallback')
        response = self.parse(result.stdout)
        response.transcript, response.stderr = result.stdout, result.stderr
        return response
