import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tokenizers import Tokenizer
from bizcodeqa.platform import chunking,qa,sample,stores

ASSET=sample.ROOT/'assets/tokenizers/qwen3_embedding/tokenizer.json'

class TokenChunkTests(unittest.TestCase):
    def test_sample_exact_coverage_true_counts_overlap_and_ids(self):
        fixture=sample.load_sample();tok=Tokenizer.from_file(str(ASSET))
        source=(sample.ROOT/fixture['chunks'][0]['file_path']).read_bytes().replace(b'\r\n',b'\n')
        for size,overlap in [(64,0),(64,32),(800,100),(2048,0)]:
            pieces=chunking.token_chunks(fixture,size,overlap)
            self.assertEqual(pieces,chunking.token_chunks(fixture,size,overlap))
            covered=0
            for c in pieces:
                self.assertLessEqual(c['source_start_char'],covered)
                self.assertGreater(c['source_end_char'],covered)
                self.assertEqual(c['code'],source[c['source_start_byte']:c['source_end_byte']].decode())
                self.assertEqual(c['code'],source.decode()[c['source_start_char']:c['source_end_char']])
                self.assertEqual(c['token_count'],len(tok.encode(c['code'],add_special_tokens=False).ids))
                self.assertLessEqual(c['token_count'],size)
                self.assertEqual(c['content_sha256'],hashlib.sha256(c['code'].encode()).hexdigest())
                covered=c['source_end_char']
            self.assertEqual(covered,len(source.decode()))
            self.assertEqual(len(pieces),len({c['chunk_id'] for c in pieces}))

    def test_multibyte_unicode_and_repeated_whitespace_are_preserved(self):
        code='class Demo { String value="'+('中文𠮷🙂é é ; {}\n\t  '*100)+'"; }'
        fixture=copy.deepcopy(sample.load_sample())
        file=next(e for e in fixture['entities'] if e['entity_type']=='File')
        file['file_path']='Demo.java';file['content_sha256']=hashlib.sha256(code.encode()).hexdigest()
        fixture['entities']=[file]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Demo.java').write_text(code,encoding='utf-8')
            asset=root/'assets/tokenizers/qwen3_embedding';asset.mkdir(parents=True)
            (asset/'tokenizer.json').write_bytes(ASSET.read_bytes())
            with patch.object(chunking,'ROOT',root):
                pieces=chunking.token_chunks(fixture,64,0)
                self.assertEqual(''.join(c['code'] for c in pieces),code)
                (asset/'tokenizer.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'摘要'):
                    chunking.token_chunks(fixture,64,0)

    def test_config_isolation_and_missing_index_never_falls_back(self):
        for size,overlap in [(True,0),(63,0),(2049,0),(100,51),(100,-1),(100,1.5)]:
            with self.assertRaises(ValueError):chunking.chunk_config('token',size,overlap)
        config=chunking.chunk_config('token',800,100)
        with tempfile.TemporaryDirectory() as folder,patch.object(stores,'STATE',Path(folder)/'index.json'):
            stores.STATE.write_text(json.dumps({'chunks':[],'collection':'method','commit_sha':'test'}))
            self.assertIsNone(stores.state('token'))
            with patch.object(qa,'chat') as chat,self.assertRaises(stores.ServiceError):
                qa.answer('B','question',chunking_strategy='token')
            chat.assert_not_called()
            stores.index_path('token').write_text(json.dumps({'chunks':[],'chunking':config,'collection':'tokens','commit_sha':'test'}))
            self.assertEqual(stores.state('token')['collection'],'tokens')
            self.assertIsNone(stores.state('token',512,64))
            self.assertEqual({p['profile_id'] for p in stores.index_profiles()},{'method','token_qwen3_v1_800_100'})

    def test_selected_strategy_in_bc_prompts_and_metadata(self):
        fixture=sample.load_sample();pieces=chunking.token_chunks(fixture)
        index={**fixture['metadata'],'chunks':pieces,'chunking':chunking.chunk_config('token'),
               'collection':'tokens','query_instruction':'query','embedding_digest':'digest','graph_ready':True}
        response={'content':'示例 [E1]','model':'test','usage':{},'finish_reason':'stop'}
        with patch.object(qa,'state',return_value=index),patch.object(qa,'load_sample',return_value=fixture),patch.object(qa,'vector_search',return_value=[dict(pieces[0],origin='vector',score=.8)]),patch.object(qa,'graph_expand',return_value=([dict(pieces[-1],origin='graph',score=None)],[])) as expand,patch.object(qa,'chat',return_value=response):
            for mode in ('B','C'):
                r=qa.answer(mode,'问题',chunking_strategy='token')
                self.assertEqual(r['chunking']['strategy'],'token')
                self.assertIn('Token 窗口',r['messages'][1]['content'])
                self.assertTrue(all(c['chunking_strategy']=='token' for c in r['evidence']))
            self.assertEqual(expand.call_count,1)
