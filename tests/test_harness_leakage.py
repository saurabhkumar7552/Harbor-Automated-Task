"""AST/prompt checks only: never import or execute generated task source."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from stem_factory import contracts
from stem_factory.errors import ContractError
from stem_factory.factory import IMPLEMENT_ACTION
from stem_factory.packaging import check_implementation, check_public_leakage
from stem_factory.proposals import HARNESS_CONTRACT, author_prompt, prompt
from stem_factory.review import audit_prompt, review_prompt
from tests.fixtures import implementation, proposal


SIGNATURE = ('def statistics(values: list[list[int]], target: int, '
             'start: int) -> tuple[float, float, float]:')
REFERENCE = SIGNATURE + '\n    weighted_total = sum(sum(row) for row in values)\n    return weighted_total / (target + start + 1)\n'


class Leakage(unittest.TestCase):
    def test_public_signature_without_body_is_permitted(self):
        check_public_leakage(REFERENCE, 'Implement this API:\n' + SIGNATURE + '\n\nSubmit /work/task.py.')

    def test_signature_stub_and_formatting_are_permitted(self):
        for stub in ('pass', '...'):
            public = '```python\n' + SIGNATURE.replace(', ', ',\n    ') + '\n    ' + stub + '\n```'
            # The signature deliberately spans lines inside its argument list.
            check_public_leakage(REFERENCE, public)

    def test_multiline_reference_header_is_permitted(self):
        reference = ('def statistics(\n    values: list[list[int]], target: int, start: int\n) -> tuple[float, float, float]:\n'
                     '    return target + start\n')
        check_public_leakage(reference, '```python\ndef statistics(\n    values: list[list[int]], target: int, start: int\n) -> tuple[float, float, float]:\n    ...\n```')

    def test_fenced_header_without_body_or_with_comment_is_permitted(self):
        for suffix in ('', ' # public API'):
            check_public_leakage(REFERENCE, '```python\n' + SIGNATURE + suffix + '\n```')

    def test_multiline_first_body_statement_does_not_break_header_assessment(self):
        source = SIGNATURE + '\n    return (\n        target + start\n    )\n'
        check_public_leakage(source, SIGNATURE)

    def test_actual_body_rejected_with_comments_and_formatting(self):
        bodies = ('weighted_total=sum(sum(row) for row in values) # copied\n',
                  '# explanatory comment\nweighted_total = sum( sum(row) for row in values )\n',
                  'return weighted_total/(target+start+1)\n')
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ContractError):
                check_public_leakage(REFERENCE, '```python\n' + body + '```')

    def test_unfenced_and_inline_solution_bodies_rejected(self):
        for public in ('weighted_total = sum(sum(row) for row in values)',
                       '`return weighted_total / (target + start + 1)`', REFERENCE):
            with self.subTest(public=public), self.assertRaises(ContractError):
                check_public_leakage(REFERENCE, public)

    def test_inline_function_body_never_exempt(self):
        source = 'def statistics(values): return sum(values) / len(values)\n'
        with self.assertRaises(ContractError):
            check_public_leakage(source, '```python\n' + source + '```')

    def test_old_long_line_protection_outside_code_blocks(self):
        body = '    answer = "' + 'sensitive reference detail ' * 5 + '"'
        with self.assertRaises(ContractError):
            check_public_leakage('def f():\n' + body + '\n    return answer\n', 'The algorithm is ' + body.strip())

    def test_comments_on_headers_are_not_exempted(self):
        source = SIGNATURE + ' # ' + 'private solution commentary ' * 4 + '\n    return target\n'
        with self.assertRaises(ContractError):
            check_public_leakage(source, source.splitlines()[0])

    def test_malformed_source_and_public_code_fail_closed(self):
        cases = [('def broken(', 'API'), (REFERENCE, '```python\ndef broken(\n```'),
                 (REFERENCE, '```python\n' + SIGNATURE), (REFERENCE, 'def broken('),
                 (REFERENCE, '```other\nnot valid python !\n```')]
        for reference, public in cases:
            with self.subTest(public=public), self.assertRaises(ContractError):
                check_public_leakage(reference, public)

    def test_parser_failure_fails_closed(self):
        for error in (SyntaxError('parser unavailable'), RecursionError('limit')):
            with patch('stem_factory.packaging.ast.parse', side_effect=error), self.assertRaises(ContractError):
                check_public_leakage(REFERENCE, SIGNATURE)

    def test_tokenizer_failure_fails_closed(self):
        import tokenize
        with patch('stem_factory.packaging.tokenize.generate_tokens', side_effect=tokenize.TokenError('bad tokens')), self.assertRaises(ContractError):
            check_public_leakage(REFERENCE, SIGNATURE)

    def test_existing_private_path_protection_remains(self):
        for private in ('/solution/', '/tests/', 'reference_python'):
            bundle = implementation()
            bundle['instruction'] += private
            with self.subTest(private=private), self.assertRaises(ContractError):
                check_implementation(bundle)

    def test_five_historical_bundles(self):
        root = Path(__file__).resolve().parents[1]
        run = root / 'task/retry-20261029-02/failed'
        cases = ((3, 0), (6, 1), (6, 2), (9, 0), (9, 1))
        if not run.is_dir():
            self.skipTest('Local historical run is not distributed as a fixture')
        for candidate, revision in cases:
            with self.subTest(candidate=candidate, revision=revision):
                record = json.loads((run / f'candidate-{candidate:03d}-revision-{revision:02d}.json').read_text())
                check_implementation(record['candidate']['implementation'])


class HarnessInstructions(unittest.TestCase):
    def test_all_roles_receive_same_capability_contract(self):
        prompts = (author_prompt(contracts.PROPOSAL, []),
                   prompt(IMPLEMENT_ACTION, contracts.IMPLEMENTATION, approved_proposal=proposal()),
                   review_prompt(contracts.REVIEW, proposal(), []),
                   audit_prompt(contracts.AUDIT, proposal(), implementation()))
        for text in prompts:
            self.assertIn(HARNESS_CONTRACT, text)
            self.assertIn('random.Random(integer_seed)', text)
            self.assertIn('shell=False', text)
            self.assertIn('No oracle', text)
            self.assertIn('do not require stricter accuracy', text)

    def test_obsolete_blanket_bans_removed(self):
        self.assertNotIn('run subprocesses', IMPLEMENT_ACTION)
        self.assertNotIn('or rely on random state', IMPLEMENT_ACTION)
        self.assertIn('global/unseeded random state', IMPLEMENT_ACTION)


if __name__ == '__main__':
    unittest.main()
