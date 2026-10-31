"""Generation-only control plane with read-only environment context and static packaging checks."""
import sys
from pathlib import Path

from . import contracts
from .adapters.codex import CodexAdapter
from .adapters.docker_codex import DockerCodexAdapter, assessment as docker_assessment
from .config import require_live_execution, require_models
from .errors import ConfigError, FactoryError
from .factory import Factory
from .isolation import assess_isolation
from .environment import inspect_environment
from .packaging import publish, static_check
from .proposals import author_prompt, novelty
from .reporting import atomic_json, event, tree_hash
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
    candidate_limit = config.limits['max_candidates']
    if target < 1 or (candidate_limit is not None and target > candidate_limit):
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
        'runtime_validation': 'Docker build, container execution and Harbor execution are not performed by offline package validation',
        'environment_spec': inspect_environment(config.existing_tasks, config.validation['image']),
        'harbor_required': False, 'docker_required_for_preflight': False,
        'benchmark_execution': 'never', 'inference_calls': 0, 'accepted_packages_created': 0,
        'blockers': blockers,
        'operations': [
            'Create explicit STEM objective, medium difficulty, inputs, expected outputs, constraints and acceptance criteria',
            'Author proposal; one review; at most one author repair (two versions total)',
            'Same author model implements private reference/tests with feedback; package without another review',
            'Check schema, syntax, templates and duplicate similarity against existing and accepted tasks',
            'Validate package structure, metadata, environment contract and leakage offline',
            'Publish offline-valid packages atomically; preserve final reviewer concerns and runtime uncertainty'],
        'limits': {**config.limits, 'max_revisions': min(1, config.limits['max_revisions'])},
    }


class GenerationValidator(Validator):
    def doctor(self):
        raise FactoryError('Generation preflight must not invoke runtime/Harbor doctor')

    def schema(self, package):
        # Repository-owned strict templates/TOML only. Harbor compatibility is deferred.
        return {'local_template': static_check(package, self.settings['image']),
                'harbor_compatibility': 'not checked; benchmark integration out of scope'}

    def validate(self, package, report_path):
        """Perform offline-only package checks; never build or start Docker images."""
        package = Path(package).resolve()
        result = {'passed': False, 'status': 'FAIL', 'package': str(package),
                  'input_hash': tree_hash(package, exclude={'authoring/validation.json'}),
                  'checks': [], 'checks_not_run': [
                      'Docker image build', 'reference execution in a container',
                      'verifier and mutant execution in containers', 'Harbor task execution'],
                  'harbor_execution': 'not_run', 'docker_build_verified': False}
        try:
            check = static_check(package, self.settings['image'])
            result['checks'].append({'name': 'package_structure_metadata_templates_leakage',
                                     'status': 'PASS', 'evidence': check})
            result['warnings'] = [
                'Offline validation does not establish Docker build or runtime compatibility.',
                'Harbor execution has not been run.']
            result.update(passed=True, status='offline_valid')
        except (FactoryError, OSError, ValueError) as exc:
            result['checks'].append({'name': 'package_structure_metadata_templates_leakage',
                                     'status': 'FAIL', 'detail': str(exc)})
            result['error'] = str(exc)
        atomic_json(report_path, result)
        return result


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
        self.environment_spec = inspect_environment(config.existing_tasks, config.validation['image'])
        super().__init__(config, **kwargs)

    def preflight(self):
        require_live_execution(self.config)
        require_entitlements(self.config)
        for adapter in {id(a): a for a in self.adapters.values()}.values():
            adapter.preflight()  # Explicitly selected transport; never a fallback.
        # Task images are checked at the later runtime gate, not during authoring.

    def subject(self):
        accepted = sum(c['status'] == 'accepted' for c in self.state.data['candidates'])
        subjects = self.config.generation['subjects']
        return subjects[accepted % len(subjects)]

    def author_request(self, current_inventory, candidate):
        return author_prompt(contracts.PROPOSAL, current_inventory,
            candidate.get('feedback'),
            {k: candidate[k] for k in ('proposal', 'implementation') if k in candidate},
            environment_spec=candidate.get('environment_spec', self.environment_spec),
            revision_history=candidate.get('repair_history', []), revision=candidate.get('revision', 0)) + (
            '\nRequired domain: ' + self.subject() +
            '\nThe problem_statement must explicitly define inputs, expected outputs, '
            'types, units, tolerances, error behavior and bounds. Acceptance criteria '
            'must be objectively testable. No unstated assumptions. Difficulty: medium.\n')

    def validate_proposal(self, proposal):
        if proposal['domain'].strip().casefold() != self.subject().strip().casefold():
            raise ConfigError('Proposal domain differs from requested subject')

    def step(self, candidate):
        candidate.setdefault('authoring_status', 'awaiting_author')
        candidate.setdefault('review_status', 'not_reviewed')
        candidate.setdefault('packaging_status', 'not_started')
        candidate.setdefault('package_validation_status', 'not_run')
        candidate.setdefault('harbor_execution_status', 'not_run')
        candidate.setdefault('repair_history', [])
        if candidate['revision'] >= min(1, self.config.limits['max_revisions']):
            candidate['revision_limit_reached'] = True
        current = inspect_environment(self.config.existing_tasks, self.config.validation['image'])
        previous = candidate.get('environment_spec')
        if previous and previous.get('fingerprint') != current['fingerprint']:
            change = {'old_fingerprint': previous.get('fingerprint'),
                      'new_fingerprint': current['fingerprint'],
                      'changed_evidence': {'previous': previous.get('evidence'),
                                           'current': current.get('evidence')}}
            candidate.setdefault('environment_history', []).append(change)
            previous_stage = candidate.get('stage')
            if previous_stage and Path(previous_stage).is_dir():
                archived = self.config.output / 'failed' / (Path(previous_stage).name + '-environment-changed')
                publish(previous_stage, archived)
            if candidate.get('proposal') and candidate['status'] != 'author' and \
                    candidate['revision'] < min(1, self.config.limits['max_revisions']):
                candidate.setdefault('repair_history', []).append({
                    'failed_revision': candidate['revision'], 'phase': candidate['status'],
                    'findings': {'environment_change': change},
                    'proposal': candidate.get('proposal'),
                    'implementation': candidate.get('implementation')})
                from .revisions import revise_or_reject
                revise_or_reject(candidate, {'environment_change': change},
                                 min(1, self.config.limits['max_revisions']))
                candidate.update(authoring_status='repair_pending', review_status='awaiting_review',
                                 packaging_status='not_started', package_validation_status='not_run')
            else:
                candidate['final_findings'] = {'environment_change': change}
                candidate['review_status'] = 'concerns_after_final_revision'
                if candidate.get('proposal') and candidate['status'] != 'author':
                    self.reject(candidate, {'environment_change': change},
                                'Environment changed after repair limit; create a fresh candidate')
                    candidate.update(packaging_status='package_failed',
                                     package_validation_status='failed')
                    self.state.save()
                    return
            event(self.config.output, 'environment_spec_changed', candidate=candidate['index'], **change)
        candidate['environment_spec'] = current
        candidate['environment_fingerprint'] = current['fingerprint']
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

    @staticmethod
    def key(candidate):
        base = f'candidate-{candidate["index"]:03d}-revision-{candidate["revision"]:02d}'
        fingerprint = candidate.get('environment_fingerprint')
        return base + (f'-env-{fingerprint[:12]}' if fingerprint else '')
