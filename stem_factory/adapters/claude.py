import json
from .base import Adapter, Response, response_value
from ..errors import ContractError


class ClaudeAdapter(Adapter):
    required_flags = ('--print', '--model', '--output-format', '--json-schema', '--safe-mode',
                      '--tools', '--strict-mcp-config', '--mcp-config', '--no-session-persistence')
    allowed_args = {'--betas': 1}

    def command(self, schema, workspace):
        return [self.role.executable, '--print', '--model', self.role.model,
                '--safe-mode', '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--no-session-persistence', '--output-format', 'json',
                '--json-schema', json.dumps(schema, separators=(',', ':')), *self.role.args]

    def parse(self, text):
        envelope = response_value(text)
        if envelope.get('is_error') or envelope.get('subtype', 'success') != 'success':
            raise ContractError('Claude unsuccessful result')
        value = envelope.get('structured_output')
        if value is None:
            value = response_value(envelope.get('result', ''))
        cost = envelope.get('total_cost_usd')
        if cost is not None and (type(cost) not in (float, int) or cost < 0):
            raise ContractError('Invalid cost')
        return Response(value, text, '', envelope.get('usage', {}), cost)
