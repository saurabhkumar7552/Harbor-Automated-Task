from importlib import import_module
from .codex import CodexAdapter
from .claude import ClaudeAdapter
from .gemini import GeminiAdapter
from ..errors import ConfigError


BUILTINS = {'codex': CodexAdapter, 'claude': ClaudeAdapter, 'gemini': GeminiAdapter}


def create(role, extensions):
    factory = BUILTINS.get(role.adapter)
    if factory is None:
        reference = extensions.get(role.adapter)
        if reference is None:
            raise ConfigError('Unknown CLI adapter')
        module, name = reference.split(':', 1)
        # Trusted operator configuration is equivalent to loading a Python plugin.
        factory = getattr(import_module(module), name)
    return factory(role)
