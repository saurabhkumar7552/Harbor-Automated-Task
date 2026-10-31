import copy
import json
from pathlib import Path
from stem_factory.config import load


def proposal(task_id='coupled-decay'):
    return {'task_id': task_id, 'title': 'Coupled decay reconstruction', 'domain': 'Physics',
            'learning_objective': 'Integrate coupled radioactive compartments with stable matrix arithmetic',
            'difficulty_rationale': 'Three dependent numerical reasoning stages',
            'problem_statement': 'Implement a stable reconstruction for a coupled decay network with nonnegative transitions.',
            'starting_environment': 'Empty /work, Python 3.13 standard library',
            'functional_requirements': ['Implement decay(x)'], 'constraints': ['No network'],
            'acceptance_criteria': ['Deterministic numeric results'], 'solution_strategy': 'Matrix recurrence',
            'deterministic_tests': ['Check invariants'], 'dependencies': ['Python 3.13 standard library'],
            'edge_cases': ['Zero transitions'],
            'output_manifest': [{'path': '/work/task.py', 'purpose': 'Submitted Python API'}]}


def review(ok=True):
    findings = [] if ok else [{'category': 'environment', 'severity': 'blocking',
                               'finding': 'Missing units', 'evidence': 'Input contract omits units',
                               'required_change': 'Specify units'}]
    return {'verdict': 'PASS' if ok else 'FAIL', 'difficulty': 'medium',
            'reasoning_complexity': 'Multiple dependent derivations', 'dependent_steps': 3,
            'ambiguity_assessment': 'Complete', 'complete': True, 'solvable': True,
            'solvability_assessment': 'Bounded', 'stem_relevant': True, 'stem_assessment': 'Physics',
            'tests_adequate': True, 'test_assessment': 'Edges and invariants',
            'defects': [] if ok else ['Missing units'], 'required_changes': [] if ok else ['Specify units'],
            'findings': findings}


def audit(ok=True):
    findings = [] if ok else [{'category': 'correctness', 'severity': 'blocking',
                               'finding': 'Mismatch', 'evidence': 'Spec differs',
                               'required_change': 'Fix mismatch'}]
    return {'verdict': 'PASS' if ok else 'FAIL', 'specification_matches': True, 'no_ambiguity': True,
            'no_answer_leakage': True, 'tests_meaningful': True, 'mutants_plausible': True,
            'rationale': 'Implementation aligns', 'defects': [] if ok else ['Mismatch'],
            'required_changes': [] if ok else ['Fix mismatch'], 'findings': findings}


def implementation():
    tests = 'import unittest\nfrom task import decay\nclass DecayTests(unittest.TestCase):\n'
    tests += ''.join(f'    def test_{i}(self):\n        self.assertEqual(decay({i}), {i})\n' for i in range(8))
    return {'instruction': 'Implement decay(x) in /work/task.py. Return x unchanged.',
            'reference_python': 'def decay(x):\n    return x\n', 'tests_python': tests,
            'mutants': [{'name': f'concept-{i}', 'rationale': f'Conceptual error {i}',
                         'code': f'def decay(x):\n    return x + {i}\n'} for i in range(1, 4)],
            'requirements_traceability': [{'requirement': 'Implement decay(x)', 'tests': ['test_0']}]}


def config(root, **limits):
    root = Path(root)
    existing = root / 'tasks'
    existing.mkdir(exist_ok=True)
    easy = existing / 'calculate-average'
    easy.mkdir(exist_ok=True)
    (easy / 'instruction.md').write_text('Compute the arithmetic mean of scores. Return zero for empty lists.')
    data = {'version': 1, 'repository': str(root), 'existing_tasks': str(existing),
            'output': str(root / 'output'), 'adapters': {},
            'roles': {name: {'adapter': 'codex', 'executable': 'fake-cli', 'model': f'fixture-{name}'}
                      for name in ('author', 'reviewer', 'implementer')},
            'limits': {'max_candidates': 5, 'max_revisions': 1, **limits}, 'validation': {}}
    path = root / 'models.yaml'
    path.write_text(json.dumps(data))
    return load(path)
