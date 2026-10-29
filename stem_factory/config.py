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
    fields(data, {"version", "repository", "existing_tasks", "output", "roles", "adapters", "limits", "validation"},
           {"version", "repository", "existing_tasks", "output", "roles", "limits", "validation"})
    if data["version"] != 1:
        raise ConfigError("Unsupported configuration version")
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
        fields(item, {"adapter", "executable", "model", "effort", "args", "timeout", "max_output_bytes", "required_env", "cwd", "launcher"},
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
        roles[name] = Role(item["adapter"], item["executable"], item["model"], effort,
                           strings(item.get("args", [])), number(item.get("timeout", 300), 1, 3600),
                           size, required_env, resolve(item["cwd"]) if item.get("cwd") else None,
                           strings(item.get("launcher", [])))
        # The launcher is an operator-audited confinement boundary, not a shell template.
        if roles[name].cwd and not roles[name].cwd.is_relative_to(output / "agent-work"):
            raise ConfigError("Role cwd must be within output/agent-work")
    a, r = roles["author"], roles["reviewer"]
    if (a.adapter == r.adapter or os.path.normcase(a.executable) == os.path.normcase(r.executable)) and a.model.casefold() == r.model.casefold():
        raise ConfigError("Author and reviewer require separately configured model identities")
    limits = {"max_candidates": 15, "max_revisions": 2, "max_calls": 100,
              "max_run_seconds": 7200, "max_cost_usd": None,
              "max_unknown_cost_calls": 100, "max_prompt_bytes": 1048576, "similarity_threshold": 0.72}
    fields(data["limits"], limits)
    limits.update(data["limits"])
    for key in ("max_candidates", "max_revisions", "max_calls", "max_unknown_cost_calls"):
        if type(limits[key]) is not int:
            raise ConfigError(f"{key} must be integer")
        number(limits[key], 0 if key == "max_revisions" else 1, 1000)
    number(limits["max_run_seconds"], 1, 86400)
    if type(limits['max_prompt_bytes']) is not int:
        raise ConfigError('max_prompt_bytes must be an integer')
    number(limits['max_prompt_bytes'], 4096, 16777216)
    number(limits["similarity_threshold"], .1, .95)
    if limits["max_cost_usd"] is not None:
        number(limits["max_cost_usd"], .01, 10000)
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
    return Config(path, repository, existing, output, roles, adapters, limits, validation,
                  hashlib.sha256(canonical.encode()).hexdigest())


def require_models(config):
    for name, role in config.roles.items():
        if any(marker in role.model.upper() for marker in ("REPLACE", "YOUR_", "<", ">")):
            raise ConfigError(f"Configure a verified model identity for {name}")
        if any(not os.environ.get(v) for v in role.required_env):
            raise ConfigError(f"Required environment variable missing for {name}; values are never printed")
