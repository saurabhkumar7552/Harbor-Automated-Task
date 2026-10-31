"""Read-only inspection of the target Harbor task environment."""
import json
from pathlib import Path
import re
import tomllib

from .errors import FactoryError
from .reporting import digest, no_secrets


MAX_SOURCE_BYTES = 65536


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise FactoryError(f'Environment evidence is not a bounded regular file: {path.name}')
    text = path.read_text(encoding='utf-8')
    no_secrets(text)
    return text


def inspect_environment(existing_tasks, configured_image=None, *, manifest=False):
    """Summarize verified local task metadata without running Docker or Harbor."""
    tasks = Path(existing_tasks)
    root = tasks.parent
    evidence = []
    facts = []
    assumptions = []
    unknowns = []
    example = None
    base_image = None
    try:
        candidates = sorted(p for p in tasks.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        candidates = []
    for task in candidates:
        toml_path = task / 'task.toml'
        dockerfile_path = task / 'environment' / 'Dockerfile'
        if toml_path.is_symlink() or dockerfile_path.is_symlink():
            continue
        if not toml_path.is_file() or not dockerfile_path.is_file():
            continue
        try:
            raw = tomllib.loads(_read(toml_path))
            dockerfile = _read(dockerfile_path)
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, FactoryError):
            continue
        match = re.search(r'(?m)^\s*FROM\s+([^\s]+)', dockerfile)
        if match is None:
            continue
        base_image = match.group(1)
        workdir_match = re.search(r'(?m)^\s*WORKDIR\s+(.+)$', dockerfile)
        workdir = workdir_match.group(1).strip() if workdir_match else None
        example = task
        evidence = [
            {'path': str(toml_path), 'sha256': digest(_read(toml_path))},
            {'path': str(dockerfile_path), 'sha256': digest(dockerfile)},
        ]
        ignore = task / 'environment' / '.dockerignore'
        if ignore.is_file() and not ignore.is_symlink():
            ignore_text = _read(ignore)
            evidence.append({'path': str(ignore), 'sha256': digest(ignore_text)})
            facts.append({'claim': 'Agent build context uses the inspected environment .dockerignore.',
                          'evidence': str(ignore)})
        facts.extend([
            {'claim': f'Harbor task schema version is {raw.get("schema_version", "unspecified")}.',
             'evidence': str(toml_path)},
            {'claim': f'Example agent submission artifacts are {raw.get("artifacts", [])}.',
             'evidence': str(toml_path)},
            {'claim': f'Agent base image is {base_image}.', 'evidence': str(dockerfile_path)},
            {'claim': f'Agent working directory is {workdir or "unspecified"}.',
             'evidence': str(dockerfile_path)},
            {'claim': f'Agent network mode is {raw.get("agent", {}).get("network_mode", "unspecified")}.',
             'evidence': str(toml_path)},
            {'claim': f'Verifier configuration is {raw.get("verifier", {})}.' , 'evidence': str(toml_path)},
            {'claim': f'Agent resource settings are {raw.get("environment", {})}.', 'evidence': str(toml_path)},
        ])
        break
    if example is None:
        unknowns.append('No readable task.toml and environment/Dockerfile pair was found; package conventions remain unverified.')
        sample_metadata = {}
        workdir = None
    else:
        try:
            sample_metadata = tomllib.loads(_read(example / 'task.toml'))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, FactoryError):
            sample_metadata = {}
        unknowns.extend([
            'The configured base-image tag was not built or checked for immutability during this inspection.',
            'Installed operating-system and Python package inventories were not executed or inferred from the image name.',
            'Runtime behavior and Harbor task execution were not tested.',
        ])
        if configured_image and base_image != configured_image:
            assumptions.append(f'The factory profile selects {configured_image}; the example uses {base_image}. Compatibility requires separate runtime validation.')
    assumptions.extend([
        ('Submission paths and language in this evidence describe the example only; the manifest defines actual task requirements.'
         if manifest else 'The factory profile continues to require one Python 3.13 standard-library submission at /work/task.py.'),
        'The inspected calculate-average task is a packaging example, not a source of task-specific solution requirements.',
    ])
    runtime = {'base_image': base_image, 'configured_image': configured_image,
               'working_directory': workdir,
               'agent': sample_metadata.get('agent'),
               'agent_network_mode': sample_metadata.get('agent', {}).get('network_mode'),
               'verifier': sample_metadata.get('verifier'),
               'environment': sample_metadata.get('environment'),
               'environment_resources': sample_metadata.get('environment'),
               'example_artifacts': sample_metadata.get('artifacts')}
    spec = {'version': 1, 'target_root': str(root), 'example_task': str(example) if example else None,
            'runtime': runtime, 'verified_facts': facts, 'assumptions': assumptions,
            'unknowns': unknowns, 'evidence': evidence}
    spec['fingerprint'] = digest(spec)
    return spec


def encode_environment(spec):
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2)
