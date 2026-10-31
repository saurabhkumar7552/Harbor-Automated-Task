"""Recognize provider account and usage blocks that must stop a generation run."""
import json
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
    """Inspect provider errors only; never scan successful structured task content.

    Plain text is accepted for transport failures and explicit error messages.
    Callers must not pass successful unstructured model answers here.
    """
    errors = []
    raw = str(output)
    try:
        records = [json.loads(raw)]
    except (ValueError, TypeError):
        records = []
        for line in raw.splitlines():
            try:
                records.append(json.loads(line))
            except (ValueError, TypeError):
                errors.append(line)
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get('type') in ('error', 'turn.failed'):
            errors.append(json.dumps(record))
        elif record.get('is_error') or record.get('error'):
            errors.append(json.dumps(record.get('error') or record.get('errors') or
                                     record.get('result') or record.get('message') or record))
    text = '\n'.join(errors).casefold()
    if any(marker in text for marker in AUTH_MARKERS):
        raise RunHaltError('Authentication prevented a model call; run stopped immediately')
    if any(marker in text for marker in USAGE_MARKERS):
        raise RunHaltError('Provider usage limit prevented a model call; run stopped immediately')
