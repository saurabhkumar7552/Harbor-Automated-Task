import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from .errors import FactoryError


def redact(text):
    for name, value in os.environ.items():
        if re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', name, re.I) and len(value) >= 8:
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'(?i)bearer\s+[a-z0-9._-]+', 'Bearer [REDACTED]', text)
    return re.sub(r'\bsk-[a-zA-Z0-9_-]{16,}', '[REDACTED]', text)


def no_secrets(text):
    if redact(text) != text:
        raise FactoryError('Sensitive value detected; artifact rejected without logging its contents')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = redact(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)) + '\n'
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def tree_hash(path, exclude=()):
    result = {}
    for file in sorted(Path(path).rglob('*')):
        if file.is_symlink():
            raise FactoryError('Symlink in package tree')
        if file.is_file():
            relative = file.relative_to(path).as_posix()
            if relative not in exclude:
                result[relative] = hashlib.sha256(file.read_bytes()).hexdigest()
    return digest(result)


def event(root, kind, **data):
    entry = {'time': datetime.now(timezone.utc).isoformat(), 'kind': kind, **data}
    with (Path(root) / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(redact(json.dumps(entry, ensure_ascii=False)) + '\n')


def report(root):
    root = Path(root)
    path = root / 'state.json'
    if not path.exists():
        return {'accepted': 0, 'status': 'not-started', 'cost': 'unknown; no recorded calls'}
    state = json.loads(path.read_text(encoding='utf-8'))
    return {'accepted': sum(c['status'] == 'accepted' for c in state['candidates']),
            'halted': state.get('halted'),
            'candidates': [{'task_id': c.get('task_id'), 'status': c['status'], 'reason': c.get('reason')}
                           for c in state['candidates']],
            'calls_reserved': state['calls'], 'known_cost_usd': state['known_cost_usd'],
            'unknown_cost_calls': state['unknown_cost_calls'],
            'cost_complete': state['unknown_cost_calls'] == 0,
            'elapsed_seconds': state['elapsed_seconds'],
            'reviews': str(root / 'requests'), 'validation': str(root / 'validation'),
            'packages': str(root / 'accepted'),
            'note': 'Review gates are independent prompts, not evidence of statistical independence. No Harbor benchmark is executed.'}
