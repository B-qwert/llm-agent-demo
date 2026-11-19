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

class ParagraphChunkTests(unittest.TestCase):
    def fixture(self,code):
        fixture=copy.deepcopy(sample.load_sample())
        file=next(e for e in fixture['entities'] if e['entity_type']=='File')
        file.update(file_path='Demo.java',content_sha256=hashlib.sha256(code.encode()).hexdigest())
        fixture['entities']=[file]
        return fixture

    def test_blank_lines_tabs_comments_and_last_line(self):
        code='\n \t\n// 注释\nint a=1;\n\t\n\n  int b=2;'
        with tempfile.TemporaryDirectory() as folder,patch.object(chunking,'ROOT',Path(folder)):
            Path(folder,'Demo.java').write_text(code,encoding='utf-8')
            pieces=chunking.paragraph_chunks(self.fixture(code))
        self.assertEqual([c['code'] for c in pieces],['// 注释\nint a=1;\n','  int b=2;'])
        self.assertEqual([(c['start_line'],c['end_line']) for c in pieces],[(3,4),(7,7)])

    def test_very_long_paragraph_is_kept_whole_without_tokenizer(self):
        code=('// 中文𠮷🙂 '+('int value=123; '*3000)+'\n')
        tok=Tokenizer.from_file(str(ASSET))
        with tempfile.TemporaryDirectory() as folder,patch.object(chunking,'ROOT',Path(folder)):
            Path(folder,'Demo.java').write_text(code,encoding='utf-8')
            pieces=chunking.paragraph_chunks(self.fixture(code))
        self.assertEqual(len(pieces),1)
        self.assertEqual(''.join(c['code'] for c in pieces),code)
        self.assertTrue(all(c['paragraph_index']==0 for c in pieces))
        self.assertGreater(len(tok.encode(pieces[0]['code']).ids),2048)
        self.assertNotIn('token_count',pieces[0])

    def test_sample_exact_offsets_ids_and_symbol_mapping(self):
        fixture=sample.load_sample();pieces=chunking.paragraph_chunks(fixture)
        self.assertEqual(pieces,chunking.paragraph_chunks(fixture))
        source=(sample.ROOT/pieces[0]['file_path']).read_bytes().replace(b'\r\n',b'\n')
        actual={e['symbol_id'] for e in fixture['entities']}
        self.assertEqual(len(pieces),15)
        self.assertEqual(len(pieces),len({c['chunk_id'] for c in pieces}))
        end=0
        for c in pieces:
            self.assertGreaterEqual(c['source_start_byte'],end)
            end=c['source_end_byte']
            self.assertEqual(c['code'],source[c['source_start_byte']:end].decode())
            self.assertEqual(c['code'],source.decode()[c['source_start_char']:c['source_end_char']])
            self.assertTrue(set(c['symbol_ids'])<=actual)
            self.assertTrue(c['code'].strip())

    def test_empty_changed_source_rejected_and_no_size_parameters(self):
        self.assertEqual(chunking.chunk_config('paragraph'),chunking.chunk_config('paragraph',1,-1))
        self.assertNotIn('chunk_size',chunking.chunk_config('paragraph'))
        code='\n \t\n'
        with tempfile.TemporaryDirectory() as folder,patch.object(chunking,'ROOT',Path(folder)):
            Path(folder,'Demo.java').write_text(code)
            fixture=self.fixture(code)
            with self.assertRaisesRegex(ValueError,'非空段落'):chunking.paragraph_chunks(fixture)
            Path(folder,'Demo.java').write_text('changed')
            with self.assertRaisesRegex(ValueError,'快照'):chunking.paragraph_chunks(fixture)

    def test_profile_isolation_and_selected_bc_evidence(self):
        config=chunking.chunk_config('paragraph')
        self.assertNotIn('chunk_overlap',config)
        with tempfile.TemporaryDirectory() as folder,patch.object(stores,'STATE',Path(folder)/'index.json'):
            self.assertIsNone(stores.state('paragraph'))
            with patch.object(qa,'chat') as chat,self.assertRaises(stores.ServiceError):qa.answer('B','question',chunking_strategy='paragraph')
            chat.assert_not_called()
            stores.index_path('paragraph').write_text(json.dumps({'chunks':[],'chunking':config,'collection':'paragraphs','commit_sha':'test'}))
            self.assertEqual(stores.state('paragraph')['collection'],'paragraphs')
            self.assertEqual(stores.state('paragraph',512)['collection'],'paragraphs')
            self.assertEqual(stores.index_profiles()[0]['profile_id'],'paragraph_blank_v1')
        fixture=sample.load_sample();pieces=chunking.paragraph_chunks(fixture)
        index={**fixture['metadata'],'chunks':pieces,'chunking':config,'collection':'paragraphs','query_instruction':'query','embedding_digest':'digest','graph_ready':True}
        response={'content':'示例 [E1]','model':'test','usage':{},'finish_reason':'stop'}
        with patch.object(qa,'state',return_value=index),patch.object(qa,'load_sample',return_value=fixture),patch.object(qa,'vector_search',return_value=[dict(pieces[0],origin='vector',score=.8)]),patch.object(qa,'graph_expand',return_value=([dict(pieces[-1],origin='graph',score=None)],[])),patch.object(qa,'chat',return_value=response):
            for mode in ('B','C'):
                r=qa.answer(mode,'问题',chunking_strategy='paragraph')
                self.assertEqual(r['chunking']['strategy'],'paragraph')
                self.assertIn('空行段落',r['messages'][1]['content'])
                self.assertTrue(all(c['chunking_strategy']=='paragraph' for c in r['evidence']))
