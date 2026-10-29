"""Repository-specific Harbor 1.3 templates, not arbitrary model file manifests."""
import ast
import ctypes
import json
import os
from pathlib import Path
import re
import tomllib
import sys
from .errors import ContractError, FactoryError
from .reporting import atomic_json, no_secrets, tree_hash


DRIVER = '''import importlib.util
import sys
import unittest
sys.path.insert(0, "/work")
spec = importlib.util.spec_from_file_location("hidden_tests", "/tests/test_task.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
if suite.countTestCases() < 8:
    raise SystemExit("At least 8 deterministic test cases are required")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
TEST_SH = '''#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier || exit 1
rm -f /logs/verifier/reward.json /logs/verifier/reward.txt
python -I /tests/driver.py > /logs/verifier/tests.log 2>&1
status=$?
cat /logs/verifier/tests.log
if [ "$status" -eq 0 ]; then
    printf '1\\n' > /logs/verifier/reward.txt || exit 1
else
    printf '0\\n' > /logs/verifier/reward.txt || exit 1
fi
exit "$status"
'''


def metadata(proposal):
    return f'''schema_version = "1.3"
artifacts = ["/work/task.py"]

[task]
name = {json.dumps('local/' + proposal['task_id'])}
description = {json.dumps(proposal['title'])}
keywords = ["stem", "python", "medium"]

[metadata]
category = {json.dumps(proposal['domain'])}
difficulty = "medium"

[agent]
timeout_sec = 600.0
network_mode = "public"

[verifier]
timeout_sec = 60.0
network_mode = "no-network"
environment_mode = "separate"

[verifier.environment]
network_mode = "no-network"
build_timeout_sec = 600.0
os = "linux"
cpus = 1
memory_mb = 512

[environment]
network_mode = "public"
build_timeout_sec = 600.0
os = "linux"
cpus = 1
memory_mb = 512
'''


def templates(proposal, implementation, image):
    reference = implementation['reference_python'].rstrip() + '\n'
    if re.search(r'^STEM_FACTORY_REFERENCE_END$', reference, re.M):
        raise ContractError('Reserved heredoc delimiter in reference')
    solve = "#!/bin/bash\nset -euo pipefail\nmkdir -p /work\ncat > /work/task.py <<'STEM_FACTORY_REFERENCE_END'\n" + reference + 'STEM_FACTORY_REFERENCE_END\n'
    return {
        'instruction.md': implementation['instruction'].rstrip() + '\n',
        'task.toml': metadata(proposal),
        'environment/Dockerfile': f'FROM {image}\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nWORKDIR /work\nRUN mkdir -p /work\n',
        'environment/.dockerignore': '**\n!Dockerfile\n',
        'solution/solve.sh': solve,
        'tests/Dockerfile': f'FROM {image}\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nWORKDIR /work\nCOPY test.sh test_task.py driver.py /tests/\n',
        'tests/.dockerignore': '**\n!Dockerfile\n!test.sh\n!test_task.py\n!driver.py\n',
        'tests/test.sh': TEST_SH, 'tests/driver.py': DRIVER,
        'tests/test_task.py': implementation['tests_python'].rstrip() + '\n',
        'README.md': f'# {proposal["title"]}\n\nPrivate author documentation.\n\n'
                     'Python 3.13 standard library only. Public build context is environment/ only.\n'
                     'Hidden tests are baked into the separate verifier; reference is Oracle-only.\n'
                     'Do not mount the package root into an evaluated agent.\n'
                     'Factory review and validation evidence is in authoring/.\n',
    }


def check_implementation(bundle):
    for key in ('reference_python', 'tests_python'):
        try:
            ast.parse(bundle[key])
        except SyntaxError as exc:
            raise ContractError(f'{key}: Python syntax error') from exc
    tree = ast.parse(bundle['tests_python'])
    tests = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
    if len(set(tests)) < 8:
        raise ContractError('At least eight named unittest test methods required')
    codes = set()
    for mutant in bundle['mutants']:
        try:
            ast.parse(mutant['code'])
        except SyntaxError as exc:
            raise ContractError('Mutants must be valid Python, not syntax errors') from exc
        code = ast.dump(ast.parse(mutant['code']))
        if code in codes or code == ast.dump(ast.parse(bundle['reference_python'])):
            raise ContractError('Duplicate mutant or identical reference')
        codes.add(code)
    public = bundle['instruction']
    if '/work/task.py' not in public or any(v in public for v in ('/solution/', '/tests/', 'reference_python')):
        raise ContractError('Instruction omits output contract or leaks private paths')
    # Mechanical exact-code leakage check plus independent semantic audit.
    for line in bundle['reference_python'].splitlines():
        if len(line.strip()) > 70 and line.strip() in public:
            raise ContractError('Reference code appears in public instructions')


def create_package(directory, proposal, implementation, image, evidence):
    check_implementation(implementation)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        for relative, content in templates(proposal, implementation, image).items():
            no_secrets(content)
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8', newline='\n')
        atomic_json(directory / 'authoring/evidence.json', evidence)
        static_check(directory, image)
    except Exception:
        # Caller archives this directory; never erase failed work.
        raise
    return directory


def static_check(directory, image):
    directory = Path(directory)
    required = {'instruction.md', 'task.toml', 'environment/Dockerfile', 'environment/.dockerignore',
                'solution/solve.sh', 'tests/Dockerfile', 'tests/.dockerignore', 'tests/test.sh',
                'tests/test_task.py', 'tests/driver.py', 'README.md', 'authoring/evidence.json'}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if not required <= actual or any(not p.startswith('authoring/') for p in actual - required):
        raise FactoryError('Unexpected or missing package files')
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise FactoryError('Package contains symlink')
        if path.is_file():
            data = path.read_bytes()
            if not data or b'\r' in data or data.startswith(b'\xef\xbb\xbf'):
                raise FactoryError('Package files must be nonempty UTF-8 LF')
            no_secrets(data.decode('utf-8'))
    proposal = json.loads((directory / 'authoring/evidence.json').read_text())['proposal']
    raw = tomllib.loads((directory / 'task.toml').read_text())
    if raw != tomllib.loads(metadata(proposal)):
        raise FactoryError('Harbor metadata differs from approved template')
    for relative, content in templates(proposal, json.loads((directory / 'authoring/evidence.json').read_text())['implementation'], image).items():
        if (directory / relative).read_text(encoding='utf-8') != content:
            raise FactoryError('Package differs from reviewed content')
    return {'static': 'PASS', 'schema_version': raw['schema_version'], 'tree_hash': tree_hash(directory)}


def publish(stage, destination):
    # Native no-replace rename also protects against an external process creating an empty destination.
    stage, destination = Path(stage), Path(destination)
    if destination.exists():
        raise FactoryError('Publication destination already exists; refusing overwrite')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == 'nt':
            os.rename(stage, destination)  # Windows rename refuses an existing destination.
        else:
            libc = ctypes.CDLL(None, use_errno=True)
            if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
                function = libc.renameat2
                function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                result = function(-100, os.fsencode(stage), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
            elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
                function = libc.renamex_np
                function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
                result = function(os.fsencode(stage), os.fsencode(destination), 4)  # RENAME_EXCL
            else:
                raise FactoryError('Atomic no-replace directory publication unsupported on this platform')
            if result:
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
    except OSError as exc:
        raise FactoryError('Atomic publication failed; destination is occupied or filesystem is incompatible') from exc
