"""Generation-only control plane. No Harbor imports, probes or evaluations.

Static preflight is read-only. Executable task validation retains the existing
offline Docker boundary and is never substituted with host execution.
"""
import sys
from pathlib import Path

from .adapters.codex import CodexAdapter
from .adapters.docker_codex import DockerCodexAdapter, assessment as docker_assessment
from .config import require_live_execution, require_models
from .errors import ConfigError, FactoryError
from .factory import Factory
from .isolation import assess_isolation
from .packaging import static_check
from .proposals import novelty
from .validation import Validator


def require_entitlements(config):
    if config.generation is None:
        raise ConfigError('generate requires a generation configuration')
    require_models(config)
    for name in ('author', 'reviewer'):
        evidence = config.generation['entitlements'][name]
        if not evidence or evidence['model'] != config.roles[name].model:
            raise ConfigError(f'{name}: missing entitlement confirmation for this exact model; catalog/login is insufficient')
    if config.roles['author'].model.strip().casefold() == config.roles['reviewer'].model.strip().casefold():
        raise ConfigError('Generation author and reviewer models must differ')


def preflight(config, target):
    """No subprocesses, provider calls, runtime startup, or output writes."""
    if config.generation is None:
        raise ConfigError('generate requires a generation configuration')
    if not 1 <= target <= config.limits['max_candidates']:
        raise ConfigError('Target must be positive and no greater than max_candidates')
    blockers = []
    try:
        require_entitlements(config)
    except FactoryError as exc:
        blockers.append(str(exc))
    if not config.execution['live_enabled']:
        blockers.append('Live execution disabled; explicit approval required before enabling a future run')
    docker = config.generation.get('transport', 'strict') == 'docker'
    executable = Path(config.validation['docker_executable'] if docker else config.roles['author'].executable)
    if not executable.is_file():
        blockers.append('Configured transport executable is not visible from this process; an approved host context may be required')
    isolation = {name: docker_assessment(config) if docker else assess_isolation(role, (config.output, config.existing_tasks))
                 for name, role in config.roles.items()}
    for name, assessment in isolation.items():
        blockers.extend(f'{name}: {reason}' for reason in assessment['blockers'])
    return {
        'dry_run': True, 'config_valid': True, 'target': target, 'difficulty': 'medium',
        'python': sys.version.split()[0], 'python_compatible': sys.version_info >= (3, 11),
        'codex_executable_present': None if docker else executable.is_file(),
        'transport': 'docker' if docker else 'strict',
        'transport_executable_present': executable.is_file(),
        'subjects': config.generation['subjects'], 'output': str(config.output / 'accepted'),
        'existing_tasks': str(config.existing_tasks),
        'roles': {k: {'model': r.model, 'executable': r.executable} for k, r in config.roles.items()},
        'entitlement_status': 'Operator evidence required; no account entitlement verified by this preflight',
        'isolation_status': ('Docker confinement selected; tools and standard CLI authentication permitted; runtime unverified'
                             if docker else 'Unverified; launcher presence does not establish confinement'),
        'isolation': isolation,
        'authentication_status': 'Unverified; no authentication probe performed',
        'ready_for_live_generation': False,
        'runtime_validation': 'Deferred: existing offline Docker containment and local image required before inference; no host fallback',
        'harbor_required': False, 'docker_required_for_preflight': False,
        'benchmark_execution': 'never', 'inference_calls': 0, 'accepted_packages_created': 0,
        'blockers': blockers,
        'operations': [
            'Create explicit STEM objective, medium difficulty, inputs, expected outputs, constraints and acceptance criteria',
            'Author proposal; fresh independent reviewer; bounded revision or rejection',
            'Same author model implements private reference/tests; reviewer audits full package',
            'Check schema, syntax, templates and duplicate similarity against existing and accepted tasks',
            'Run reference twice, empty baseline and conceptual mutants using existing offline containment',
            'Publish only fully validated packages atomically into separate accepted directory'],
        'limits': config.limits, 'cost_tracking': 'Deferred; call limits do not establish a spending cap',
    }


class GenerationValidator(Validator):
    def doctor(self):
        raise FactoryError('Generation preflight must not invoke runtime/Harbor doctor')

    def schema(self, package):
        # Repository-owned strict templates/TOML only. Harbor compatibility is deferred.
        return {'local_template': static_check(package, self.settings['image']),
                'harbor_compatibility': 'not checked; benchmark integration out of scope'}


class GenerationFactory(Factory):
    def __init__(self, config, **kwargs):
        if config.generation is None:
            raise ConfigError('generate requires a generation configuration')
        kwargs.setdefault('validator', GenerationValidator(config))
        if 'adapters' not in kwargs:
            if config.generation.get('transport', 'strict') == 'docker':
                health = {'cleanup_failed': False}
                author = DockerCodexAdapter(config, config.roles['author'], health)
                reviewer = DockerCodexAdapter(config, config.roles['reviewer'], health)
            else:
                boundaries = (config.output, config.existing_tasks)
                author = CodexAdapter(config.roles['author'], strict_isolation=True, forbidden_roots=boundaries)
                reviewer = CodexAdapter(config.roles['reviewer'], strict_isolation=True, forbidden_roots=boundaries)
            kwargs['adapters'] = {'author': author, 'implementer': author, 'reviewer': reviewer}
        elif any(isinstance(a, CodexAdapter) and not a.strict_isolation for a in kwargs['adapters'].values()):
            raise ConfigError('Generation cannot use a legacy Codex adapter; strict isolation is required')
        super().__init__(config, **kwargs)

    def preflight(self):
        require_live_execution(self.config)
        require_entitlements(self.config)
        for adapter in self.adapters.values():
            adapter.preflight()  # Explicitly selected transport; never a fallback.
        # Runtime readiness, only on an explicitly enabled future live run. This
        # inspects an already-local image; no Docker/Harbor doctor or startup.
        self.validator.image_identity()

    def subject(self):
        accepted = sum(c['status'] == 'accepted' for c in self.state.data['candidates'])
        subjects = self.config.generation['subjects']
        return subjects[accepted % len(subjects)]

    def author_request(self, current_inventory, candidate):
        return super().author_request(current_inventory, candidate) + (
            '\nRequired domain: ' + self.subject() +
            '\nThe problem_statement must explicitly define inputs, expected outputs, '
            'types, units, tolerances, error behavior and bounds. Acceptance criteria '
            'must be objectively testable. No unstated assumptions. Difficulty: medium.\n')

    def validate_proposal(self, proposal):
        if proposal['domain'].strip().casefold() != self.subject().strip().casefold():
            raise ConfigError('Proposal domain differs from requested subject')

    def step(self, candidate):
        if candidate['status'] == 'validate':
            # Also compare the final public instruction, not only the proposal.
            from .proposals import inventory
            try:
                novelty({**candidate['proposal'],
                         'problem_statement': candidate['implementation']['instruction']},
                        inventory(self.config.existing_tasks, self.config.output / 'accepted'),
                        self.config.limits['similarity_threshold'])
            except FactoryError as exc:
                self.fail(candidate, {'duplicate_check': str(exc)})
                self.state.save()
                return
        super().step(candidate)
