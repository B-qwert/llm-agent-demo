"""Create local configuration once; never overwrite existing credentials."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env already exists; preserved.')
else:
    text = (root / '.env.example').read_text(encoding='utf-8')
    while 'GENERATE_ME' in text:
        text = text.replace('GENERATE_ME', secrets.token_hex(20), 1)
    with target.open('x', encoding='utf-8') as file:
        file.write(text)
    print('.env created with random local database passwords; fill LLM settings locally.')
