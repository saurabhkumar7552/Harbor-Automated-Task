"""Configuration is operator-owned. Model output never becomes executable config."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from .contracts import loads
from .errors import ConfigError, ContractError


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise ConfigError("Missing or unknown configuration fields")


def number(value, low, high):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ConfigError(f"Expected numeric value between {low} and {high}")
    return value


def strings(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or '\x00' in v for v in value):
        raise ConfigError("Expected an array of strings")
    return tuple(value)


@dataclass(frozen=True)
class Role:
    adapter: str
    executable: str
    model: str
    effort: str | None
    args: tuple[str, ...]
    timeout: float
    max_output_bytes: int
    required_env: tuple[str, ...]
    cwd: Path | None
    launcher: tuple[str, ...]
    launcher_evidence: Path | None = None


@dataclass(frozen=True)
class Config:
    path: Path
    repository: Path
    existing_tasks: Path
    output: Path
    roles: dict[str, Role]
    adapters: dict[str, str]
    limits: dict
    validation: dict
    fingerprint: str
    execution: dict
    generation: dict | None = None


def load(path):
    path = Path(path).resolve()
    raw = path.read_text(encoding="utf-8-sig")
    from .reporting import no_secrets
    no_secrets(raw)
    try:
        data = loads(raw)
    except ContractError:
        try:
            import yaml
        except ImportError as exc:
            raise ConfigError("Use JSON-form YAML (as shipped), or install the optional yaml extra yourself") from exc
        # Reject duplicate YAML keys as strictly as JSON.
        class UniqueLoader(yaml.SafeLoader):
            pass
        def mapping(loader, node):
            pairs = loader.construct_pairs(node)
            if len({k for k, _ in pairs}) != len(pairs):
                raise ConfigError("Duplicate YAML key")
            return dict(pairs)
        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        try:
            data = yaml.load(raw, Loader=UniqueLoader)
        except yaml.YAMLError as exc:
            raise ConfigError("Malformed YAML") from exc
    fields(data, {"version", "repository", "existing_tasks", "output", "roles", "adapters", "limits", "validation", "execution", "generation"},
           {"version", "repository", "existing_tasks", "output", "roles", "limits", "validation"})
    if data["version"] != 1:
        raise ConfigError("Unsupported configuration version")
    execution = {"live_enabled": True, "stop_on_validation_failure": False}
    fields(data.get("execution", {}), execution)
    execution.update(data.get("execution", {}))
    if any(type(value) is not bool for value in execution.values()):
        raise ConfigError("Execution controls must be booleans")
    def resolve(value):
        if not isinstance(value, str) or not value:
            raise ConfigError("Expected nonempty path")
        return (path.parent / value).resolve()
    repository, existing, output = (resolve(data[k]) for k in ("repository", "existing_tasks", "output"))
    if not existing.is_dir():
        raise ConfigError("existing_tasks must be a readable directory")
    if output == existing or output.is_relative_to(existing) or existing.is_relative_to(output):
        raise ConfigError("Factory output must be separate from existing tasks")
    fields(data["roles"], {"author", "reviewer", "implementer"}, {"author", "reviewer", "implementer"})
    adapters = data.get("adapters", {})
    if not isinstance(adapters, dict) or any(not isinstance(v, str) or ':' not in v for v in adapters.values()):
        raise ConfigError("adapters must map names to trusted module:Class references")
    roles = {}
    for name, item in data["roles"].items():
        fields(item, {"adapter", "executable", "model", "effort", "args", "timeout", "max_output_bytes", "required_env", "cwd", "launcher", "launcher_evidence"},
               {"adapter", "executable", "model"})
        for key in ("adapter", "executable", "model"):
            if not isinstance(item[key], str) or not item[key].strip() or '\x00' in item[key]:
                raise ConfigError(f"Invalid {name}.{key}")
        if item["model"].startswith('-'):
            raise ConfigError("Model identity cannot start with '-' ")
        effort = item.get("effort")
        if effort is not None and (not isinstance(effort, str) or not re.fullmatch(r"[a-z_]+", effort)):
            raise ConfigError("Invalid effort")
        required_env = strings(item.get("required_env", []))
        if any(not re.fullmatch(r"[A-Z_][A-Z0-9_]*", v) for v in required_env):
            raise ConfigError("required_env contains names only, never secret values")
        size = number(item.get("max_output_bytes", 1048576), 4096, 16777216)
        if type(size) is not int:
            raise ConfigError("max_output_bytes must be an integer")
        evidence = item.get('launcher_evidence')
        if evidence is not None:
            if (not isinstance(evidence, str) or not evidence or '\x00' in evidence
                    or not Path(evidence).is_absolute()):
                raise ConfigError('launcher_evidence must be an absolute path or null')
            # Preserve the original spelling; strict static validation must see
            # reparse points/traversal before following any path components.
            evidence = Path(evidence)
        roles[name] = Role(item["adapter"], item["executable"], item["model"], effort,
                           strings(item.get("args", [])), number(item.get("timeout", 300), 1, 3600),
                           size, required_env, resolve(item["cwd"]) if item.get("cwd") else None,
                           strings(item.get("launcher", [])), evidence)
        # The launcher is an operator-audited confinement boundary, not a shell template.
        if roles[name].cwd and not roles[name].cwd.is_relative_to(output / "agent-work"):
            raise ConfigError("Role cwd must be within output/agent-work")
    a, r = roles["author"], roles["reviewer"]
    if (a.adapter == r.adapter or os.path.normcase(a.executable) == os.path.normcase(r.executable)) and a.model.casefold() == r.model.casefold():
        raise ConfigError("Author and reviewer require separately configured model identities")
    limits = {"max_candidates": 15, "max_revisions": 3,
              "similarity_threshold": 0.72}
    fields(data["limits"], limits)
    limits.update(data["limits"])
    # Null explicitly means no candidate ceiling when the target is an accepted
    # count rather than an attempt count.
    if limits["max_candidates"] is not None:
        if type(limits["max_candidates"]) is not int:
            raise ConfigError("max_candidates must be integer or null")
        number(limits["max_candidates"], 1, 1000)
    if type(limits["max_revisions"]) is not int:
        raise ConfigError("max_revisions must be integer")
    number(limits["max_revisions"], 0, 1000)
    if limits["max_revisions"] > 3:
        raise ConfigError("max_revisions cannot exceed the three-repair workflow maximum")
    number(limits["similarity_threshold"], .1, .95)
    validation = {"docker_executable": "docker", "image": "python:3.13.0-slim-bookworm",
                  "timeout": 60, "max_output_bytes": 1048576,
                  "harbor_python": None, "harbor_site_packages": None}
    fields(data["validation"], validation)
    validation.update(data["validation"])
    image = validation["image"]
    if not isinstance(image, str) or not re.fullmatch(r"[a-zA-Z0-9_./:@-]+", image) or ':' not in image or image.endswith(':latest'):
        raise ConfigError("Validation image must have an explicit version or immutable digest")
    number(validation["timeout"], 1, 600)
    number(validation["max_output_bytes"], 4096, 16777216)
    # No free-form validation commands or pip dependencies are accepted.
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
    generation = data.get('generation')
    if generation is not None:
        fields(generation, {'subjects', 'entitlements', 'transport', 'docker'}, {'subjects', 'entitlements'})
        transport = generation.get('transport', 'strict')
        if transport not in ('strict', 'docker'):
            raise ConfigError('Generation transport must be strict or docker')
        if transport == 'docker':
            docker = generation.get('docker')
            fields(docker, {'image', 'auth_volume', 'cpus', 'memory_mb', 'pids_limit'},
                   {'image', 'auth_volume', 'cpus', 'memory_mb', 'pids_limit'})
            image = docker['image']
            if image is not None and (not isinstance(image, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)):
                raise ConfigError('Codex Docker image must be an immutable local sha256 image ID or null')
            volume = docker['auth_volume']
            if volume is not None and (not isinstance(volume, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{1,127}', volume)):
                raise ConfigError('Codex authentication must use a dedicated named volume or null, never a host path')
            for key, low, high in (('cpus', 1, 8), ('memory_mb', 512, 8192), ('pids_limit', 16, 256)):
                if type(docker[key]) is not int:
                    raise ConfigError(f'Docker {key} must be an integer')
                number(docker[key], low, high)
            if any(r.executable != 'codex' or r.launcher or r.launcher_evidence or r.required_env for r in roles.values()):
                raise ConfigError('Docker generation uses guest codex, no launchers and no host credential environment')
        elif 'docker' in generation:
            raise ConfigError('Docker settings require explicit docker transport')
        subjects = strings(generation['subjects'])
        if not subjects or len(subjects) > 20 or any(not s.strip() or len(s) > 100 for s in subjects):
            raise ConfigError('Generation subjects must contain 1-20 nonempty subject names')
        fields(generation['entitlements'], {'author', 'reviewer'}, {'author', 'reviewer'})
        for evidence in generation['entitlements'].values():
            if evidence is not None:
                fields(evidence, {'model', 'source'}, {'model', 'source'})
                if any(not isinstance(v, str) or not v.strip() for v in evidence.values()):
                    raise ConfigError('Entitlement evidence requires an exact model and a non-secret confirmation source')
        if adapters or any(r.adapter != 'codex' or r.args or r.cwd for r in roles.values()):
            raise ConfigError('Generation uses built-in Codex only, fresh workspaces and no provider overrides')
        if len({os.path.normcase(str(Path(r.executable).resolve())) for r in roles.values()}) != 1:
            raise ConfigError('Generation roles must use the same Codex CLI installation')
        if roles['implementer'] != roles['author']:
            raise ConfigError('Generation implementer must use the author role configuration')
        if any((v.launcher, v.launcher_evidence) != (a.launcher, a.launcher_evidence) for v in roles.values()):
            raise ConfigError('Generation roles must share the same launcher and review evidence')
        if any(v.launcher_evidence is not None for v in roles.values()):
            from .isolation import evidence_fingerprint
            bindings = {k: evidence_fingerprint(v, (output, existing)) for k, v in roles.items()}
            canonical = json.dumps({'configuration': data, 'launcher_review_contents': bindings},
                                   sort_keys=True, separators=(',', ':'))
    return Config(path, repository, existing, output, roles, adapters, limits, validation,
                  hashlib.sha256(canonical.encode()).hexdigest(), execution, generation)


def require_live_execution(config):
    if not config.execution['live_enabled']:
        raise ConfigError('Live execution is disabled in configuration; verify model access and isolation before enabling')


def require_models(config):
    for name, role in config.roles.items():
        if any(marker in role.model.upper() for marker in ("REPLACE", "YOUR_", "<", ">")):
            raise ConfigError(f"Configure a verified model identity for {name}")
        if any(not os.environ.get(v) for v in role.required_env):
            raise ConfigError(f"Required environment variable missing for {name}; values are never printed")
