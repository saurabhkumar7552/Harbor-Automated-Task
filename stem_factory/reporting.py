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
        return {'accepted': 0, 'status': 'not-started'}
    state = json.loads(path.read_text(encoding='utf-8'))
    def package_path(candidate):
        if candidate.get('status') == 'accepted' and candidate.get('task_id'):
            return str(root / 'accepted' / candidate['task_id'])
        if candidate.get('packaging_status') == 'package_failed':
            name = f"candidate-{candidate['index']:03d}-revision-{candidate.get('revision', 0):02d}"
            fingerprint = candidate.get('environment_fingerprint')
            if fingerprint:
                name += f'-env-{fingerprint[:12]}'
            archive = root / 'failed' / name
            return str(archive) if archive.is_dir() else None
        return None

    offline_valid = sum(c.get('package_validation_status') == 'offline_valid'
                        for c in state['candidates'])
    return {'accepted': sum(c['status'] == 'accepted' for c in state['candidates']),
            'offline_valid_packages': offline_valid,
            'acceptance_basis': 'Offline package validation; reviewer approval is reported separately.',
            'halted': state.get('halted'),
            'candidates': [{'task_id': c.get('task_id'), 'status': c['status'],
                            'authoring_status': c.get('authoring_status', 'legacy_unknown'),
                            'review_status': c.get('review_status', 'legacy_unknown'),
                            'repairs_performed': c.get('revision', 0),
                            'revision_limit_reached': c.get('revision_limit_reached', False),
                            'packaging_status': c.get('packaging_status', 'legacy_unknown'),
                            'package_validation_status': c.get('package_validation_status', 'legacy_unknown'),
                            'harbor_execution_status': c.get('harbor_execution_status', 'not_run'),
                            'environment_fingerprint': c.get('environment_fingerprint'),
                            'review_findings': c.get('review', {}).get('findings', []),
                            'final_findings': c.get('final_findings', {}),
                            'validation_report': c.get('validation_report'),
                            'package_path': package_path(c),
                            'reason': c.get('reason')}
                           for c in state['candidates']],
            'calls_reserved': state['calls'],
            'live_model_calls_reserved': state['calls'],
            'paid_operation_status': 'unknown_provider_billing' if state['calls'] else 'no_model_requests',
            'elapsed_seconds': state['elapsed_seconds'],
            'reviews': str(root / 'requests'), 'validation': str(root / 'validation'),
            'packages': str(root / 'accepted'),
            'note': 'Review gates are independent prompts, not evidence of statistical independence. No Harbor benchmark is executed.'}
