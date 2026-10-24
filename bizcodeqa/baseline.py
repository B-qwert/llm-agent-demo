"""Scheme A: independent questions only; no source, gold answers or retrieval."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from .config import load_env, required
from .llm import chat


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'evaluations/book_borrow/questions.json'
PROMPT = ROOT / 'evaluations/book_borrow/prompt_a.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_inputs(dataset_path, prompt_path):
    dataset_bytes, prompt_bytes = dataset_path.read_bytes(), prompt_path.read_bytes()
    dataset = json.loads(dataset_bytes)
    prompt = json.loads(prompt_bytes)
    ids = set()
    for item in dataset['questions']:
        if set(item) != {'question_id', 'question', 'split'}:
            raise ValueError('Question file must contain only id, question and split')
        if item['question_id'] in ids or item['split'] not in ('dev', 'eval'):
            raise ValueError('Invalid question id or split')
        if not isinstance(item['question'], str) or not item['question'].strip():
            raise ValueError('Question text is required')
        ids.add(item['question_id'])
    return dataset, prompt, digest(dataset_bytes), digest(prompt_bytes)


def messages_for(question, prompt):
    return [{'role': 'system', 'content': prompt['system']},
            {'role': 'user', 'content': prompt['user_prefix'] + question['question']}]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['dev', 'eval', 'all'], default='dev')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/baseline_a.jsonl')
    parser.add_argument('--execute', action='store_true', help='Make real, paid API requests')
    parser.add_argument('--resume', action='store_true', help='Skip recorded attempts, including failures')
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args(argv)
    if not 1 <= args.max_tokens <= 4096 or not 0 < args.timeout <= 300:
        parser.error('Invalid token or timeout budget')
    dataset, prompt, dataset_hash, prompt_hash = read_inputs(DATASET, PROMPT)
    selected = [q for q in dataset['questions'] if args.split == 'all' or q['split'] == args.split]
    if not args.execute:
        print(json.dumps({'dry_run': True, 'question_count': len(selected),
                          'dataset_sha256': dataset_hash, 'prompt_sha256': prompt_hash,
                          'requests': [{'question_id': q['question_id'],
                                        'messages': messages_for(q, prompt)} for q in selected]},
                         ensure_ascii=False, indent=2))
        return 0
    load_env(ROOT / '.env')
    # Explicit experiment budgets; never modify the user's .env.
    os.environ['LLM_MAX_TOKENS'] = str(args.max_tokens)
    os.environ['LLM_TIMEOUT_SECONDS'] = str(args.timeout)
    os.environ['LLM_THINKING'] = 'disabled'
    config = {'base_url': required('LLM_BASE_URL').rstrip('/'), 'model': required('LLM_MODEL'),
              'max_tokens': args.max_tokens, 'timeout_seconds': args.timeout,
              'thinking': 'disabled', 'stream': False,
              'temperature': 'provider_default_not_explicitly_set',
              'seed': 'not_set', 'retries': 0}
    required('LLM_API_KEY')
    # Validate endpoint before writing metadata. Keys, credentials and URLs with queries are never logged.
    from urllib.parse import urlsplit
    url = urlsplit(config['base_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Baseline requires an HTTPS endpoint without credentials, query or fragment')
    fingerprint = digest(json.dumps({'dataset': dataset_hash, 'prompt': prompt_hash,
                                    'config': config}, sort_keys=True).encode())
    existing = []
    if args.output.exists():
        if not args.resume:
            raise ValueError('Output exists; choose another file or use --resume')
        existing = [json.loads(line) for line in args.output.read_text(encoding='utf-8').splitlines()]
        if any(row['experiment_fingerprint'] != fingerprint for row in existing):
            raise ValueError('Cannot resume with different questions, prompt or configuration')
        if len({row['question_id'] for row in existing}) != len(existing):
            raise ValueError('Duplicate question ids in output')
    seen = {row['question_id'] for row in existing}
    implementation_commit = subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    failed = any(row['status'] != 'ok' for row in existing)
    for question in selected:
        if question['question_id'] in seen:
            continue
        row = {'scheme': 'A', 'question_id': question['question_id'], 'split': question['split'],
               'question': question['question'], 'started_at_utc': timestamp(),
               'source_commit_sha': dataset['source_commit_sha'],
               'implementation_commit_sha': implementation_commit,
               'dataset_sha256': dataset_hash, 'prompt_sha256': prompt_hash,
               'experiment_fingerprint': fingerprint, 'config': config,
               'messages': messages_for(question, prompt), 'attempt': 1}
        start = time.perf_counter()
        try:
            result = chat(row['messages'])
            row.update({'status': 'ok' if result['finish_reason'] == 'stop' else 'incomplete',
                        'answer': result['content'], 'returned_model': result['model'],
                        'usage': result['usage'], 'finish_reason': result['finish_reason']})
            failed = failed or row['status'] != 'ok'
        except (RuntimeError, ValueError, OSError) as exc:
            # Client's HTTP/network messages are redacted. Never print arbitrary response bodies.
            row.update({'status': 'error', 'error_type': type(exc).__name__,
                        'error': 'API request failed; no upstream body or credentials recorded'})
            failed = True
        row['latency_seconds'] = round(time.perf_counter() - start, 3)
        row['finished_at_utc'] = timestamp()
        with args.output.open('a', encoding='utf-8', newline='\n') as output:
            output.write(json.dumps(row, ensure_ascii=False) + '\n')
            output.flush()
        print(f"{row['question_id']}: {row['status']} ({row['latency_seconds']}s)", flush=True)
        if row['status'] == 'error':
            # Stop on authentication, quota or connectivity failures; no retry cost cascade.
            break
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
