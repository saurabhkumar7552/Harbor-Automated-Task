from .proposals import prompt


def review_prompt(schema, proposal, existing):
    # Fresh request: no author's difficulty verdict, prior reviewer decision or chat history.
    specification = {k: v for k, v in proposal.items() if k != 'difficulty_rationale'}
    return prompt('Independently solve/analyze this specification. Classify difficulty yourself. '
                  'Medium requires at least three dependent implementation/reasoning steps, '
                  'a nontrivial STEM algorithm, bounded scope, and no advanced research or '
                  'specialist infrastructure. Reject easy formula substitutions and hard research tasks. '
                  'Assess solvability, completeness, ambiguity, edge cases, tests and novelty against '
                  'the supplied inventory (including semantic similarity beyond word overlap). '
                  'PASS only if medium, complete, solvable, STEM relevant and adequately testable. '
                  'List every defect and required change. Never approve because an author says medium.',
                  schema, specification=specification, existing_tasks=existing)


def passed(review):
    return (review['verdict'] == 'PASS' and review['difficulty'] == 'medium'
            and review['dependent_steps'] >= 3
            and all(review[k] for k in ('complete', 'solvable', 'stem_relevant', 'tests_adequate'))
            and not review['defects'] and not review['required_changes'])


def audit_prompt(schema, proposal, implementation):
    return prompt('Audit the actual implementation bundle against the specification. '
                  'Public instruction must be complete and must not disclose the reference or hidden '
                  'test answers. Check every requirement is tested, expected values independently '
                  'make sense, tests are deterministic and cannot always pass, mutants represent at '
                  'least three distinct plausible conceptual errors rather than syntax/import failures. '
                  'Reference success is not proof of medium difficulty. FAIL for any defect.', schema,
                  specification={k: v for k, v in proposal.items() if k != 'difficulty_rationale'},
                  implementation=implementation)


def audit_passed(review):
    return review['verdict'] == 'PASS' and all(review[k] for k in (
        'specification_matches', 'no_ambiguity', 'no_answer_leakage', 'tests_meaningful', 'mutants_plausible'
    )) and not review['defects'] and not review['required_changes']
