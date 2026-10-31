from .proposals import prompt


def review_prompt(schema, proposal, existing, environment_spec=None, *, feedback=None,
                  repair_history=None):
    # Fresh request: no author's difficulty verdict, prior reviewer decision or chat history.
    specification = {k: v for k, v in proposal.items() if k != 'difficulty_rationale'}
    return prompt('Independently solve/analyze this specification. Classify difficulty yourself. '
                  'Medium requires at least three dependent implementation/reasoning steps, '
                  'a nontrivial STEM algorithm, bounded scope, and no advanced research or '
                  'specialist infrastructure. Reject easy formula substitutions and hard research tasks. '
                  'Assess solvability, completeness, ambiguity, edge cases, tests and novelty against '
                  'the supplied inventory (including semantic similarity beyond word overlap). '
                  'PASS only if medium, complete, solvable, STEM relevant and adequately testable. '
                  'Check that the validation plan is implementable under the shared verifier contract; '
                  'reject unsupported enforcement claims without removing the underlying requirement. '
                  'Put blocking issues in defects and required_changes. Put every issue in findings '
                  'with category, severity, concrete evidence and required_change; categories are '
                  'correctness, environment, packaging, tests, security_leakage, difficulty, quality. '
                  'Only blocking findings prevent PASS. Never approve because an author says medium.',
                  schema, specification=specification, existing_tasks=existing,
                  verified_environment=environment_spec, prior_reviewer_findings=feedback,
                  repair_history=repair_history or [])


def passed(review):
    return (review['verdict'] == 'PASS' and review['difficulty'] == 'medium'
            and review['dependent_steps'] >= 3
            and all(review[k] for k in ('complete', 'solvable', 'stem_relevant', 'tests_adequate'))
            and not review['defects'] and not review['required_changes']
            and not any(item['severity'] == 'blocking' for item in review['findings']))


def audit_prompt(schema, proposal, implementation, environment_spec=None):
    return prompt('Audit the actual implementation bundle against the specification. '
                  'Public instruction must be complete and must not disclose the reference or hidden '
                  'test answers. Check every requirement is tested, expected values independently '
                  'make sense, tests are deterministic and cannot always pass, mutants represent at '
                  'least three distinct plausible conceptual errors rather than syntax/import failures. '
                  'Apply the shared verifier contract to the actual tests, including fresh guarded import, '
                  'bounded child checks, seeded local data, independent oracles, exact public tolerances '
                  'and real named-test traceability. A requested check is not evidence it exists. '
                  'Public API declarations alone are not reference-solution leakage. '
                  'Reference success is not proof of medium difficulty. FAIL for any defect.', schema,
                  specification={k: v for k, v in proposal.items() if k != 'difficulty_rationale'},
                  implementation=implementation, verified_environment=environment_spec)


def audit_passed(review):
    return review['verdict'] == 'PASS' and all(review[k] for k in (
        'specification_matches', 'no_ambiguity', 'no_answer_leakage', 'tests_meaningful', 'mutants_plausible'
    )) and not review['defects'] and not review['required_changes'] and not any(
        item['severity'] == 'blocking' for item in review['findings'])
