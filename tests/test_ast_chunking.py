import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bizcodeqa.platform import chunking, qa, sample, stores


class AstChunkTests(unittest.TestCase):
    def test_sample_spans_ids_and_compounds(self):
        fixture=sample.load_sample()
        chunks=chunking.ast_chunks(fixture)
        self.assertEqual(chunks,chunking.ast_chunks(fixture))
        source=(sample.ROOT/chunks[0]['file_path']).read_bytes().replace(b'\r\n',b'\n')
        known={e['symbol_id'] for e in fixture['entities']}
        self.assertGreater(len(chunks),20)
        self.assertEqual(len(chunks),len({c['chunk_id'] for c in chunks}))
        self.assertTrue(any(c['ast_node_type']=='if_statement' for c in chunks))
        self.assertEqual(sum(c['ast_node_type']=='field_declaration' for c in chunks),8)
        end=0
        for c in chunks:
            self.assertGreaterEqual(c['source_start_byte'],end)
            end=c['source_end_byte']
            self.assertEqual(c['code'],source[c['source_start_byte']:end].decode())
            self.assertEqual(c['code'],source.decode()[c['source_start_char']:c['source_end_char']])
            self.assertEqual(c['start_line'],source[:c['source_start_byte']].count(b'\n')+1)
            self.assertEqual(c['end_line'],source[:end-1].count(b'\n')+1)
            self.assertTrue(set(c['symbol_ids'])<=known)

    def custom(self,code):
        fixture=copy.deepcopy(sample.load_sample())
        file=next(e for e in fixture['entities'] if e['entity_type']=='File')
        method=next(e for e in fixture['entities'] if e['entity_type']=='Method')
        file['file_path']='Demo.java';file['content_sha256']=hashlib.sha256(code.encode()).hexdigest()
        method.update(file_path='Demo.java',start_line=1,end_line=code.count('\n')+1)
        fixture['entities']=[file,method]
        return fixture

    def test_nested_control_flow_strings_and_empty_method(self):
        code='class Demo { void f() { String s="中文;{}"; if(true) { f(); } else { f(); } for(int i=0;i<2;i++){ f(); } } }'
        with tempfile.TemporaryDirectory() as folder,patch.object(chunking,'ROOT',Path(folder)):
            Path(folder,'Demo.java').write_text(code,encoding='utf-8')
            chunks=chunking.ast_chunks(self.custom(code))
            self.assertEqual([c['ast_node_type'] for c in chunks],['local_variable_declaration','if_statement','for_statement'])
            self.assertIn('else',chunks[1]['code'])
            self.assertIn('i++',chunks[2]['code'])
            code='class Demo { void f() {} }'
            Path(folder,'Demo.java').write_text(code)
            self.assertEqual(chunking.ast_chunks(self.custom(code))[0]['ast_node_type'],'method_declaration')

    def test_invalid_java_and_changed_source_rejected(self):
        code='class Demo { void f( { }'
        with tempfile.TemporaryDirectory() as folder,patch.object(chunking,'ROOT',Path(folder)):
            Path(folder,'Demo.java').write_text(code)
            fixture=self.custom(code)
            with self.assertRaisesRegex(ValueError,'语法错误'):
                chunking.ast_chunks(fixture)
            Path(folder,'Demo.java').write_text('class Changed {}')
            with self.assertRaisesRegex(ValueError,'快照'):
                chunking.ast_chunks(fixture)

    def test_profile_isolation_discovery_and_no_fallback(self):
        config=chunking.chunk_config('ast')
        self.assertEqual(config,chunking.chunk_config('ast',900,0))
        with tempfile.TemporaryDirectory() as folder,patch.object(stores,'STATE',Path(folder)/'index.json'):
            stores.STATE.write_text(json.dumps({'chunks':[],'collection':'method','commit_sha':'test'}))
            self.assertIsNone(stores.state('ast'))
            with patch.object(qa,'chat') as chat,self.assertRaises(stores.ServiceError):
                qa.answer('B','question',chunking_strategy='ast')
            chat.assert_not_called()
            stores.index_path('ast').write_text(json.dumps({'chunks':[],'chunking':config,'collection':'ast','commit_sha':'test'}))
            self.assertEqual(stores.state('ast')['collection'],'ast')
            self.assertEqual({p['profile_id'] for p in stores.index_profiles()},{'method','ast_statement_v1'})

    def test_ast_routing_and_prompt_preserve_selected_units(self):
        fixture=sample.load_sample()
        chunks=chunking.ast_chunks(fixture)
        index={**fixture['metadata'],'chunks':chunks,'chunking':chunking.chunk_config('ast'),
               'collection':'ast','query_instruction':'query','embedding_digest':'digest','graph_ready':True}
        response={'content':'示例 [E1]','model':'test','usage':{},'finish_reason':'stop'}
        with patch.object(qa,'state',return_value=index),patch.object(qa,'load_sample',return_value=fixture),patch.object(qa,'vector_search',return_value=[dict(chunks[0],origin='vector',score=.8)]),patch.object(qa,'graph_expand',return_value=([dict(chunks[-1],origin='graph',score=None)],[])) as expand,patch.object(qa,'chat',return_value=response):
            for mode in ('B','C'):
                result=qa.answer(mode,'问题',chunking_strategy='ast')
                self.assertEqual(result['chunking']['profile_id'],'ast_statement_v1')
                self.assertIn('AST field_declaration',result['messages'][1]['content'])
                self.assertEqual(len(result['evidence']),1 if mode=='B' else 2)
                self.assertTrue(all(c['chunking_strategy']=='ast' for c in result['evidence']))
            self.assertEqual(expand.call_count,1)
