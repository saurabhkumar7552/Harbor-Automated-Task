"""Mock-only checks; synthetic audit records never authorize real execution."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from stem_factory import isolation as iso
from stem_factory.adapters.codex import CodexAdapter
from stem_factory.config import load
from stem_factory.errors import ConfigError
from tests.test_adapters import role
from tests.test_generation import generation_config


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def mock_review():
    """Trust, PE metadata and artifact contents are all in-memory mocks."""
    base = Path('C:/MOCK-ISOLATION-NOT-INSTALLED')
    launcher, codex, policy, evidence, document, tests, dll = (
        str(base / name) for name in ('launcher.exe', 'codex.exe', 'policy.json',
                                     'review.json', 'audit.txt', 'negative.txt', 'runtime.dll'))
    r = replace(role('codex'), executable=codex,
                launcher=(launcher, '--policy', policy, '--'), launcher_evidence=Path(evidence))
    contents = {policy: b'MOCK policy, not enforced', document: b'MOCK audit, not independent evidence',
                tests: b'MOCK test evidence, not confinement', dll: b'MOCK dependency'}
    def artifact(path):
        return {'path': path, 'sha256': 'a' * 64, 'file_identity': '1:2',
                'architecture': 'amd64', 'version': 'MOCK', 'publisher': 'MOCK',
                'provenance': 'MOCK fixture, not an approved installation'}
    def reference(path):
        return {'path': path, 'sha256': sha(contents[path])}
    now = datetime.now(timezone.utc)
    record = {'version': 1, 'launcher': artifact(launcher), 'codex': artifact(codex),
              'policy': {**reference(policy), 'version': 'MOCK-v1'}, 'dependencies': [reference(dll)],
              'contract': {'prefix': list(r.launcher), 'workspace': 'fresh-request-only',
                           'schema': 'canonical-windows-path', 'argument_grammar': 'MOCK exact argv',
                           'dependency_search': 'MOCK reviewed DLL search'},
              'controls': {k: {'mechanism': 'MOCK control, not enforced', 'review_reference': 'MOCK section '+k,
                               'negative_test_reference': 'MOCK negative test '+k} for k in iso.CONTROLS},
              'audit': {'reviewer': 'MOCK independent reviewer', 'decision': 'approved',
                        'scope': 'codex-generation-isolation',
                        'reviewed_at': (now-timedelta(hours=1)).isoformat(),
                        'expires_at': (now+timedelta(hours=1)).isoformat(),
                        'review_document': reference(document), 'negative_tests': reference(tests),
                        'limitations': 'MOCK only; no real confinement established',
                        'revalidation_triggers': ['MOCK binary/policy/OS/auth changes']},
              'runtime_binding': {'mechanism': 'MOCK binding', 'independent_observer': 'MOCK observer',
                                  'policy_version': 'MOCK-v1', 'phase': 'before-prompt'}}
    pins = {}
    def repin():
        pins.clear()
        pins[sha(json.dumps(record).encode())] = {
            'reviewer': record['audit']['reviewer'], 'review_document': record['audit']['review_document'],
            'policy': record['policy'], 'scope': record['audit']['scope']}
    repin()
    def read(path):
        raw = json.dumps(record).encode() if str(path) == evidence else contents[str(path)]
        return raw, raw.decode()
    def inspect(path, roots=()):
        return {k: artifact(str(path))[k] for k in ('path', 'sha256', 'file_identity', 'architecture')}
    with patch.object(iso, 'TRUSTED_REVIEWS', pins), \
         patch.object(iso, 'local_path', side_effect=lambda value, roots=(): Path(value)), \
         patch.object(iso, '_read_document', side_effect=read), \
         patch.object(iso, '_file_digest', side_effect=lambda path: sha(contents[str(path)])), \
         patch.object(iso, 'inspect_native_executable', side_effect=inspect), \
         patch('stem_factory.adapters.base.run', side_effect=AssertionError('Any process forbidden')):
        yield r, record, pins, contents, repin


class StaticIsolation(unittest.TestCase):
    def test_missing_paths_and_evidence(self):
        with patch('stem_factory.adapters.base.run', side_effect=AssertionError('process forbidden')):
            self.assertIn('missing', iso.assess_isolation(role('codex'))['blockers'][0])
            with self.assertRaises(ConfigError):
                iso.load_review(role('codex'))
            with patch.object(Path, 'lstat', side_effect=FileNotFoundError):
                with self.assertRaises(ConfigError):
                    iso.inspect_native_executable('C:/MOCK-ABSENT/launcher.exe')

    def test_invalid_path_grammar(self):
        paths = ['launcher.exe', '//server/share/a.exe', r'\\?\C:\a.exe',
                 r'C:\a.exe:stream', 'C:/root/../a.exe', 'C:/root/./a.exe', 'C:/a.exe\x00', '/tmp/a.exe']
        for path in paths:
            with self.subTest(path=path), patch.object(Path, 'lstat', side_effect=AssertionError('No metadata read')):
                with self.assertRaises(ConfigError):
                    iso.local_path(path)

    def test_directory_reparse_and_access_denial(self):
        regular = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0)
        for info in (SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0),
                     SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)):
            with self.subTest(info=info), patch.object(Path, 'lstat', return_value=info), \
                 patch.object(Path, 'resolve', return_value=Path('C:/MOCK/a.exe')):
                with self.assertRaises(ConfigError):
                    iso.local_path('C:/MOCK/a.exe')
        with patch.object(Path, 'lstat', side_effect=[regular, SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)]):
            with self.assertRaises(ConfigError):
                iso.local_path('C:/MOCK/a.exe')
        with patch.object(Path, 'lstat', side_effect=PermissionError):
            with self.assertRaises(ConfigError):
                iso.local_path('C:/MOCK/a.exe')

    def test_artifacts_in_mutable_output_rejected(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0)
        with patch.object(Path, 'lstat', return_value=info), \
             patch.object(Path, 'resolve', return_value=Path('C:/MOCK/output')):
            with self.assertRaises(ConfigError):
                iso.local_path('C:/MOCK/output/a.exe', (Path('C:/MOCK/output'),))

    def test_native_executable_format_and_architecture(self):
        def pe(machine=0x8664, flags=2, magic=0x20b):
            data = bytearray(90)
            data[:2] = b'MZ'
            struct.pack_into('<I', data, 60, 64)
            data[64:68] = b'PE\0\0'
            struct.pack_into('<H', data, 68, machine)
            struct.pack_into('<H', data, 86, flags)
            struct.pack_into('<H', data, 88, magic)
            return data
        for raw, ok in ((b'text renamed exe', False), (pe(flags=0x2002), False),
                        (pe(machine=0x14c), False), (pe(machine=0xaa64), False), (pe(magic=0x10b), False), (pe(), True)):
            path = Mock(spec=Path)
            path.suffix, path.name = '.exe', 'MOCK-launcher.exe'
            path.open.side_effect = lambda *a, **k: io.BytesIO(raw)
            path.stat.return_value = SimpleNamespace(st_dev=1, st_ino=2)
            with self.subTest(ok=ok, size=len(raw)), patch.object(iso, 'local_path', return_value=path), \
                 patch.object(iso.platform, 'machine', return_value='AMD64'), \
                 patch.object(iso, '_windows_binary_type') as query, patch.object(iso, '_file_digest', return_value='a'*64):
                if ok:
                    self.assertEqual(iso.inspect_native_executable('MOCK')['architecture'], 'amd64')
                    query.assert_called_once_with(path)
                else:
                    with self.assertRaises(ConfigError):
                        iso.inspect_native_executable('MOCK')
                    query.assert_not_called()

    def test_unsupported_launcher_types(self):
        for name in ('a.txt', 'a.cmd', 'a.ps1', 'a.py', 'a.lnk', 'a.dll', 'cmd.exe', 'python.exe', 'wsl.exe'):
            with self.subTest(name=name), patch.object(iso, 'local_path', return_value=Path('C:/MOCK')/name):
                with self.assertRaises(ConfigError):
                    iso.inspect_native_executable('MOCK')

    def test_production_has_no_trusted_records(self):
        self.assertEqual(iso.TRUSTED_REVIEWS, {})

    def test_complete_mock_review_is_only_static_match(self):
        with mock_review() as (r, record, pins, contents, repin):
            report = iso.assess_isolation(r)
            self.assertEqual(report['static_evidence'], 'matches_reviewed_record')
            self.assertEqual(report['audit'], 'trusted_review_reference_only')
            self.assertEqual(report['confinement'], 'unverified')
            self.assertFalse(report['ready_for_execution'])
            with self.assertRaisesRegex(ConfigError, 'health'):
                iso.require_strict_isolation(r)

    def test_untrusted_and_self_approved_records(self):
        with mock_review() as (r, record, pins, contents, repin):
            pins.clear()
            self.assertIn('independently approved', iso.assess_isolation(r)['blockers'][0])
            record['approved'] = True
            self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'invalid')

    def test_digest_only_trust_insufficient(self):
        with mock_review() as (r, record, pins, contents, repin):
            pins[next(iter(pins))] = True
            self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'invalid')

    def test_modified_evidence_not_cached(self):
        with mock_review() as (r, record, pins, contents, repin):
            self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'matches_reviewed_record')
            record['audit']['limitations'] = 'MOCK modified review'
            self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'invalid')

    def test_modified_policy_dependency_audit_and_negative_tests(self):
        for suffix in ('policy.json', 'runtime.dll', 'audit.txt', 'negative.txt'):
            with self.subTest(suffix=suffix), mock_review() as (r, record, pins, contents, repin):
                target = next(k for k in contents if k.endswith(suffix))
                contents[target] += b'CHANGED'
                self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'invalid')

    def test_incomplete_or_mismatched_record_even_with_mock_trust(self):
        for mutation in ('control', 'runtime', 'scope', 'expired', 'unknown', 'prefix', 'mapping', 'codex', 'launcher'):
            with self.subTest(mutation=mutation), mock_review() as (r, record, pins, contents, repin):
                if mutation == 'control':
                    del record['controls']['network']
                elif mutation == 'runtime':
                    record['runtime_binding']['policy_version'] = 'MOCK-other'
                elif mutation == 'scope':
                    record['audit']['scope'] = 'MOCK-unrelated'
                elif mutation == 'expired':
                    record['audit']['expires_at'] = '2000-01-01T00:00:00+00:00'
                elif mutation == 'unknown':
                    record['contract']['bypass'] = True
                elif mutation == 'prefix':
                    record['contract']['prefix'].insert(1, '--MOCK-bypass')
                elif mutation == 'mapping':
                    record['contract']['workspace'] = 'shared-home'
                else:
                    record[mutation]['sha256'] = 'b'*64
                repin()
                self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'invalid')

    def test_malformed_json_and_read_errors(self):
        with mock_review() as (r, record, pins, contents, repin):
            for raw in (b'{', b'{"version":1,"version":1}', b'{"approved":true}', b'[]'):
                with self.subTest(raw=raw), patch.object(iso, '_read_document', return_value=(raw, raw.decode())):
                    self.assertEqual(iso.assess_isolation(r)['static_evidence'], 'invalid')
            with patch.object(iso, '_read_document', side_effect=PermissionError('MOCK sentinel omitted')):
                self.assertNotIn('sentinel', str(iso.assess_isolation(r)))

    def test_strict_direct_calls_never_launch_or_write(self):
        with mock_review() as (r, record, pins, contents, repin):
            adapter = CodexAdapter(r, strict_isolation=True)
            self.assertFalse(adapter.inspect()['available'])
            for action in (adapter.preflight, lambda: adapter.invoke('MOCK', {}, Path('C:/MOCK-NOT-CREATED')),
                           lambda: adapter.command({}, Path('C:/MOCK-NOT-CREATED'))):
                with self.assertRaisesRegex(ConfigError, 'health'):
                    action()
            record['audit']['limitations'] = 'MOCK changed after inspection'
            with self.assertRaisesRegex(ConfigError, 'trust record'):
                adapter.invoke('MOCK', {}, Path('C:/MOCK-NOT-CREATED'))

    def test_static_checker_returning_cannot_unlock_legacy_transport(self):
        adapter = CodexAdapter(role('codex'), strict_isolation=True)
        with patch.object(iso, 'require_strict_isolation', return_value=None), \
             patch('stem_factory.adapters.base.run', side_effect=AssertionError('no fallback')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('no schema writes')):
            with self.assertRaises(ConfigError):
                adapter.invoke('MOCK', {}, Path('MOCK'))
            with self.assertRaises(ConfigError):
                adapter.command({}, Path('MOCK'))

    def test_optional_configuration_and_review_content_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            self.assertIsNone(c.roles['author'].launcher_evidence)
            data = json.loads(c.path.read_text())
            evidence = Path(d)/'MOCK-review.json'
            evidence.write_text('{}')
            for item in data['roles'].values():
                item['launcher_evidence'] = str(evidence)
            c.path.write_text(json.dumps(data))
            first = load(c.path)
            evidence.write_text('{"MOCK":true}')
            self.assertNotEqual(first.fingerprint, load(c.path).fingerprint)
            data['roles']['reviewer']['launcher_evidence'] = str(Path(d)/'other.json')
            c.path.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                load(c.path)

    def test_relative_evidence_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c = generation_config(d)
            data = json.loads(c.path.read_text())
            for value in ('review.json', '', 42):
                data['roles']['author']['launcher_evidence'] = value
                c.path.write_text(json.dumps(data))
                with self.subTest(value=value), self.assertRaises(ConfigError):
                    load(c.path)
