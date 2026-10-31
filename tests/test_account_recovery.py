"""Provider error classification and explicit recovery without live requests."""
import json
from pathlib import Path
import tempfile
import unittest

from stem_factory import contracts
from stem_factory.adapters.codex import CodexAdapter
from stem_factory.adapters.claude import ClaudeAdapter
from stem_factory.adapters.gemini import GeminiAdapter
from stem_factory.cli import parser
from stem_factory.errors import ContractError, RunHaltError
from stem_factory.generation import GenerationFactory
from stem_factory.reporting import atomic_json
from stem_factory.state import Journal, State
from tests.fixtures import config, proposal
from tests.test_adapters import role
from tests.test_manifest_generation import configuration, models
from tests.test_workflow import agents


def codex_response(value):
    return '\n'.join(json.dumps(e) for e in [
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(value)}},
        {'type': 'turn.completed', 'usage': {}}])


class AccountRecovery(unittest.TestCase):
    def test_successful_task_content_is_never_an_account_error(self):
        value = {'instruction': 'Implement a rate limit; reject unauthorized records and missing credentials.'}
        self.assertEqual(CodexAdapter(role('codex')).parse(codex_response(value)).value, value)
        self.assertEqual(ClaudeAdapter(role('claude')).parse(json.dumps(
            {'subtype': 'success', 'structured_output': value})).value, value)
        self.assertEqual(GeminiAdapter(role('gemini')).parse(json.dumps(
            {'response': json.dumps(value)})).value, value)

    def test_actual_provider_errors_halt_across_adapters(self):
        cases = [(CodexAdapter(role('codex')), {'type': 'turn.failed', 'error': {'message': 'rate limit exceeded'}}),
                 (CodexAdapter(role('codex')), {'type': 'error', 'message': 'authentication required'}),
                 (ClaudeAdapter(role('claude')), {'is_error': True, 'result': 'usage limit reached'}),
                 (GeminiAdapter(role('gemini')), {'error': {'message': 'invalid api key'}})]
        for adapter, payload in cases:
            with self.subTest(adapter=type(adapter).__name__), self.assertRaises(RunHaltError):
                adapter.parse(json.dumps(payload))
        with self.assertRaises(ContractError):
            CodexAdapter(role('codex')).parse(json.dumps({'type': 'turn.failed', 'error': {'message': 'server unavailable'}}))

    def test_opt_in_account_retry_archives_failure_and_completes_same_run(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), models()
            original = a['author'].function
            def once(index, prompt, schema):
                if index == 1:
                    raise RunHaltError('Provider usage limit prevented a model call; run stopped immediately')
                return original(index, prompt, schema)
            a['author'].function = once
            with self.assertRaises(RunHaltError):
                GenerationFactory(c, adapters=a).run(1)
            with self.assertRaises(RunHaltError):
                GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(len(a['author'].calls), 1)
            result = GenerationFactory(c, adapters=a, retry_account_errors=True).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 4)  # failed + author + review + implementation
            self.assertIsNone(result['last_stop'])
            archives = list((c.output/'requests').glob('*/attempts/*/result.json'))
            self.assertEqual(len(archives), 1)
            self.assertTrue(json.loads(archives[0].read_text(encoding='utf-8'))['halted'])
            self.assertTrue(any('-retry-' in p.name for p in (c.output/'agent-work').iterdir()))

    def test_repeated_account_failure_halts_after_one_authorized_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), models()
            def blocked(*args):
                raise RunHaltError('Authentication prevented a model call; run stopped immediately')
            a['author'].function = blocked
            for retry in (False, True):
                with self.assertRaises(RunHaltError):
                    GenerationFactory(c, adapters=a, retry_account_errors=retry).run(1)
            self.assertEqual(len(a['author'].calls), 2)

    def test_account_retry_never_bypasses_cleanup_or_identity_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(d)
            c.output.mkdir()
            state, a = State(c), agents()
            journal = Journal(state, a, retry_account_errors=True)
            for key, error in [('cleanup', 'Docker cleanup is uncertain; stopping the run'),
                               ('identity', 'Provider usage limit prevented a model call')]:
                from stem_factory.reporting import digest
                identity = digest({'role': 'author', 'prompt': 'same', 'schema': contracts.PROPOSAL})
                atomic_json(c.output/'requests'/key/'result.json',
                            {'identity': identity if key == 'cleanup' else 'changed', 'halted': True, 'error': error})
                with self.assertRaises(RunHaltError):
                    journal.call('author', 'same', contracts.PROPOSAL, key)
            self.assertEqual(state.data['calls'], 0)

    def test_interrupted_account_retry_requires_uncertain_authorization(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(d)
            c.output.mkdir()
            state, a = State(c), agents()
            def blocked(*args):
                raise RunHaltError('Authentication prevented a model call; run stopped immediately')
            a['author'].function = blocked
            with self.assertRaises(RunHaltError):
                Journal(state, a).call('author', 'same', contracts.PROPOSAL, 'pending')
            def interrupt(*args): raise KeyboardInterrupt()
            a['author'].function = interrupt
            with self.assertRaises(KeyboardInterrupt):
                Journal(state, a, retry_account_errors=True).call('author', 'same', contracts.PROPOSAL, 'pending')
            with self.assertRaisesRegex(RunHaltError, 'unknown completion'):
                Journal(state, a, retry_account_errors=True).call('author', 'same', contracts.PROPOSAL, 'pending')
            a['author'].function = lambda *args: proposal()
            self.assertEqual(Journal(state, a, retry_uncertain=True).call(
                'author', 'same', contracts.PROPOSAL, 'pending')['task_id'], 'coupled-decay')

    def test_zero_repairs_implementation_receives_failed_review(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), models(reject=True)
            c.generation['workflow']['author_repairs'] = 0
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['candidates'][0]['repairs_performed'], 1)
            self.assertIn('Specify units', a['author'].calls[-1])
            self.assertEqual(len(a['reviewer'].calls), 1)

    def test_cli_exposes_separate_account_and_uncertain_retry_flags(self):
        for command in ('run', 'generate'):
            args = parser().parse_args([command, '--retry-account-errors'])
            self.assertTrue(args.retry_account_errors)
            self.assertFalse(args.retry_uncertain)


if __name__ == '__main__':
    unittest.main()
