"""Minimal Chat Completions client; never prints keys or upstream error bodies."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from .config import required


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def chat(messages):
    base = required('LLM_BASE_URL').rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        raise ValueError('LLM_BASE_URL must be an HTTP(S) URL')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('LLM_BASE_URL cannot contain credentials, query or fragment')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', 'host.docker.internal'):
        raise ValueError('Remote LLM endpoints must use HTTPS')
    key = required('LLM_API_KEY')
    model = required('LLM_MODEL')
    timeout = float(os.getenv('LLM_TIMEOUT_SECONDS', '60'))
    tokens = int(os.getenv('LLM_MAX_TOKENS', '128'))
    if not 0 < timeout <= 300 or not 1 <= tokens <= 4096:
        raise ValueError('Invalid LLM timeout or token limit')
    payload = {'model': model, 'messages': messages, 'max_tokens': tokens, 'stream': False}
    thinking = os.getenv('LLM_THINKING', '').strip()
    if thinking:
        if thinking not in ('enabled', 'disabled'):
            raise ValueError('Invalid LLM thinking mode')
        payload['thinking'] = {'type': thinking}
    request = urllib.request.Request(
        base + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        exc.close()
        hints = {401: 'check API key', 403: 'check model permission', 404: 'check URL/model',
                 429: 'rate limit or quota', 400: 'check model request parameters'}
        raise RuntimeError(f'LLM HTTP {exc.code}: {hints.get(exc.code, "provider request failed")}') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('LLM network/TLS/timeout failure; check connectivity') from None
    try:
        content = data['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError('LLM returned no non-empty text completion') from None
    return {'content': content, 'model': data.get('model', model), 'usage': data.get('usage', {})}
