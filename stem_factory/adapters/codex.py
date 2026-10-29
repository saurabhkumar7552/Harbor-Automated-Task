import json
from .base import Adapter, Response, response_value
from ..errors import ConfigError, ContractError


class CodexAdapter(Adapter):
    help_args = ['exec', '--help']
    required_flags = ('--model', '--json', '--output-schema', '--sandbox', '--ignore-user-config',
                      '--ignore-rules', '--skip-git-repo-check', '--ephemeral')
    allowed_args = {'--oss': 0, '--local-provider': 1}
    requires_launcher = True

    def check_effort(self):
        # This is a TOML configuration key, not a guessed CLI flag. Provider must support its value.
        if self.role.effort and self.role.effort not in {'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}:
            raise ConfigError('Unsupported Codex reasoning effort; confirm model support with its provider')

    def command(self, schema, workspace):
        schema_path = workspace / 'response-schema.json'
        schema_path.write_text(json.dumps(schema), encoding='utf-8')
        args = [self.role.executable, 'exec', '--ignore-user-config', '--ignore-rules',
                '--sandbox', 'read-only', '--skip-git-repo-check', '--ephemeral',
                '--json', '--model', self.role.model, '--output-schema', str(schema_path)]
        if self.role.effort:
            args += ['-c', 'model_reasoning_effort=' + json.dumps(self.role.effort)]
        return [*args, *self.role.args, '-']

    def parse(self, text):
        answers, usage, completed = [], {}, 0
        for line in text.splitlines():
            event = response_value(line)
            if event.get('type') in {'error', 'turn.failed'}:
                raise ContractError('Codex error event')
            if event.get('type') == 'item.completed':
                item = event.get('item')
                if not isinstance(item, dict):
                    raise ContractError('Invalid Codex item envelope')
                if item.get('type') == 'agent_message':
                    if not isinstance(item.get('text'), str):
                        raise ContractError('Invalid Codex final message')
                    answers.append(item['text'])
            if event.get('type') == 'turn.completed':
                completed += 1
                usage = event.get('usage', {})
        if len(answers) != 1 or completed != 1:
            raise ContractError('Expected exactly one Codex final agent_message')
        return Response(response_value(answers[0]), text, '', usage)
