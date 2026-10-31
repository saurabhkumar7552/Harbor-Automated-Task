"""Author → reviewer → final author bundle → packaging, with no rejection loop."""
import json
import uuid
from pathlib import Path

from . import contracts, task_spec
from .environment import inspect_environment
from .errors import FactoryError, RunHaltError
from .packaging import create_package, publish, static_check
from .proposals import inventory, novelty
from .reporting import atomic_json, digest, event, tree_hash


def diagnostics(factory, proposal, request, current_inventory):
    findings = []
    for label, check in (
        ('manifest', lambda: task_spec.validate_proposal(proposal, request)),
        ('novelty', lambda: novelty(proposal, current_inventory, factory.config.limits['similarity_threshold']))):
        try:
            check()
        except FactoryError as exc:
            findings.append({'category': label, 'detail': str(exc)})
    return findings


def step(factory, candidate):
    config, root = factory.config, factory.config.output
    candidate.setdefault('task_request', factory.run_request(candidate))
    request = candidate['task_request']
    candidate.setdefault('repair_history', [])
    candidate.setdefault('workflow', 'feedback-package-v2')
    phase = candidate['status']
    current_inventory = inventory(config.existing_tasks, root / 'accepted')
    if 'environment_spec' not in candidate:
        candidate['environment_spec'] = inspect_environment(config.existing_tasks, config.validation['image'], manifest=True)
        candidate['environment_fingerprint'] = candidate['environment_spec']['fingerprint']
    key = factory.key(candidate)
    try:
        if phase == 'author':
            schema = task_spec.proposal_schema(request)
            proposal = factory.journal.call('author', task_spec.phase_prompt('author', schema, request,
                existing_tasks=current_inventory, environment_example=candidate['environment_spec']), schema, key + '-author')
            candidate.update(proposal=proposal, task_id=proposal['task_id'], status='review',
                             authoring_status='proposal_authored', review_status='awaiting_review')
            candidate['proposal_diagnostics'] = diagnostics(factory, proposal, request, current_inventory)
        elif phase == 'review':
            review = factory.journal.call('reviewer', task_spec.phase_prompt('review', contracts.REVIEW, request,
                specification={k: v for k, v in candidate['proposal'].items() if k != 'difficulty_rationale'},
                requirement_catalog=task_spec.requirement_catalog(candidate['proposal']),
                proposal_diagnostics=candidate.get('proposal_diagnostics', []),
                environment_example=candidate['environment_spec'], existing_tasks=current_inventory),
                contracts.REVIEW, key + '-review')
            candidate.update(review=review, feedback={'independent_review': review}, status='finalize',
                             review_status='feedback_received', authoring_status='finalization_pending')
        elif phase == 'finalize':
            schema = task_spec.finalization_schema(request)
            result = factory.journal.call('author', task_spec.phase_prompt('finalize', schema, request,
                previous_proposal=candidate['proposal'], reviewer_feedback=candidate['review'],
                proposal_diagnostics=candidate.get('proposal_diagnostics', []),
                requirement_catalog=task_spec.requirement_catalog(candidate['proposal']),
                environment_example=candidate['environment_spec']), schema, key + '-finalize')
            candidate['initial_proposal'] = candidate['proposal']
            candidate.update(proposal=result['proposal'], implementation=result['implementation'],
                task_id=result['proposal']['task_id'], status='validate', revision=1,
                authoring_status='finalized', review_status='repaired_without_rereview',
                revision_limit_reached=True,
                final_findings={'initial_review': candidate['review'], 'repair_verification': 'not_reviewed'})
            candidate['final_diagnostics'] = diagnostics(factory, candidate['proposal'], request, current_inventory)
            candidate['repair_history'].append({'phase': 'finalize', 'failed_revision': 0,
                                               'findings': candidate['review']})
        elif phase == 'validate':
            package(factory, candidate)
        else:
            raise FactoryError('This manifest workflow requires a fresh run; unsupported saved phase: ' + phase)
    except RunHaltError:
        raise
    except (FactoryError, OSError, ValueError) as exc:
        if phase == 'review':
            candidate.update(review={'verdict': 'unavailable', 'findings': [], 'error': str(exc)},
                             feedback={'review_error': str(exc)}, status='finalize',
                             review_status='review_unavailable', authoring_status='finalization_pending')
            event(root, 'review_unavailable', request_key=key, reason=str(exc))
        else:
            preserve(factory, candidate, phase, str(exc))
    factory.state.save()


def preserve(factory, candidate, phase, reason):
    """Retain incomplete work without calling it rejected or offline-valid."""
    root = factory.config.output
    key = factory.key(candidate)
    destination = root / 'drafts' / key
    stage = root / 'staging' / key
    if destination.exists() and stage.is_dir():
        destination = root / 'drafts' / (key + '-preserved-' + uuid.uuid4().hex[:12])
    if stage.is_dir():
        publish(stage, destination)
    destination.mkdir(parents=True, exist_ok=True)
    atomic_json(destination / 'diagnostics.json', {'phase': phase, 'reason': reason,
                'candidate': candidate, 'harbor_execution_status': 'not_run'})
    candidate.update(status='needs_attention', reason=reason, diagnostic_phase=phase,
                     draft_path=str(destination), packaging_status='draft_preserved',
                     package_validation_status='invalid' if phase == 'validate' else 'not_run')
    event(root, 'draft_preserved', request_key=key, phase=phase, reason=reason)


def package(factory, candidate):
    root, config = factory.config.output, factory.config
    key = factory.key(candidate)
    stage = root / 'staging' / key
    candidate.update(packaging_status='packaging', stage=str(stage))
    evidence = {k: candidate.get(k) for k in ('proposal', 'initial_proposal', 'review', 'implementation',
        'environment_spec', 'environment_fingerprint', 'repair_history', 'revision',
        'review_status', 'final_findings', 'task_request', 'final_diagnostics')}
    evidence.update(profile='manifest-v1', workflow='feedback-package-v2', request_key=key,
        config_fingerprint=config.fingerprint, model_identities={k: v.model for k, v in config.roles.items()})
    if not stage.exists():
        create_package(stage, candidate['proposal'], candidate['implementation'], config.validation['image'], evidence)
    if digest(json.loads((stage / 'authoring/evidence.json').read_text(encoding='utf-8'))) != digest(evidence):
        raise FactoryError('Staged evidence differs from the finalized task')
    static_check(stage, config.validation['image'])
    report_path = root / 'validation' / (key + '.json')
    candidate['validation_report'] = str(report_path)
    validation = (json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists()
                  else factory.validator.validate(stage, report_path))
    if not validation['passed']:
        preserve(factory, candidate, 'validate', validation.get('error', 'Offline package validation failed'))
        return
    if validation.get('input_hash') != tree_hash(stage, exclude={'authoring/validation.json'}):
        raise FactoryError('Validation evidence does not match staged content')
    atomic_json(stage / 'authoring/validation.json', validation)
    destination = root / 'accepted' / candidate['task_id']
    publish(stage, destination)
    candidate.update(status='accepted', packaging_status='packaged', package_validation_status='offline_valid',
                     harbor_execution_status='not_run', published_hash=tree_hash(destination),
                     packaging_warnings=validation.get('warnings', []))
    event(root, 'published', task_id=candidate['task_id'], request_key=key)
