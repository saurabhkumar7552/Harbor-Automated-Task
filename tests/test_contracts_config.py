import json
from pathlib import Path
import tempfile
import unittest
from stem_factory import contracts
from stem_factory.config import load, require_models
from stem_factory.errors import ConfigError, ContractError
from stem_factory.proposals import novelty, validate_scope
from stem_factory.review import passed, audit_passed, review_prompt
from tests.fixtures import config, proposal, review, audit, implementation


class ContractsAndConfig(unittest.TestCase):
    def test_all_contracts_roundtrip(self):
        for value, schema in ((proposal(), contracts.PROPOSAL), (review(), contracts.REVIEW),
                              (audit(), contracts.AUDIT), (implementation(), contracts.IMPLEMENTATION)):
            self.assertEqual(contracts.validate(contracts.loads(json.dumps(value)), schema), value)

    def test_malformed_json_duplicate_fences_trailing_nonfinite(self):
        for text in ('{"a":1,"a":2}', '```json\n{}\n```', '{} {}', '{"x":NaN}'):
            with self.subTest(text=text), self.assertRaises(ContractError):
                contracts.loads(text)

    def test_extra_missing_wrong_types(self):
        for change in ({'verdict': 'OK'}, {'dependent_steps': True}, {'complete': 'yes'}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                contracts.validate({**review(), **change}, contracts.REVIEW)

    def test_fail_cannot_be_converted_to_pass(self):
        for change in ({'verdict': 'FAIL'}, {'difficulty': 'easy'}, {'difficulty': 'hard'},
                       {'dependent_steps': 2}, {'complete': False}, {'solvable': False},
                       {'tests_adequate': False}, {'stem_relevant': False}, {'defects': ['Defect']}):
            self.assertFalse(passed({**review(), **change}))
        self.assertTrue(passed(review()))
        self.assertFalse(audit_passed(audit(False)))

    def test_reviewer_does_not_see_author_difficulty(self):
        value = proposal()
        value['difficulty_rationale'] = 'AUTHOR_SAYS_APPROVE_ME'
        text = review_prompt(contracts.REVIEW, value, [])
        self.assertNotIn('AUTHOR_SAYS_APPROVE_ME', text)
        self.assertIn(value['problem_statement'], text)
        self.assertIn('Classify difficulty yourself', text)

    def test_duplicate_and_similarity(self):
        p = proposal()
        for prior in ([{'task_id': p['task_id'], 'specification': 'Different'}],
                      [{'task_id': 'other-task', 'specification': p['problem_statement']} ]):
            with self.assertRaises(ContractError):
                novelty(p, prior, .7)

    def test_scope_rejects_paths_and_dependencies(self):
        for change in ({'output_manifest': [{'path': '../../secret', 'purpose': 'x'}]},
                       {'dependencies': ['numpy']}):
            with self.assertRaises(ContractError):
                validate_scope({**proposal(), **change})

    def test_config_independent_models_output_separation_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            data = json.loads(c.path.read_text())
            for mutation in ('same_model', 'output', 'secret', 'cwd'):
                altered = json.loads(json.dumps(data))
                if mutation == 'same_model':
                    altered['roles']['reviewer']['model'] = altered['roles']['author']['model']
                elif mutation == 'output':
                    altered['output'] = str(c.existing_tasks)
                elif mutation == 'secret':
                    altered['roles']['author']['api_key'] = 'do-not-store'
                else:
                    altered['roles']['author']['cwd'] = str(c.repository)
                c.path.write_text(json.dumps(altered))
                with self.subTest(mutation=mutation), self.assertRaises(ConfigError):
                    load(c.path)

    def test_placeholder_models_block_live_run(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            data = json.loads(c.path.read_text())
            data['roles']['author']['model'] = 'YOUR_AUTHOR_MODEL'
            c.path.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                require_models(load(c.path))

    def test_same_executable_cannot_hide_model_identity_behind_adapter_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            data = json.loads(c.path.read_text())
            data['roles']['reviewer']['adapter'] = 'custom-codex'
            data['roles']['reviewer']['model'] = data['roles']['author']['model']
            c.path.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                load(c.path)
