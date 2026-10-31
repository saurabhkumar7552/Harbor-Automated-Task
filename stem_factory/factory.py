import json
from pathlib import Path
from . import contracts
from .adapters import create
from .config import require_models, require_live_execution
from .errors import ContractError, FactoryError, RunHaltError
from .packaging import check_implementation, create_package, publish, static_check
from .proposals import author_prompt, inventory, novelty, prompt, validate_scope
from .reporting import atomic_json, digest, event, report, tree_hash
from .review import audit_passed, audit_prompt, passed, review_prompt
from .revisions import revise_or_reject
from .state import Journal, RunLock, State
from .validation import Validator


IMPLEMENT_ACTION = '''Implement the latest supplied proposal as structured content.
Apply supplied reviewer feedback to the actual instruction, reference and tests.
Preserve correct requirements and do not claim that unreviewed repairs are approved.
instruction is the full self-contained public specification, including exact API,
all constraints, units, numerical tolerances, input validation and acceptance criteria.
reference_python is the complete /work/task.py source, never public.
tests_python uses standard library unittest.TestCase with at least 8 named test_ methods.
Test the submitted API from task; arrange fresh-import safety checks before parent imports.
Do not redefine its implementation in tests. Follow the shared verifier contract.
Do not add a runner, main block, exit calls, print fake test results, alter unittest,
read private author files, use network, or rely on global/unseeded random state.
Only bounded local import-safety subprocesses and local seeded test generators
are permitted as described in the shared verifier contract; neither is allowed
in the submitted solution unless the public task contract explicitly permits it.
The factory supplies the runner. Include deterministic independent expected results,
edge cases, invalid input, numeric tolerances, invariants and non-mutation checks.
mutants contains at least three distinct syntactically valid complete task.py sources
with the SAME public API and plausible conceptual mistakes that tests should catch
with assertion failures. Do not use missing imports or missing functions as mutants.
requirements_traceability maps every functional requirement to named test methods.
'''


def dry_plan(config, target):
    return {'dry_run': True, 'target': target, 'existing_tasks': str(config.existing_tasks),
            'output': str(config.output), 'roles': {
                k: {'adapter': v.adapter, 'executable': v.executable, 'model': v.model,
                    'effort': v.effort, 'timeout': v.timeout, 'max_output_bytes': v.max_output_bytes,
                    'isolation_launcher_configured': bool(v.launcher)} for k, v in config.roles.items()},
            'operations': ['Validate models, installed CLI capabilities, authentication environment, Harbor and Docker',
                           'Load read-only existing task inventory', 'Author strict JSON proposals',
                           'Independent proposal review; revise up to three times and retain final concerns',
                           'Implement reviewed proposal as JSON content; audit with reviewer',
                           'Render fixed Harbor 1.3 templates to staging',
                           'Run offline package structure, metadata, source, leakage, and environment checks',
                           'Record Docker and Harbor runtime checks as not run',
                           'Publish offline-valid packages and preserve invalid package diagnostics'],
            'limits': config.limits, 'execution': config.execution, 'benchmark_execution': 'never'}


class Factory:
    def __init__(self, config, *, retry_uncertain=False, validator=None, adapters=None):
        self.config = config
        self.adapters = adapters or {k: create(v, config.adapters) for k, v in config.roles.items()}
        self.validator = validator or Validator(config)
        self.retry_uncertain = retry_uncertain

    def preflight(self):
        require_live_execution(self.config)
        require_models(self.config)
        for adapter in self.adapters.values():
            adapter.preflight()
        info = self.validator.doctor()
        if not info['harbor']['available'] or not info['docker']['available']:
            raise FactoryError('Local validation prerequisites unavailable; run doctor (no model calls made)')
        self.validator.image_identity()

    def run(self, target, recover_lock=False):
        self.preflight()  # No model spending until ALL prerequisites are present.
        root = self.config.output
        with RunLock(root, recover_lock):
            self.state = State(self.config)
            self.journal = Journal(self.state, self.adapters, self.retry_uncertain)
            for folder in ('accepted', 'staging', 'failed', 'requests', 'validation'):
                (root / folder).mkdir(exist_ok=True)
            try:
                if self.state.data.get('halted'):
                    raise FactoryError('Run halted after local validation failure; inspect diagnostics and prepare a new reviewed run')
                self.reconcile()
                while sum(c['status'] == 'accepted' for c in self.state.data['candidates']) < target:
                    candidate = next((c for c in self.state.data['candidates'] if c['status'] not in ('accepted', 'rejected')), None)
                    if candidate is None:
                        candidate_limit = self.config.limits['max_candidates']
                        if candidate_limit is not None and len(self.state.data['candidates']) >= candidate_limit:
                            break
                        candidate = {'index': len(self.state.data['candidates']) + 1,
                                     'revision': 0, 'status': 'author',
                                     'authoring_status': 'awaiting_author',
                                     'review_status': 'not_reviewed',
                                     'packaging_status': 'not_started',
                                     'package_validation_status': 'not_run',
                                     'harbor_execution_status': 'not_run',
                                     'repair_history': []}
                        self.state.data['candidates'].append(candidate)
                        self.state.save()
                    self.step(candidate)
                    if self.state.data.get('halted'):
                        break
            finally:
                self.state.save()
                atomic_json(root / 'report.json', report(root))
            return report(root)

    def reconcile(self):
        # A crash after rename but before state save must not repeat implementation/publication.
        for candidate in self.state.data['candidates']:
            if candidate['status'] == 'rejected':
                continue
            if not candidate.get('task_id'):
                continue
            destination = self.config.output / 'accepted' / candidate['task_id']
            if candidate['status'] == 'accepted':
                if not destination.is_dir() or tree_hash(destination) != candidate['published_hash']:
                    raise FactoryError('Accepted package missing or changed; refusing to regenerate/overwrite')
            elif destination.exists():
                evidence = json.loads((destination / 'authoring/evidence.json').read_text(encoding='utf-8'))
                validation = json.loads((destination / 'authoring/validation.json').read_text(encoding='utf-8'))
                if evidence.get('request_key') != self.key(candidate) or not validation['passed']:
                    raise FactoryError('Publication collision or incomplete evidence')
                static_check(destination, self.config.validation['image'])
                if validation.get('input_hash') != tree_hash(destination, exclude={'authoring/validation.json'}):
                    raise FactoryError('Published content differs from validation evidence')
                candidate.update(status='accepted', published_hash=tree_hash(destination))
        self.state.save()

    @staticmethod
    def key(candidate):
        return f'candidate-{candidate["index"]:03d}-revision-{candidate["revision"]:02d}'

    def step(self, candidate):
        config, root = self.config, self.config.output
        key = self.key(candidate)
        current_inventory = inventory(config.existing_tasks, root / 'accepted')
        try:
            phase = candidate['status']
            if phase == 'author':
                proposal = self.journal.call('author', self.author_request(current_inventory, candidate),
                                            contracts.PROPOSAL, key + '-author')
                validate_scope(proposal)
                self.validate_proposal(proposal)
                novelty(proposal, current_inventory, config.limits['similarity_threshold'])
                candidate.update(proposal=proposal, task_id=proposal['task_id'], status='review',
                                 authoring_status='proposal_authored', review_status='awaiting_review')
                candidate.pop('final_findings', None)
                if config.generation is not None and candidate.get('review'):
                    candidate.update(status='implement', review_status='repaired_without_rereview',
                                     revision_limit_reached=True)
                    candidate['final_findings'] = {'initial_review': candidate['review'],
                                                  'repair_verification': 'not_reviewed'}
            elif phase == 'review':
                review = self.journal.call(
                    'reviewer', review_prompt(contracts.REVIEW, candidate['proposal'], current_inventory,
                                              candidate.get('environment_spec'),
                                              feedback=candidate.get('feedback'),
                                              repair_history=candidate.get('repair_history', [])),
                    contracts.REVIEW, key + '-review')
                candidate['review'] = review
                if passed(review):
                    candidate.update(status='implement', review_status='proposal_approved')
                else:
                    candidate['review_status'] = 'proposal_findings'
                    if candidate['revision'] < config.limits['max_revisions']:
                        self.fail(candidate, {'independent_review': review})
                    else:
                        candidate.update(status='implement', revision_limit_reached=True,
                                         review_status='concerns_after_final_revision',
                                         final_findings={'proposal_review': review})
            elif phase == 'implement':
                implementation = self.journal.call('implementer', prompt(IMPLEMENT_ACTION, contracts.IMPLEMENTATION,
                    approved_proposal=candidate['proposal'],
                    reviewer_feedback=candidate.get('feedback'),
                    repair_history=candidate.get('repair_history', []),
                    verified_environment=candidate.get('environment_spec')),
                    contracts.IMPLEMENTATION, key + '-implement')
                candidate.update(implementation=implementation, status='audit', authoring_status='implemented')
                if config.generation is not None:
                    candidate['status'] = 'validate'
            elif phase == 'audit':
                if config.generation is not None:
                    candidate.update(status='validate', review_status='implementation_not_reviewed')
                    self.state.save()
                    return
                # Parse only: reject structural defects before spending a reviewer call.
                # Keep this at the audit boundary so resumed candidates are checked too.
                try:
                    check_implementation(candidate['implementation'])
                except ContractError as exc:
                    feedback = {'structural_validation': {
                        'code': 'IMPLEMENTATION_STRUCTURE', 'detail': str(exc)}}
                    if candidate['revision'] >= config.limits['max_revisions']:
                        candidate.update(status='validate', revision_limit_reached=True,
                                         review_status='concerns_after_final_revision',
                                         feedback=feedback, final_findings=feedback)
                    else:
                        self.fail(candidate, feedback)
                    self.state.save()
                    return
                audit = self.journal.call('reviewer', audit_prompt(contracts.AUDIT, candidate['proposal'],
                                          candidate['implementation'], candidate.get('environment_spec')),
                                          contracts.AUDIT, key + '-audit')
                candidate['audit'] = audit
                if not audit_passed(audit):
                    candidate['review_status'] = 'implementation_findings'
                    if candidate['revision'] < config.limits['max_revisions']:
                        self.fail(candidate, {'implementation_audit': audit})
                    else:
                        candidate.update(status='validate', revision_limit_reached=True,
                                         review_status='concerns_after_final_revision',
                                         final_findings={'implementation_audit': audit})
                else:
                    status = candidate.get('review_status')
                    if status != 'concerns_after_final_revision':
                        status = 'reviewer_approved'
                    candidate.update(status='validate', review_status=status)
            elif phase == 'validate':
                candidate['packaging_status'] = 'packaging'
                stage = root / 'staging' / key
                candidate['stage'] = str(stage)
                evidence = {k: candidate[k] for k in ('proposal', 'review', 'implementation', 'audit') if k in candidate}
                evidence.update(environment_spec=candidate.get('environment_spec'),
                                environment_fingerprint=candidate.get('environment_fingerprint'),
                                repair_history=candidate.get('repair_history', []),
                                revision=candidate['revision'],
                                review_status=candidate.get('review_status'),
                                final_findings=candidate.get('final_findings'))
                evidence.update(request_key=key, config_fingerprint=config.fingerprint,
                                model_identities={k: v.model for k, v in config.roles.items()},
                                independence='Fresh reviewer prompts; no statistical independence claim')
                if not stage.exists():
                    create_package(stage, candidate['proposal'], candidate['implementation'], config.validation['image'], evidence)
                if digest(json.loads((stage / 'authoring/evidence.json').read_text(encoding='utf-8'))) != digest(evidence):
                    raise FactoryError('Staged evidence differs from approved request')
                static_check(stage, config.validation['image'])
                validation_path = root / 'validation' / (key + '.json')
                candidate['validation_report'] = str(validation_path)
                if validation_path.exists():
                    validation = json.loads(validation_path.read_text(encoding='utf-8'))
                else:
                    validation = self.validator.validate(stage, validation_path)
                if not validation['passed']:
                    self.fail(candidate, {'local_validation': validation})
                else:
                    candidate['package_validation_status'] = 'offline_valid'
                    if validation.get('input_hash') != tree_hash(stage, exclude={'authoring/validation.json'}):
                        raise FactoryError('Validation report does not match staged content')
                    atomic_json(stage / 'authoring/validation.json', validation)
                    destination = root / 'accepted' / candidate['task_id']
                    publish(stage, destination)
                    candidate.update(status='accepted', packaging_status='packaged',
                                     package_validation_status='offline_valid',
                                     harbor_execution_status='not_run', published_hash=tree_hash(destination))
                    event(root, 'published', task_id=candidate['task_id'], request_key=key)
            else:
                raise FactoryError('Unknown workflow phase')
        except RunHaltError:
            raise
        except (FactoryError, OSError, ValueError) as exc:
            if not isinstance(exc, FactoryError) and not (
                candidate['status'] == 'validate' and config.execution['stop_on_validation_failure']
            ):
                raise
            self.fail(candidate, {'error': str(exc)})
        self.state.save()

    def author_request(self, current_inventory, candidate):
        previous = {k: candidate[k] for k in ('proposal', 'implementation') if k in candidate}
        return author_prompt(contracts.PROPOSAL, current_inventory,
                             candidate.get('feedback'), previous or None)

    def validate_proposal(self, proposal):
        pass

    def fail(self, candidate, feedback):
        key = self.key(candidate)
        phase = candidate['status']
        atomic_json(self.config.output / 'failed' / (key + '.json'),
                    {'candidate': candidate, 'feedback': feedback})
        stage = self.config.output / 'staging' / key
        if stage.exists():
            publish(stage, self.config.output / 'failed' / key)
        event(self.config.output, 'candidate_failed', request_key=key, feedback=feedback)
        candidate.setdefault('repair_history', []).append({
            'failed_revision': candidate['revision'], 'phase': candidate['status'],
            'findings': feedback, 'proposal': candidate.get('proposal'),
            'implementation': candidate.get('implementation')})
        if phase == 'validate' and self.config.execution['stop_on_validation_failure'] and \
                self.config.generation is None:
            reason = 'Local validation failed; workflow halted without revision or replacement'
            candidate.update(status='rejected', reason=reason, feedback=feedback,
                             packaging_status='package_failed', package_validation_status='failed')
            self.state.data['halted'] = {'request': key, 'reason': reason}
            self.state.save()
            return
        limit = min(1, self.config.limits['max_revisions']) if self.config.generation is not None else self.config.limits['max_revisions']
        if self.config.generation is not None and phase == 'validate':
            limit = candidate['revision']
        revise_or_reject(candidate, feedback, limit)
        if phase == 'validate' and candidate['status'] == 'rejected':
            candidate.update(packaging_status='package_failed', package_validation_status='failed',
                             harbor_execution_status='not_run')
        if candidate['status'] == 'author':
            candidate.update(authoring_status='repair_pending', review_status='awaiting_review',
                             packaging_status='not_started', package_validation_status='not_run')

    def reject(self, candidate, feedback, reason):
        key = self.key(candidate)
        atomic_json(self.config.output / 'failed' / (key + '.json'),
                    {'candidate': candidate, 'feedback': feedback})
        stage = self.config.output / 'staging' / key
        if stage.exists():
            publish(stage, self.config.output / 'failed' / key)
        event(self.config.output, 'candidate_failed', request_key=key, feedback=feedback)
        candidate.update(status='rejected', reason=reason, feedback=feedback)
