"""Strict, static Windows launcher assessment. This module starts no processes.

Review pins are operator trust decisions, not declarations supplied by a launcher.
None are provisioned. Even a matching reviewed record cannot establish current OS
enforcement: confined health/transport is deliberately unavailable in this patch.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import platform
import re
import stat
import struct

from .contracts import loads
from .errors import ConfigError, FactoryError
from .reporting import no_secrets


# No enrollment API or model-writable trust source. Future enrollment needs a
# separately reviewed operator trust mechanism; tests replace this empty mapping.
TRUSTED_REVIEWS = {}
CONTROLS = frozenset(('filesystem', 'process', 'tools', 'network', 'workspace',
                      'authentication', 'environment', 'cleanup', 'path_mapping',
                      'resources', 'discovery', 'deployment_permissions'))
HEALTH_BLOCKER = 'Confined health and policy enforcement are unverified; strict execution is unavailable in this patch'


def _fields(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ConfigError('Incomplete or unknown launcher evidence fields')


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 8192 or '\x00' in value:
        raise ConfigError('Invalid launcher evidence text')


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ConfigError('Invalid launcher evidence digest')


def local_path(value, forbidden_roots=()):
    """Reject indirection and unknown metadata before reading candidate content."""
    value = str(value)
    if (os.name != 'nt' or not re.match(r'^[A-Za-z]:[\\/]', value)
            or ':' in value[2:] or '\x00' in value
            or any(p in ('.', '..') for p in re.split(r'[\\/]', value)[1:])):
        raise ConfigError('Strict isolation requires an absolute local Windows path without traversal or streams')
    path = Path(value)
    try:
        for part in (path, *path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ConfigError('Reparse points are unsupported for isolation artifacts')
        canonical = path.resolve(strict=True)
        for root in forbidden_roots:
            if canonical.is_relative_to(Path(root).resolve()):
                raise ConfigError('Isolation artifacts must be outside mutable task/output directories')
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ConfigError('Isolation artifact must be a regular file')
        return canonical
    except OSError as exc:
        raise ConfigError('Isolation artifact is missing or metadata is inaccessible') from exc


def _file_digest(path):
    try:
        if path.stat().st_size > 536870912:
            raise ConfigError('Isolation artifact exceeds size limit')
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    except OSError as exc:
        raise ConfigError('Isolation artifact cannot be read') from exc


def _read_document(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            raise ConfigError('Isolation document exceeds size limit')
        text = raw.decode('utf-8-sig')
        no_secrets(text)
        return raw, text
    except (OSError, UnicodeError) as exc:
        raise ConfigError('Isolation document cannot be read as bounded UTF-8') from exc


def evidence_fingerprint(role, forbidden_roots=()):
    """Hash evidence bytes, not just its path, into generation run provenance.

    Referenced artifact digests are part of those bytes; their actual contents are
    compared afresh at assessment. Invalid references remain dry-run blockers.
    """
    if role.launcher_evidence is None:
        return None
    try:
        path = local_path(role.launcher_evidence, forbidden_roots)
        raw, _ = _read_document(path)
        return hashlib.sha256(raw).hexdigest()
    except FactoryError:
        return 'unavailable'


def _windows_binary_type(path):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    query = kernel.GetBinaryTypeW
    query.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
    query.restype = wintypes.BOOL
    result = wintypes.DWORD()
    if not query(str(path), ctypes.byref(result)) or result.value != 6:
        raise ConfigError('Unsupported Windows executable type')


def inspect_native_executable(value, forbidden_roots=()):
    path = local_path(value, forbidden_roots)
    if path.suffix.casefold() != '.exe' or path.name.casefold() in {
        'cmd.exe', 'powershell.exe', 'pwsh.exe', 'wsl.exe', 'docker.exe',
        'python.exe', 'python3.exe', 'rundll32.exe', 'cscript.exe', 'wscript.exe'}:
        raise ConfigError('Strict isolation requires a reviewed native executable, not a wrapper')
    try:
        with path.open('rb') as stream:
            header = stream.read(64)
            if len(header) != 64 or header[:2] != b'MZ':
                raise ConfigError('Invalid native executable header')
            offset = struct.unpack_from('<I', header, 60)[0]
            if not 64 <= offset <= 1048576:
                raise ConfigError('Invalid native executable header offset')
            stream.seek(offset)
            pe = stream.read(26)
        if len(pe) != 26 or pe[:4] != b'PE\0\0':
            raise ConfigError('Invalid PE executable')
        machine = struct.unpack_from('<H', pe, 4)[0]
        flags = struct.unpack_from('<H', pe, 22)[0]
        if not flags & 2 or flags & 0x2000 or struct.unpack_from('<H', pe, 24)[0] != 0x20b:
            raise ConfigError('DLL or unsupported executable format')
        architecture = {0x8664: 'amd64', 0xaa64: 'arm64'}.get(machine)
        native = {'amd64': 'amd64', 'x86_64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine().casefold())
        if not architecture or architecture != native:
            raise ConfigError('Unsupported executable architecture')
        _windows_binary_type(path)  # Read-only metadata API; never executes the file.
        info = path.stat()
        if not info.st_ino:
            raise ConfigError('Executable file identity unavailable')
        return {'path': str(path), 'sha256': _file_digest(path),
                'file_identity': f'{info.st_dev}:{info.st_ino}', 'architecture': architecture}
    except OSError as exc:
        raise ConfigError('Executable metadata unavailable') from exc


def _document_reference(reference, forbidden_roots):
    _fields(reference, ('path', 'sha256'))
    _digest(reference['sha256'])
    path = local_path(reference['path'], forbidden_roots)
    raw, _ = _read_document(path)
    if hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise ConfigError('Reviewed document changed or mismatched')
    return path


def load_review(role, forbidden_roots=()):
    if role.launcher_evidence is None:
        raise ConfigError('Launcher evidence is missing')
    path = local_path(role.launcher_evidence, forbidden_roots)
    raw, text = _read_document(path)
    record = loads(text)
    _fields(record, ('version', 'launcher', 'codex', 'policy', 'dependencies', 'contract',
                     'controls', 'audit', 'runtime_binding'))
    if type(record['version']) is not int or record['version'] != 1:
        raise ConfigError('Unsupported launcher evidence version')
    audit = record['audit']
    _fields(audit, ('reviewer', 'decision', 'reviewed_at', 'expires_at', 'scope',
                    'review_document', 'negative_tests', 'limitations', 'revalidation_triggers'))
    for key in ('reviewer', 'decision', 'scope', 'limitations'):
        _text(audit[key])
    try:
        reviewed, expires = (datetime.fromisoformat(audit[k]) for k in ('reviewed_at', 'expires_at'))
        now = datetime.now(timezone.utc)
        if reviewed.tzinfo is None or expires.tzinfo is None or not reviewed <= now < expires:
            raise ValueError
    except (TypeError, ValueError):
        raise ConfigError('Launcher review dates are invalid or expired') from None
    if audit['decision'] != 'approved' or audit['scope'] != 'codex-generation-isolation':
        raise ConfigError('Review does not approve the required isolation scope')
    triggers = audit['revalidation_triggers']
    if not isinstance(triggers, list) or not triggers or len(triggers) > 32:
        raise ConfigError('Review must specify revalidation triggers')
    for trigger in triggers:
        _text(trigger)
    # A review cannot authorize itself. Independent pins are intentionally absent
    # from production. Even a trusted reference never establishes live confinement.
    trust = TRUSTED_REVIEWS.get(hashlib.sha256(raw).hexdigest())
    expected = {'reviewer': audit['reviewer'], 'review_document': audit['review_document'],
                'policy': record['policy'], 'scope': audit['scope']}
    if trust != expected:
        raise ConfigError('Launcher evidence has no independently approved trust record')
    return record


def validate_launch_contract(role, review, forbidden_roots=()):
    for key, configured in (('launcher', role.launcher[0] if role.launcher else ''), ('codex', role.executable)):
        entry = review[key]
        _fields(entry, ('path', 'sha256', 'file_identity', 'architecture', 'version', 'publisher', 'provenance'))
        for value in entry.values():
            _text(value)
        _digest(entry['sha256'])
        actual = inspect_native_executable(configured, forbidden_roots)
        if any(actual[k] != entry[k] for k in actual):
            raise ConfigError('Reviewed executable changed or mismatched')
    policy = review['policy']
    _fields(policy, ('path', 'sha256', 'version'))
    _text(policy['version'])
    _document_reference({k: policy[k] for k in ('path', 'sha256')}, forbidden_roots)
    dependencies = review['dependencies']
    if not isinstance(dependencies, list) or len(dependencies) > 128:
        raise ConfigError('Invalid dependency evidence')
    for dependency in dependencies:
        _fields(dependency, ('path', 'sha256'))
        _digest(dependency['sha256'])
        if _file_digest(local_path(dependency['path'], forbidden_roots)) != dependency['sha256']:
            raise ConfigError('Reviewed dependency changed or mismatched')
    contract = review['contract']
    _fields(contract, ('prefix', 'workspace', 'schema', 'argument_grammar', 'dependency_search'))
    if (not isinstance(contract['prefix'], list) or any(not isinstance(v, str) or '\x00' in v for v in contract['prefix'])
            or tuple(contract['prefix']) != role.launcher or len(role.launcher) < 3
            or role.launcher[-1] != '--' or policy['path'] not in role.launcher[1:-1]):
        raise ConfigError('Launcher prefix differs from reviewed policy/argument contract')
    if contract['workspace'] != 'fresh-request-only' or contract['schema'] != 'canonical-windows-path':
        raise ConfigError('Unsupported workspace/schema mapping')
    for key in ('argument_grammar', 'dependency_search'):
        _text(contract[key])
    _fields(review['controls'], CONTROLS)
    for value in review['controls'].values():
        _fields(value, ('mechanism', 'review_reference', 'negative_test_reference'))
        for text in value.values():
            _text(text)
    for key in ('review_document', 'negative_tests'):
        _document_reference(review['audit'][key], forbidden_roots)
    _fields(review['runtime_binding'], ('mechanism', 'independent_observer', 'policy_version', 'phase'))
    for text in review['runtime_binding'].values():
        _text(text)
    if review['runtime_binding']['policy_version'] != policy['version'] or review['runtime_binding']['phase'] != 'before-prompt':
        raise ConfigError('Runtime policy binding does not match reviewed policy')


def assess_isolation(role, forbidden_roots=()):
    result = {'host_artifacts': 'not_checked', 'static_evidence': 'invalid',
              'launcher_configured': bool(role.launcher),
              'evidence_configured': role.launcher_evidence is not None,
              'audit': 'unverified', 'isolated_health': 'not_implemented',
              'confinement': 'unverified', 'ready_for_execution': False, 'blockers': []}
    try:
        if role.args or role.cwd:
            raise ConfigError('Strict generation forbids provider overrides and reused workspaces')
        if not role.launcher:
            raise ConfigError('Audited isolation launcher is missing')
        inspect_native_executable(role.launcher[0], forbidden_roots)
        inspect_native_executable(role.executable, forbidden_roots)
        result['host_artifacts'] = 'compatible_metadata_only'
        review = load_review(role, forbidden_roots)
        validate_launch_contract(role, review, forbidden_roots)
        result.update(static_evidence='matches_reviewed_record', audit='trusted_review_reference_only')
    except (FactoryError, OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        # Never echo malformed record values, OS diagnostics, credentials or paths.
        result['blockers'].append(str(exc) if isinstance(exc, ConfigError) else 'Invalid or inaccessible launcher evidence')
    result['blockers'].append(HEALTH_BLOCKER)
    return result


def require_strict_isolation(role, forbidden_roots=()):
    assessment = assess_isolation(role, forbidden_roots)
    # This patch has no approved confined health/transport implementation. No
    # evidence flag, cached assessment or caller can turn a static match into one.
    raise ConfigError('; '.join(assessment['blockers']))
