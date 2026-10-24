"""Validate recorded answers against reviewed scores and regenerate Scheme A metrics."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'evaluations/book_borrow'


def main():
    dataset = json.loads((BASE / 'questions.json').read_text(encoding='utf-8'))
    gold = json.loads((BASE / 'gold.json').read_text(encoding='utf-8'))
    prompt = json.loads((BASE / 'prompt_a.json').read_text(encoding='utf-8'))
    scores = json.loads((BASE / 'runs/a_20261024_scores.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for split in ('dev', 'eval')
            for line in (BASE / f'runs/a_20261024_{split}.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = {q['question_id']: q for q in dataset['questions']}
    answers = {r['question_id']: r for r in rows}
    reviews = {r['question_id']: r for r in scores['reviews']}
    if len(answers) != len(rows) or set(answers) != set(expected) or set(reviews) != set(expected):
        raise ValueError('Missing, extra or duplicate question ids')
    for question_id, row in answers.items():
        q = expected[question_id]
        review = reviews[question_id]
        expected_messages = [{'role': 'system', 'content': prompt['system']},
                             {'role': 'user', 'content': prompt['user_prefix'] + q['question']}]
        if row['messages'] != expected_messages or row['split'] != q['split']:
            raise ValueError('Request must contain only the frozen prompt and current question')
        if review['answer_sha256'] != hashlib.sha256(row.get('answer', '').encode()).hexdigest():
            raise ValueError('Reviewed answer hash mismatch')
        if row['source_commit_sha'] != dataset['source_commit_sha']:
            raise ValueError('Source snapshot mismatch')
        if row['status'] != 'ok' and review['correctness'] != 'not_scored':
            raise ValueError('Failed or incomplete calls must not be scored')
    negative = {q['question_id'] for q in gold['questions'] if q['category'] == 'insufficient_evidence'}
    result = {'source_commit_sha': dataset['source_commit_sha'],
              'reviewer': scores['reviewer'], 'team_review_status': scores['team_review_status'],
              'requested_models': sorted({r['config']['model'] for r in rows}),
              'returned_models': sorted({r.get('returned_model', '') for r in rows}),
              'retrieval_recall_at_k': None, 'source_citation_coverage': None, 'groups': {}}
    for group in ('dev', 'eval', 'all'):
        selected = [r for r in rows if group == 'all' or r['split'] == group]
        valid = [r for r in selected if r['status'] == 'ok']
        counts = Counter(reviews[r['question_id']]['correctness'] for r in selected)
        business = [r for r in valid if r['question_id'] not in negative]
        latencies = [r['latency_seconds'] for r in valid]
        usage = {key: sum(r.get('usage', {}).get(key, 0) for r in selected)
                 for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        result['groups'][group] = {
            'planned': len(selected), 'successful_calls': len(valid),
            'errors': sum(r['status'] == 'error' for r in selected),
            'incomplete': sum(r['status'] == 'incomplete' for r in selected),
            'counts': {key: counts[key] for key in ('correct','partial','incorrect','abstained','not_scored')},
            'strict_accuracy': counts['correct'] / len(valid) if valid else None,
            'correct_over_planned': counts['correct'] / len(selected),
            'business_questions': len(business),
            'business_correct': sum(reviews[r['question_id']]['correctness'] == 'correct' for r in business),
            'unsupported_project_claims': sum(reviews[r['question_id']]['unsupported_project_claim'] for r in valid),
            'unsupported_behavior_claims': sum(reviews[r['question_id']]['unsupported_behavior_claim'] for r in valid),
            'mean_latency_seconds': round(statistics.mean(latencies), 3) if latencies else None,
            'median_latency_seconds': round(statistics.median(latencies), 3) if latencies else None,
            'min_latency_seconds': min(latencies) if latencies else None,
            'max_latency_seconds': max(latencies) if latencies else None,
            'sum_request_latency_seconds': round(sum(latencies), 3), 'usage': usage}
    output = BASE / 'runs/a_20261024_summary.json'
    output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
