"""Read-only independent audit of the saved 210 records and reviewed scores.
Run from any directory: python outputs/evaluation_20261119/recompute_metrics.py
Does not call LLMs, databases, or modify history.
"""
import hashlib
import json
import re
import statistics
from pathlib import Path

folder=Path(__file__).resolve().parent
root=folder.parents[1]
rows=json.loads((folder/'records_210.json').read_text(encoding='utf-8'))
scored=json.loads((folder/'records_scored.json').read_text(encoding='utf-8'))
manifest=json.loads((folder/'audit_manifest.json').read_text(encoding='utf-8'))
assert hashlib.sha256((folder/'records_210.json').read_bytes()).hexdigest()==manifest['raw_selected_sha256']
assert len(rows)==210 and len({r['id'] for r in rows})==210
lookup={r['id']:r for r in scored}
assert set(lookup)=={r['id'] for r in rows}
source=(root/'samples/book_borrow/src/experiment/bookBorrowSystem.java').read_bytes().replace(b'\r\n',b'\n')
assert hashlib.sha256(source).hexdigest()==manifest['source_sha256']
lines=source.splitlines(keepends=True);off=[0]
for line in lines:off.append(off[-1]+len(line))
gold=json.loads((folder/'gold_units.json').read_text(encoding='utf-8'))
assert sum(map(len,gold.values()))==36
for units in gold.values():
 for unit in units:
  expected=[]
  for lineno in range(unit['start_line'],unit['end_line']+1):
   line=lines[lineno-1];s=line.strip()
   if not s or s.startswith(b'//') or all(chr(c) in '{};' for c in s):continue
   expected.extend(off[lineno-1]+j for j,c in enumerate(line) if chr(c) not in ' \t\r\n')
  assert expected==unit['required']
for row in rows:
 r=lookup[row['id']]
 assert r['answer']==row['answer'] and r['messages']==row['messages']
 assert r['evidence']==row['evidence'] and r['created_at']==row['created_at']
 intervals=[]
 for e in row['evidence']:
  code=e['code'].encode();start=e.get('source_start_byte')
  if start is None:start=source.find(code,off[e['start_line']-1],off[e['end_line']])
  end=start+len(code)
  assert start>=0 and source[start:end]==code
  assert hashlib.sha256(code).hexdigest()==e['content_sha256']
  assert e['code'] in row['messages'][1]['content']
  intervals.append((start,end,e['origin']))
 if row['mode']!='A':
  assert sum(o=='vector' for _,_,o in intervals)==row['top_k']==5
  for stage,key in [('final','final_hits'),('vector','vector_hits')]:
   hits=[u['id'] for u in gold[r['eval_question_id']] if all(any(a<=p<b for a,b,o in intervals if stage=='final' or o=='vector') for p in u['required'])]
   assert hits==r['eval_recall'][key]
summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
for item in summary:
 group=[r for r in scored if r['eval_strategy']==item['strategy'] and r['mode']==item['mode']]
 assert len(group)==14 and len({r['eval_question_id'] for r in group})==14
 scores=[r['eval_answer_score'] for r in group]
 assert scores.count(2)==item['correct'] and scores.count(1)==item['partial'] and scores.count(0)==item['incorrect_or_unanswered']
 assert sum(s==2 for s in scores)/14==item['accuracy']
 if item['mode']!='A':
  assert sum(len(r['eval_recall']['final_hits']) for r in group)/36==item['final_recall_micro']
  assert statistics.mean(len(r['eval_recall']['final_hits'])/r['eval_recall']['gold_count'] for r in group)==item['final_recall_macro']
print('PASS: 210 immutable records, 36 gold units, 868 exact source objects, 15 group summaries; answer judgments remain reviewable initial scores.')
