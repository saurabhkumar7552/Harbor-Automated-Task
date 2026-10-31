"""Single-writer durable state and request journal with explicit uncertain-call handling."""
import json
import os
from pathlib import Path
import time
from .errors import FactoryError, RunHaltError
from .config import require_live_execution
from .reporting import atomic_json, digest, event


def check_process_alive(pid):
    """Query process existence without sending a Windows termination signal."""
    if pid <= 0:
        raise ValueError('Lock PID must be positive')
    if os.name != 'nt':
        os.kill(pid, 0)
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID is not present.
            raise ProcessLookupError(pid)
        raise ctypes.WinError(error)
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value != 259:  # STILL_ACTIVE
            raise ProcessLookupError(pid)
    finally:
        kernel.CloseHandle(handle)


class RunLock:
    def __init__(self, root, recover=False):
        self.path = Path(root) / '.lock'
        self.recover = recover

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.recover:
            try:
                pid = int(self.path.read_text())
                check_process_alive(pid)
            except ProcessLookupError:
                self.path.unlink()
            except (ValueError, OSError):
                raise FactoryError('Cannot establish stale lock; investigate before removing manually')
            else:
                raise FactoryError('Existing run lock belongs to an active process')
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise FactoryError('Run is locked; use --recover-lock only for a dead prior process') from exc
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *args):
        os.close(self.fd)
        self.path.unlink(missing_ok=True)


class State:
    def __init__(self, config):
        self.config = config
        self.root = config.output
        self.path = self.root / 'state.json'
        self.started = time.monotonic()
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data['fingerprint'] != config.fingerprint:
                raise FactoryError('Configuration changed; use a new output directory to preserve provenance')
        else:
            self.data = {'version': 1, 'fingerprint': config.fingerprint, 'candidates': [],
                         'calls': 0, 'elapsed_seconds': 0.0}
        self.data.setdefault('calls', 0)
        self.data.setdefault('elapsed_seconds', 0.0)
        self.data.pop('known_cost_usd', None)
        self.data.pop('unknown_cost_calls', None)
        self.previous_elapsed = self.data['elapsed_seconds']

    def save(self):
        self.data['elapsed_seconds'] = self.previous_elapsed + time.monotonic() - self.started
        atomic_json(self.path, self.data)

    def reserve(self):
        self.data['calls'] += 1
        self.save()  # Reserve before any external request, including failed/uncertain requests.


class Journal:
    def __init__(self, state, adapters, retry_uncertain=False, *, retry_account_errors=False):
        self.state = state
        self.adapters = adapters
        self.retry_uncertain = retry_uncertain
        self.retry_account_errors = retry_account_errors

    def call(self, role_name, prompt, schema, key):
        from .contracts import validate
        from .reporting import no_secrets
        require_live_execution(self.state.config)
        state = self.state
        directory = state.root / 'requests' / key
        identity = digest({'role': role_name, 'prompt': prompt, 'schema': schema})
        result_path = directory / 'result.json'
        request_path = directory / 'request.json'
        account_retry = False
        if result_path.exists():
            record = json.loads(result_path.read_text(encoding='utf-8'))
            if record['identity'] != identity:
                raise RunHaltError('Cached request identity mismatch; use a fresh run after changing prompts or schemas')
            if record.get('error'):
                account_error = record['error'].startswith((
                    'Authentication prevented a model call', 'Provider usage limit prevented a model call'))
                if account_error and self.retry_account_errors:
                    if state.config.roles[role_name].cwd is not None:
                        raise RunHaltError('Account retries require a fresh managed workspace; configure a new run without role.cwd')
                    # Preserve the failed attempt before marking its result retry-pending.
                    attempt = directory / 'attempts' / f'before-retry-{state.data["calls"] + 1:06d}'
                    for filename in ('request.json', 'result.json', 'transcript.json'):
                        source = directory / filename
                        if source.exists():
                            atomic_json(attempt / filename, json.loads(source.read_text(encoding='utf-8')))
                    atomic_json(result_path, {'identity': identity, 'retry_pending': True})
                    event(state.root, 'account_retry_authorized', request=key, evidence=str(attempt))
                    account_retry = True
                elif record.get('halted') or account_error or record['error'].startswith('Docker cleanup is uncertain'):
                    raise RunHaltError(record['error'])
                else:
                    raise FactoryError(record['error'])
            elif not record.get('retry_pending'):
                return validate(record['value'], schema)
        uncertain = request_path.exists() or result_path.exists()
        if uncertain and not self.retry_uncertain and not account_retry:
            raise RunHaltError('Interrupted request has unknown completion; inspect requests and use --retry-uncertain to authorize possible duplicate usage')
        no_secrets(prompt)
        state.reserve()
        role = state.config.roles[role_name]
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(request_path, {'identity': identity, 'role': role_name, 'model': role.model,
                                  'adapter': role.adapter, 'prompt': prompt, 'schema': schema,
                                  'attempt_reserved': state.data['calls']})
        workspace = role.cwd or state.root / 'agent-work' / key
        if uncertain and role.cwd is None:
            workspace = state.root / 'agent-work' / (key + f'-retry-{state.data["calls"]}')
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            response = self.adapters[role_name].invoke(prompt, schema, workspace,
                                                        timeout=role.timeout)
            # Preserve full reviewer transcript, with secret redaction, even for malformed contracts.
            atomic_json(directory / 'transcript.json', {'stdout': response.transcript, 'stderr': response.stderr,
                                                        'usage': response.usage, 'cost_usd': response.cost_usd})
            no_secrets(json.dumps(response.value))
            value = validate(response.value, schema)
            atomic_json(result_path, {'identity': identity, 'value': value})
            state.save()
            event(state.root, 'model_result', request=key, role=role_name)
            return value
        except FactoryError as exc:
            transport = workspace / 'transport.json'
            if transport.exists():
                atomic_json(directory / 'transcript.json', json.loads(transport.read_text(encoding='utf-8')))
            atomic_json(result_path, {'identity': identity, 'error': str(exc),
                                     'halted': isinstance(exc, RunHaltError)})
            event(state.root, 'model_failure', request=key, role=role_name, error=str(exc))
            raise
