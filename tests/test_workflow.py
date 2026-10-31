import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from stem_factory import contracts
from stem_factory.adapters.base import Response
from stem_factory.errors import RunHaltError, FactoryError
from stem_factory.factory import Factory, dry_plan
from stem_factory.packaging import create_package, publish, static_check
from stem_factory.reporting import atomic_json, digest, tree_hash
from stem_factory.state import Journal, RunLock, State
from tests.fixtures import config, proposal, review, audit, implementation


class FakeAdapter:
    def __init__(self, function):
        self.function = function
        self.calls = []

    def preflight(self):
        pass

    def invoke(self, prompt, schema, workspace, timeout=None):
        self.calls.append(prompt)
        value = self.function(len(self.calls), prompt, schema)
        return Response(value, json.dumps(value), '', {'fixture_tokens': 10}, .001)


class FakeValidator:
    """Control-plane fixture only; does NOT execute or establish package correctness."""
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def doctor(self):
        return {'harbor': {'available': True}, 'docker': {'available': True}}

    def image_identity(self):
        return 'sha256:' + 'a' * 64

    def validate(self, stage, path):
        self.calls += 1
        value = {'passed': self.ok, 'fixture_only': True, 'input_hash': tree_hash(stage)}
        atomic_json(path, value)
        return value


def agents(reject_first=False, always_fail=False):
    def author(index, prompt, schema):
        return proposal('coupled-decay-' + str(index))
    def reviewer(index, prompt, schema):
        if schema is contracts.AUDIT:
            return audit()
        return review(not always_fail and not (reject_first and index == 1))
    return {'author': FakeAdapter(author), 'reviewer': FakeAdapter(reviewer),
            'implementer': FakeAdapter(lambda *args: implementation())}


class Workflow(unittest.TestCase):
    def test_accept_and_resume_without_repeated_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a, v = config(directory), agents(), FakeValidator()
            before = tree_hash(c.existing_tasks)
            result = Factory(c, adapters=a, validator=v).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 4)
            result = Factory(c, adapters=a, validator=v).run(1)
            self.assertEqual(result['calls_reserved'], 4)
            self.assertEqual(v.calls, 1)
            self.assertEqual(tree_hash(c.existing_tasks), before)

    def test_full_five_control_plane(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory), agents()
            result = Factory(c, adapters=a, validator=FakeValidator()).run(5)
            self.assertEqual(result['accepted'], 5)
            self.assertEqual(result['calls_reserved'], 20)
            self.assertEqual(len(list((c.output / 'accepted').iterdir())), 5)

    def test_review_failure_revised_and_fresh_review(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory), agents(reject_first=True)
            result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(len(a['author'].calls), 2)
            self.assertIn('Specify units', a['author'].calls[1])
            self.assertIn('Specify units', a['reviewer'].calls[1])
            prior = c.output / 'requests/candidate-001-revision-00-review/result.json'
            self.assertEqual(json.loads(prior.read_text())['value']['verdict'], 'FAIL')

    def test_exhausted_review_retains_concerns_and_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory, max_candidates=1), agents(always_fail=True)
            result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(len(a['implementer'].calls), 1)
            self.assertEqual(result['candidates'][0]['status'], 'accepted')
            self.assertEqual(result['candidates'][0]['review_status'], 'concerns_after_final_revision')
            self.assertTrue(result['candidates'][0]['final_findings'])

    def test_failed_validation_preserves_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory, max_candidates=1, max_revisions=0)
            result = Factory(c, adapters=agents(), validator=FakeValidator(False)).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertTrue((c.output / 'failed/candidate-001-revision-00/solution/solve.sh').is_file())
            self.assertEqual(list((c.output / 'accepted').iterdir()), [])

    def test_no_configured_model_call_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory), agents()
            result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 4)

    def test_interrupt_before_cache_requires_explicit_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            c.output.mkdir()
            state = State(c)
            state.save()
            atomic_json(c.output / 'requests/pending/request.json', {'inflight': True})
            a = agents()
            with self.assertRaises(RunHaltError):
                Journal(state, a).call('author', 'spec', contracts.PROPOSAL, 'pending')
            self.assertEqual(len(a['author'].calls), 0)

    def test_cache_replay_no_request_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            c.output.mkdir()
            state, a = State(c), agents()
            journal = Journal(state, a)
            first = journal.call('author', 'spec', contracts.PROPOSAL, 'request')
            second = journal.call('author', 'spec', contracts.PROPOSAL, 'request')
            self.assertEqual(first, second)
            self.assertEqual(state.data['calls'], 1)
            with self.assertRaises(FactoryError):
                journal.call('author', 'changed spec', contracts.PROPOSAL, 'request')

    def test_atomic_publication_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'stage').mkdir()
            (root / 'accepted').mkdir()
            (root / 'accepted/original').write_text('original')
            with self.assertRaises(FactoryError):
                publish(root / 'stage', root / 'accepted')
            self.assertEqual((root / 'accepted/original').read_text(), 'original')

    def test_post_publish_crash_reconciles(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory), agents()
            Factory(c, adapters=a, validator=FakeValidator()).run(1)
            path = c.output / 'state.json'
            data = json.loads(path.read_text())
            data['candidates'][0]['status'] = 'validate'
            atomic_json(path, data)
            result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 4)

    def test_crash_after_validation_attachment_resumes_without_new_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a, v = config(directory), agents(), FakeValidator()
            with patch('stem_factory.factory.publish', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                Factory(c, adapters=a, validator=v).run(1)
            result = Factory(c, adapters=a, validator=v).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 4)
            self.assertEqual(v.calls, 1)

    def test_modified_accepted_package_blocks_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            c, a = config(directory), agents()
            Factory(c, adapters=a, validator=FakeValidator()).run(1)
            accepted = next((c.output / 'accepted').iterdir())
            (accepted / 'instruction.md').write_text('changed')
            with self.assertRaises(FactoryError):
                Factory(c, adapters=a, validator=FakeValidator()).run(1)

    def test_dry_run_never_creates_output(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            result = dry_plan(c, 5)
            self.assertTrue(result['dry_run'])
            self.assertFalse(c.output.exists())

    def test_run_lock_excludes_second_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            with RunLock(directory):
                with self.assertRaises(FactoryError):
                    with RunLock(directory):
                        pass

    def test_malformed_review_is_preserved_and_never_implemented(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory, max_revisions=0, max_candidates=1)
            a = agents()
            a['reviewer'] = FakeAdapter(lambda *args: {'verdict': 'PASS'})
            result = Factory(c, adapters=a, validator=FakeValidator()).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(a['implementer'].calls, [])
            transcript = c.output / 'requests/candidate-001-revision-00-review/transcript.json'
            self.assertIn('PASS', transcript.read_text())

    def test_large_prompt_is_not_blocked_by_a_configured_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            c.output.mkdir()
            state, a = State(c), agents()
            Journal(state, a).call('author', 'x'*5000, contracts.PROPOSAL, 'large-prompt')
            self.assertEqual(state.data['calls'], 1)
            self.assertEqual(len(a['author'].calls), 1)
