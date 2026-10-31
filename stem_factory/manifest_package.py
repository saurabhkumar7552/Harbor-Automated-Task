"""Render declared task files without executing model-produced code or setup."""
import copy
import json
import shlex
import re
from pathlib import Path

from . import contracts, task_spec
from .errors import ContractError, FactoryError
from .reporting import atomic_json, digest, no_secrets, tree_hash


def check_bundle(proposal, bundle, request):
    contracts.validate(proposal, contracts.MANIFEST_PROPOSAL)
    for item in proposal['output_manifest']:
        task_spec.artifact_path(item['path'])
    for key in ('base_image', 'verifier_image'):
        if not re.fullmatch(r'[A-Za-z0-9_./:@-]+', proposal['environment_plan'][key]):
            raise ContractError('Unsafe container image reference')
    contracts.validate(bundle, contracts.MANIFEST_IMPLEMENTATION)
    public = bundle['instruction']
    if any(p in public for p in ('/solution/', '/tests/private/', 'reference_files')):
        raise ContractError('Public instruction exposes private verifier/reference paths')
    for group in ('starter_files', 'reference_files', 'verifier_files'):
        names = [task_spec.relative_path(f['path']) for f in bundle[group]]
        if len(names) != len(set(names)):
            raise ContractError(f'Duplicate paths in {group}')
        if len(names) != len({name.casefold() for name in names}):
            raise ContractError(f'Case-colliding paths in {group} are not portable')
        if any(a != b and b.startswith(a + '/') for a in names for b in names):
            raise ContractError(f'Conflicting file/directory paths in {group}')
    # Conservative exact-content guard. Semantic leakage still needs runtime/manual review.
    public_text = public + '\n' + '\n'.join(f['content'] for f in bundle['starter_files'])
    for private in bundle['reference_files'] + bundle['verifier_files']:
        if len(private['content'].strip()) >= 40 and private['content'].strip() in public_text:
            raise ContractError('Private reference/verifier file appears in public content')
    ids = [test['id'] for test in bundle['test_cases']]
    if len(ids) != len(set(ids)):
        raise ContractError('Duplicate test case IDs')
    for key in ('reference_command', 'verifier_command'):
        if any('\x00' in arg or '\n' in arg or '\r' in arg for arg in bundle[key]):
            raise ContractError('Command argv contains invalid control characters')


def traceability_report(proposal, bundle):
    catalog = task_spec.requirement_catalog(proposal)
    by_text = {row['description']: row['id'] for row in catalog}
    ids = {row['id'] for row in catalog}
    tests = {row['id'] for row in bundle['test_cases']}
    covered, mapping, warnings = set(), [], []
    for row in bundle['requirements_traceability']:
        label = row['requirement']
        requirement_id = label if label in ids else by_text.get(label)
        missing_tests = [test for test in row['tests'] if test not in tests]
        if requirement_id and not missing_tests:
            covered.add(requirement_id)
        if not requirement_id:
            warnings.append('Unresolved traceability label: ' + label)
        if missing_tests:
            warnings.append('Undeclared test IDs: ' + ', '.join(missing_tests))
        mapping.append({**row, 'requirement_id': requirement_id, 'missing_test_ids': missing_tests})
    missing = sorted(ids - covered)
    if missing:
        warnings.append('Coverage not established for: ' + ', '.join(missing))
    return {'requirements': catalog, 'mapping': mapping, 'unverified_requirements': missing,
            'warnings': warnings, 'coverage_status': 'declared' if not missing else 'incomplete'}


def environment_context(evidence):
    context = copy.deepcopy(evidence.get('environment_spec') or {})
    runtime = context.setdefault('runtime', {})
    network = 'public' if evidence['task_request']['constraints']['network_during_evaluation'] else 'no-network'
    for key in ('agent', 'environment', 'verifier'):
        runtime[key] = {**(runtime.get(key) or {}), 'network_mode': network}
    runtime['verifier']['environment_mode'] = 'separate'
    runtime['verifier']['environment'] = {
        **runtime['verifier'].get('environment', {}), 'network_mode': network}
    resources = evidence['proposal']['environment_plan']['resources']
    runtime['environment'].update(cpus=resources['cpus'], memory_mb=resources['memory_mb'], os='linux')
    runtime['verifier']['environment'].update(cpus=resources['cpus'], memory_mb=resources['memory_mb'], os='linux')
    runtime['agent']['timeout_sec'] = resources['agent_timeout_sec']
    runtime['verifier']['timeout_sec'] = resources['verifier_timeout_sec']
    return context


def dockerfile(image, steps, *, verifier=False, starter=False):
    lines = [f'FROM {image}', 'WORKDIR /work']
    for command in steps:
        # Setup strings are shell commands inside the future build only. Prevent
        # escaping RUN into another Dockerfile instruction through a raw newline.
        if any(c in command for c in ('\n', '\r', '\x00')) or command.rstrip().endswith('\\'):
            raise ContractError('Setup steps must each be a single Docker RUN command')
        lines.append('RUN ' + command)
    if verifier:
        lines.append('COPY test.sh /tests/test.sh')
        lines.append('COPY private/ /tests/private/')
    elif starter:
        lines.append('COPY starter/ /work/')
    return '\n'.join(lines) + '\n'


def templates(proposal, bundle, evidence):
    from .packaging import metadata
    request = evidence['task_request']
    check_bundle(proposal, bundle, request)
    plan = proposal['environment_plan']
    reference = shlex.join(bundle['reference_command'])
    verifier = shlex.join(bundle['verifier_command'])
    runner = ('#!/bin/sh\nset -u\nmkdir -p /logs/verifier || exit 1\n'
              'rm -f /logs/verifier/reward.txt /logs/verifier/reward.json\n'
              'cd /work || exit 1\n'
              f'{verifier} > /logs/verifier/tests.log 2>&1\nstatus=$?\n'
              'cat /logs/verifier/tests.log\n'
              'if [ "$status" -eq 0 ]; then printf "1\\n" > /logs/verifier/reward.txt; '
              'else printf "0\\n" > /logs/verifier/reward.txt; fi\nexit "$status"\n')
    result = {
        'instruction.md': (bundle['instruction'].rstrip() + '\n\n## Submission artifacts\n\n' +
            '\n'.join('- `' + item['path'] + '`' for item in proposal['output_manifest']) + '\n'),
        'task.toml': metadata(proposal, environment_context(evidence)),
        'environment/Dockerfile': dockerfile(plan['base_image'], plan['setup_steps'], starter=bool(bundle['starter_files'])),
        'environment/.dockerignore': '**\n!Dockerfile\n!starter/\n!starter/**\n',
        'solution/solve.sh': '#!/bin/sh\nset -eu\nmkdir -p /work\ncd /work\nexec ' + reference + '\n',
        'tests/Dockerfile': dockerfile(plan['verifier_image'], plan['verifier_setup_steps'], verifier=True),
        'tests/.dockerignore': '**\n!Dockerfile\n!test.sh\n!private/\n!private/**\n',
        'tests/test.sh': runner,
        'README.md': '# ' + proposal['title'] + '\n\nPrivate author package.\n'
                     'Profile: manifest-v1. No task commands or setup were executed during packaging.\n'
                     'Reference and hidden verifier files must remain outside the agent build context.\n'
                     'Test traceability and exact-content leakage checks do not prove functional correctness.\n',
        'authoring/manifest.json': json.dumps({'request': request, 'proposal': proposal,
                                             'test_cases': bundle['test_cases'],
                                             'traceability': traceability_report(proposal, bundle)}, indent=2, ensure_ascii=False) + '\n'}
    for group, prefix in (('starter_files', 'environment/starter/'),
                          ('reference_files', 'solution/files/'), ('verifier_files', 'tests/private/')):
        for file in bundle[group]:
            result[prefix + file['path']] = file['content']
    return result


def create_package(directory, proposal, bundle, evidence):
    contents = templates(proposal, bundle, evidence)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for relative, content in contents.items():
        no_secrets(content)
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8', newline='\n')
        if path.suffix == '.sh':
            path.chmod(0o755)
    atomic_json(directory / 'authoring/evidence.json', evidence)
    static_check(directory, evidence)
    return directory


def static_check(directory, evidence):
    directory = Path(directory)
    if evidence.get('profile') != 'manifest-v1':
        raise FactoryError('Unknown manifest package profile')
    environment = evidence.get('environment_spec')
    if environment is not None:
        bound = dict(environment)
        fingerprint = bound.pop('fingerprint', None)
        if fingerprint != evidence.get('environment_fingerprint') or fingerprint != digest(bound):
            raise FactoryError('Environment evidence fingerprint mismatch')
    expected = templates(evidence['proposal'], evidence['implementation'], evidence)
    required = set(expected) | {'authoring/evidence.json'}
    actual = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise FactoryError('Symlink in manifest package')
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        actual.add(relative)
        data = path.read_bytes()
        if (not data and expected.get(relative) != '') or b'\r' in data or data.startswith(b'\xef\xbb\xbf'):
            raise FactoryError('Package files must be nonempty UTF-8 LF')
        no_secrets(data.decode('utf-8'))
        if relative in expected and data.decode('utf-8') != expected[relative]:
            raise FactoryError(f'Manifest package differs from declared content: {relative}')
    if required - actual or actual - required - {'authoring/validation.json'}:
        raise FactoryError('Unexpected or missing manifest package files')
    return {'static': 'PASS', 'profile': 'manifest-v1', 'schema_version': '1.3',
            'warnings': traceability_report(evidence['proposal'], evidence['implementation'])['warnings'],
            'difficulty': evidence['proposal']['difficulty'],
            'language': evidence['proposal']['environment_plan']['language'],
            'environment_fingerprint': evidence.get('environment_fingerprint'),
            'checks_not_run': ['language syntax/compilation', 'setup commands', 'verifier behavior', 'Harbor execution'],
            'tree_hash': tree_hash(directory)}
