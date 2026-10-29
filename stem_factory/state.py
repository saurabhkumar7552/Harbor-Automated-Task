"""Single-writer durable state and request journal with explicit uncertain-call handling."""
import json
import os
from pathlib import Path
import time
from .errors import BudgetError, FactoryError
from .reporting import atomic_json, digest, event


class RunLock:
    def __init__(self, root, recover=False):
        self.path = Path(root) / '.lock'
        self.recover = recover

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.recover:
            try:
                pid = int(self.path.read_text())
                os.kill(pid, 0)
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
                         'calls': 0, 'known_cost_usd': 0.0, 'unknown_cost_calls': 0, 'elapsed_seconds': 0.0}
        self.previous_elapsed = self.data['elapsed_seconds']

    def save(self):
        self.data['elapsed_seconds'] = self.previous_elapsed + time.monotonic() - self.started
        atomic_json(self.path, self.data)

    def remaining_time(self):
        return self.config.limits['max_run_seconds'] - self.previous_elapsed - (time.monotonic() - self.started)

    def reserve(self):
        limits, data = self.config.limits, self.data
        if self.remaining_time() <= 0:
            raise BudgetError('Run time budget exhausted')
        if data['calls'] >= limits['max_calls']:
            raise BudgetError('Model call budget exhausted')
        if data['unknown_cost_calls'] >= limits['max_unknown_cost_calls']:
            raise BudgetError('Unknown-cost call budget exhausted')
        if limits['max_cost_usd'] is not None and data['known_cost_usd'] >= limits['max_cost_usd']:
            raise BudgetError('Known-cost threshold exhausted; unknown costs may be additional')
        data['calls'] += 1
        data['unknown_cost_calls'] += 1
        self.save()  # Reserve before any external request, including failed/uncertain requests.


class Journal:
    def __init__(self, state, adapters, retry_uncertain=False):
        self.state = state
        self.adapters = adapters
        self.retry_uncertain = retry_uncertain

    def call(self, role_name, prompt, schema, key):
        from .contracts import validate
        from .reporting import no_secrets
        state = self.state
        directory = state.root / 'requests' / key
        identity = digest({'role': role_name, 'prompt': prompt, 'schema': schema})
        result_path = directory / 'result.json'
        request_path = directory / 'request.json'
        if result_path.exists():
            record = json.loads(result_path.read_text(encoding='utf-8'))
            if record['identity'] != identity:
                raise FactoryError('Cached request identity mismatch')
            if record.get('error'):
                raise FactoryError(record['error'])
            return validate(record['value'], schema)
        if request_path.exists() and not self.retry_uncertain:
            raise BudgetError('Interrupted request has unknown completion; inspect requests and use --retry-uncertain to authorize possible duplicate usage')
        no_secrets(prompt)
        if len(prompt.encode('utf-8')) > state.config.limits['max_prompt_bytes']:
            raise FactoryError('Prompt exceeds configured byte budget; reduce inventory/specification size')
        state.reserve()
        role = state.config.roles[role_name]
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(request_path, {'identity': identity, 'role': role_name, 'model': role.model,
                                  'adapter': role.adapter, 'prompt': prompt, 'schema': schema,
                                  'attempt_reserved': state.data['calls']})
        workspace = role.cwd or state.root / 'agent-work' / key
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            response = self.adapters[role_name].invoke(prompt, schema, workspace,
                                                        timeout=max(.01, state.remaining_time()))
            # Preserve full reviewer transcript, with secret redaction, even for malformed contracts.
            atomic_json(directory / 'transcript.json', {'stdout': response.transcript, 'stderr': response.stderr,
                                                        'usage': response.usage, 'cost_usd': response.cost_usd})
            no_secrets(json.dumps(response.value))
            value = validate(response.value, schema)
            atomic_json(result_path, {'identity': identity, 'value': value})
            if response.cost_usd is not None:
                state.data['known_cost_usd'] += response.cost_usd
                state.data['unknown_cost_calls'] -= 1
            state.save()
            event(state.root, 'model_result', request=key, role=role_name)
            return value
        except FactoryError as exc:
            transport = workspace / 'transport.json'
            if transport.exists():
                atomic_json(directory / 'transcript.json', json.loads(transport.read_text(encoding='utf-8')))
            atomic_json(result_path, {'identity': identity, 'error': str(exc)})
            event(state.root, 'model_failure', request=key, role=role_name, error=str(exc))
            raise
