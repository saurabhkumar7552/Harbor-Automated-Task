from .base import Adapter, Response, response_value
from ..errors import ContractError
from .provider_failures import stop_if_account_blocked


class GeminiAdapter(Adapter):
    """Documented headless JSON interface; always re-probed on the installed CLI."""
    required_flags = ('--prompt', '--model', '--output-format')
    requires_launcher = True
    allowed_args = {}  # No installed effort/provider flags verified in this environment.

    def command(self, schema, workspace):
        # Gemini appends stdin to -p; schema is already included in the factory prompt.
        return [self.role.executable, '--prompt', 'Return only the JSON requested on stdin.',
                '--model', self.role.model, '--output-format', 'json']

    def parse(self, text):
        envelope = response_value(text)
        if envelope.get('error') or not isinstance(envelope.get('response'), str):
            if envelope.get('error'):
                stop_if_account_blocked(text)
            raise ContractError('Gemini response/error envelope invalid')
        return Response(response_value(envelope['response']), text, '', envelope.get('stats', {}))
