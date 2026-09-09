import os
from pathlib import Path


def load_env(path=Path('.env')):
    """Simple KEY=value file; process environment wins. No shell evaluation."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not key.strip().isidentifier():
            raise ValueError('Invalid .env line (expected KEY=value)')
        os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def required(name):
    value = os.getenv(name, '').strip()
    if not value or value == 'GENERATE_ME':
        raise ValueError(f'Missing configuration: {name}')
    return value
