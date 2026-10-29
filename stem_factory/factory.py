import json
from pathlib import Path
import time
from . import contracts
from .adapters import create
from .config import require_models
from .errors import BudgetError, FactoryError
from .packaging import create_package, publish, static_check
from .proposals import author_prompt, inventory, novelty, prompt, validate_scope
from .reporting import atomic_json, digest, event, report, tree_hash
from .review import audit_passed, audit_prompt, passed, review_prompt
from .revisions import revise_or_reject
from .state import Journal, RunLock, State
from .validation import Validator


IMPLEMENT_ACTION = '''Implement ONLY the approved proposal as structured content.
instruction is the full self-contained public specification, including exact API,
all constraints, units, numerical tolerances, input validation and acceptance criteria.
reference_python is the complete /work/task.py source, never public.
tests_python uses standard library unittest.TestCase with at least 8 named test_ methods.
Import the submitted API from task; do not redefine its implementation in tests.
Do not add a runner, main block, exit calls, print fake test results, alter unittest,
read private author files, run subprocesses, use network, or rely on random state.
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
                           'Independent difficulty review; revise or reject with bounded retries',
                           'Implement reviewed proposal as JSON content; audit with reviewer',
                           'Render fixed Harbor 1.3 templates to staging',
                           'Validate installed Harbor schema; run packaged reference twice in offline Docker',
                           'Require empty-start failure and at least 3 conceptual mutants caught by assertions',
                           'Atomic publication inside output/accepted; persist state and report'],
            'limits': config.limits, 'benchmark_execution': 'never',
            'cost': 'Model usage may be billable; unknown cost is bounded by call count, not a dollar guarantee'}


class Factory:
    def __init__(self, config, *, retry_uncertain=False, validator=None, adapters=None):
        self.config = config
        self.adapters = adapters or {k: create(v, config.adapters) for k, v in config.roles.items()}
        self.validator = validator or Validator(config)
        self.retry_uncertain = retry_uncertain

    def preflight(self):
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
                self.reconcile()
                while sum(c['status'] == 'accepted' for c in self.state.data['candidates']) < target:
                    if self.state.remaining_time() <= 0:
                        raise BudgetError('Run time budget exhausted')
                    candidate = next((c for c in self.state.data['candidates'] if c['status'] not in ('accepted', 'rejected')), None)
                    if candidate is None:
                        if len(self.state.data['candidates']) >= self.config.limits['max_candidates']:
                            break
                        candidate = {'index': len(self.state.data['candidates']) + 1,
                                     'revision': 0, 'status': 'author'}
                        self.state.data['candidates'].append(candidate)
                        self.state.save()
                    self.step(candidate)
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
                proposal = self.journal.call('author', author_prompt(contracts.PROPOSAL, current_inventory,
                    candidate.get('feedback'), candidate.get('proposal')), contracts.PROPOSAL, key + '-author')
                validate_scope(proposal)
                novelty(proposal, current_inventory, config.limits['similarity_threshold'])
                candidate.update(proposal=proposal, task_id=proposal['task_id'], status='review')
            elif phase == 'review':
                review = self.journal.call('reviewer', review_prompt(contracts.REVIEW, candidate['proposal'], current_inventory),
                                           contracts.REVIEW, key + '-review')
                candidate['review'] = review
                if not passed(review):
                    self.fail(candidate, {'independent_review': review})
                else:
                    candidate['status'] = 'implement'
            elif phase == 'implement':
                implementation = self.journal.call('implementer', prompt(IMPLEMENT_ACTION, contracts.IMPLEMENTATION,
                    approved_proposal=candidate['proposal']), contracts.IMPLEMENTATION, key + '-implement')
                candidate.update(implementation=implementation, status='audit')
            elif phase == 'audit':
                audit = self.journal.call('reviewer', audit_prompt(contracts.AUDIT, candidate['proposal'], candidate['implementation']),
                                          contracts.AUDIT, key + '-audit')
                candidate['audit'] = audit
                if not audit_passed(audit):
                    self.fail(candidate, {'implementation_audit': audit})
                else:
                    candidate['status'] = 'validate'
            elif phase == 'validate':
                stage = root / 'staging' / key
                candidate['stage'] = str(stage)
                evidence = {k: candidate[k] for k in ('proposal', 'review', 'implementation', 'audit')}
                evidence.update(request_key=key, config_fingerprint=config.fingerprint,
                                model_identities={k: v.model for k, v in config.roles.items()},
                                independence='Fresh reviewer prompts; no statistical independence claim')
                if not stage.exists():
                    create_package(stage, candidate['proposal'], candidate['implementation'], config.validation['image'], evidence)
                if digest(json.loads((stage / 'authoring/evidence.json').read_text(encoding='utf-8'))) != digest(evidence):
                    raise FactoryError('Staged evidence differs from approved request')
                static_check(stage, config.validation['image'])
                validation_path = root / 'validation' / (key + '.json')
                if validation_path.exists():
                    validation = json.loads(validation_path.read_text(encoding='utf-8'))
                else:
                    self.validator.deadline = time.monotonic() + self.state.remaining_time()
                    validation = self.validator.validate(stage, validation_path)
                if not validation['passed']:
                    self.fail(candidate, {'local_validation': validation})
                else:
                    if validation.get('input_hash') != tree_hash(stage, exclude={'authoring/validation.json'}):
                        raise FactoryError('Validation report does not match staged content')
                    atomic_json(stage / 'authoring/validation.json', validation)
                    destination = root / 'accepted' / candidate['task_id']
                    publish(stage, destination)
                    candidate.update(status='accepted', published_hash=tree_hash(destination))
                    event(root, 'published', task_id=candidate['task_id'], request_key=key)
            else:
                raise FactoryError('Unknown workflow phase')
        except BudgetError:
            raise
        except FactoryError as exc:
            self.fail(candidate, {'error': str(exc)})
        self.state.save()

    def fail(self, candidate, feedback):
        key = self.key(candidate)
        atomic_json(self.config.output / 'failed' / (key + '.json'),
                    {'candidate': candidate, 'feedback': feedback})
        stage = self.config.output / 'staging' / key
        if stage.exists():
            publish(stage, self.config.output / 'failed' / key)
        event(self.config.output, 'candidate_failed', request_key=key, feedback=feedback)
        revise_or_reject(candidate, feedback, self.config.limits['max_revisions'])
