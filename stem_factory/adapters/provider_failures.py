"""Recognize provider account and usage blocks that must stop a generation run."""
from ..errors import RunHaltError


AUTH_MARKERS = (
    'unauthorized', 'authentication failed', 'authentication required',
    'not authenticated', 'login required', 'please log in', 'sign in to continue',
    'invalid api key', 'invalid_api_key', 'invalid_auth', 'authorization failed',
    'missing credentials', 'token expired', 'expired access token',
    'refresh token expired', 'failed to refresh authentication token',
    'account has been deactivated', 'http 401', 'status 401', '"code":401',
    'http 403', 'status 403', '"code":403',
)
USAGE_MARKERS = (
    'rate limit', 'rate_limit', 'too many requests', 'insufficient_quota',
    'usage limit', 'usage_limit', 'quota exceeded', 'billing limit',
    'exceeded your current quota', 'you have hit your limit', 'you have reached your limit',
    'limit reached', 'monthly limit', 'payment required',
    'http 429', 'status 429',
    '"code":429',
)


def stop_if_account_blocked(output):
    """Raise a run-stopping error for known authentication or quota failures."""
    text = str(output).casefold()
    if any(marker in text for marker in AUTH_MARKERS):
        raise RunHaltError('Authentication prevented a model call; run stopped immediately')
    if any(marker in text for marker in USAGE_MARKERS):
        raise RunHaltError('Provider usage limit prevented a model call; run stopped immediately')
