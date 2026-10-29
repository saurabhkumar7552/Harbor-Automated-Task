from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from stem_factory.adapters import create
from stem_factory.adapters.claude import ClaudeAdapter
from stem_factory.adapters.codex import CodexAdapter
from stem_factory.adapters.gemini import GeminiAdapter
from stem_factory.config import Role
from stem_factory.errors import ConfigError, ContractError


def role(adapter):
    return Role(adapter, adapter, 'fixture-model', None, (), 10, 65536, (), None, ())


class Adapters(unittest.TestCase):
    def test_codex_jsonl_usage(self):
        text = '\n'.join(json.dumps(v) for v in [
            {'type': 'thread.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"x":1}'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 12}}])
        result = CodexAdapter(role('codex')).parse(text)
        self.assertEqual(result.value, {'x': 1})
        self.assertEqual(result.usage['input_tokens'], 12)
        self.assertIsNone(result.cost_usd)

    def test_codex_rejects_missing_multiple_error(self):
        event = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}}
        for text in ('{}', json.dumps(event) + '\n' + json.dumps(event), '{"type":"turn.failed"}'):
            with self.assertRaises(ContractError):
                CodexAdapter(role('codex')).parse(text)

    def test_claude_envelopes(self):
        result = ClaudeAdapter(role('claude')).parse(json.dumps({'subtype': 'success',
            'structured_output': {'x': 1}, 'usage': {'input_tokens': 20}, 'total_cost_usd': .01}))
        self.assertEqual(result.value, {'x': 1})
        self.assertEqual(result.cost_usd, .01)
        with self.assertRaises(ContractError):
            ClaudeAdapter(role('claude')).parse('{"is_error":true}')

    def test_gemini_explicit_parser_no_fence_stripping(self):
        adapter = GeminiAdapter(role('gemini'))
        self.assertEqual(adapter.parse('{"response":"{\\"x\\":1}","stats":{}}').value, {'x': 1})
        for text in ('{"response":"```json {} ```"}', '{"error":{"message":"failed"}}'):
            with self.assertRaises(ContractError):
                adapter.parse(text)

    def test_claude_no_tools_or_mcp_or_hooks(self):
        adapter = ClaudeAdapter(role('claude'))
        with tempfile.TemporaryDirectory() as folder:
            argv = adapter.command({}, Path(folder))
        self.assertIn('--safe-mode', argv)
        self.assertEqual(argv[argv.index('--tools') + 1], '')
        self.assertIn('--strict-mcp-config', argv)
        self.assertNotIn('--dangerously-skip-permissions', argv)

    def test_permission_args_cannot_override_adapter(self):
        for provider, cls in (('codex', CodexAdapter), ('claude', ClaudeAdapter), ('gemini', GeminiAdapter)):
            adapter = cls(replace(role(provider), args=('--dangerously-bypass-approvals-and-sandbox',)))
            adapter.help = '--dangerously-bypass-approvals-and-sandbox'
            with self.assertRaises(ConfigError):
                adapter.check_args()

    def test_codex_and_gemini_fail_closed_without_launcher(self):
        for provider, cls in (('codex', CodexAdapter), ('gemini', GeminiAdapter)):
            adapter = cls(role(provider))
            with patch.object(adapter, 'inspect', return_value={'available': True}):
                with self.assertRaises(ConfigError):
                    adapter.preflight()

    def test_claude_and_gemini_reject_unverified_effort(self):
        for provider, cls in (('claude', ClaudeAdapter), ('gemini', GeminiAdapter)):
            with self.assertRaises(ConfigError):
                cls(replace(role(provider), effort='high')).check_effort()

    def test_extension_registry(self):
        adapter = create(replace(role('custom'), adapter='custom'),
                         {'custom': 'stem_factory.adapters.claude:ClaudeAdapter'})
        self.assertIsInstance(adapter, ClaudeAdapter)
