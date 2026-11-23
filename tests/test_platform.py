import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bizcodeqa.config import load_env
from bizcodeqa.platform import qa, sample, server, stores
from bizcodeqa.platform.stores import ServiceError


class SampleTests(unittest.TestCase):
    def test_fixture_ids_references_and_utf8_locations(self):
        fixture=sample.load_sample()
        self.assertEqual(len(fixture['entities']),23)
        self.assertEqual(len(fixture['chunks']),20)
        self.assertEqual(len(fixture['relationships']),80)
        ids={e['symbol_id'] for e in fixture['entities']}
        again=sample.load_sample()
        self.assertEqual(fixture,again)
        source=(sample.ROOT/fixture['chunks'][0]['file_path']).read_bytes().replace(b'\r\n',b'\n')
        names={e['symbol_id']:e['name'] for e in fixture['entities']}
        for rel in fixture['relationships']:
            self.assertIn(rel['source_symbol_id'],ids)
            self.assertIn(rel['target_symbol_id'],ids)
            if rel['relationship_type'] in ('CALLS','REFERENCES'):
                occurrence=source[rel['source_start_byte']:rel['source_end_byte']].decode('utf-8')
                self.assertIn(names[rel['target_symbol_id']],occurrence)
                self.assertEqual(source[:rel['source_start_byte']].count(b'\n')+1,rel['source_start_line'])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=sample.load_sample()
        self.chunk=self.fixture['chunks'][8]
        self.index={**self.fixture['metadata'],'graph_ready':True,'chunks':self.fixture['chunks'],
                    'query_instruction':'test instruction','embedding_digest':'test-digest','collection':'test_collection'}
        self.response={'content':'据[E1]说明。','model':'test-model','usage':{},'finish_reason':'stop'}

    def test_a_does_not_read_source_or_query_stores(self):
        with patch.object(qa,'state',side_effect=AssertionError('index accessed')), \
             patch.object(qa,'load_sample',side_effect=AssertionError('source accessed')), \
             patch.object(qa,'vector_search',side_effect=AssertionError('vector accessed')), \
             patch.object(qa,'graph_expand',side_effect=AssertionError('graph accessed')), \
             patch.object(qa,'chat',return_value=self.response) as chat:
            result=qa.answer('A','借书条件？')
        self.assertEqual(result['evidence'],[])
        self.assertEqual(result['components'],['DeepSeek'])
        self.assertNotIn(self.chunk['code'],chat.call_args.args[0][1]['content'])

    def test_b_works_without_graph_and_only_current_question(self):
        with patch.object(qa,'state',return_value=self.index), \
             patch.object(qa,'load_sample',return_value=self.fixture), \
             patch.object(qa,'vector_search',return_value=[dict(self.chunk,origin='vector',score=.8)]), \
             patch.object(qa,'graph_expand',side_effect=AssertionError('B queried graph')), \
             patch.object(qa,'chat',return_value=self.response) as chat:
            result=qa.answer('B','借书条件？',2)
        self.assertNotIn('Neo4j',result['components'])
        self.assertIn(self.chunk['code'],chat.call_args.args[0][1]['content'])
        self.assertEqual(len(chat.call_args.args[0]),2)

    def test_c_keeps_graph_failure_visible(self):
        with patch.object(qa,'state',return_value=self.index), \
             patch.object(qa,'load_sample',return_value=self.fixture), \
             patch.object(qa,'vector_search',return_value=[]), \
             patch.object(qa,'graph_expand',side_effect=ServiceError('graph offline')), \
             patch.object(qa,'chat') as chat:
            with self.assertRaises(ServiceError):
                qa.answer('C','借书条件？')
            chat.assert_not_called()

    def test_c_adds_evidence_and_checks_invented_citation(self):
        with patch.object(qa,'state',return_value=self.index), \
             patch.object(qa,'load_sample',return_value=self.fixture), \
             patch.object(qa,'vector_search',return_value=[dict(self.chunk,origin='vector',score=.8)]), \
             patch.object(qa,'graph_expand',return_value=([dict(self.fixture['chunks'][0],origin='graph',score=None)],[])), \
             patch.object(qa,'chat',return_value={**self.response,'content':'[E999]'}):
            result=qa.answer('C','借书条件？')
        self.assertEqual(len(result['evidence']),2)
        self.assertIn('Neo4j',result['components'])
        self.assertTrue(any('E999' in w for w in result['warnings']))

    def test_invalid_inputs_rejected_before_model(self):
        with patch.object(qa,'chat') as chat:
            for mode,question,k in [('D','问题',3),('A','',3),('B','问题',True),('A','x'*2001,3)]:
                with self.assertRaises(ValueError):
                    qa.answer(mode,question,k)
            chat.assert_not_called()


class VectorAdapterTests(unittest.TestCase):
    def test_embedding_model_loaded_from_env_file_after_import(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {}, clear=True):
            env_file = Path(folder) / '.env'
            env_file.write_text('EMBEDDING_MODEL=custom-embedding:1\n', encoding='utf-8')
            load_env(env_file)

            with patch.object(stores, 'ollama', side_effect=[
                {'models': [{'name': 'custom-embedding:1', 'digest': 'custom-digest'}]},
                {'embeddings': [[1.0, 0.0]]},
            ]) as ollama:
                self.assertEqual(stores.model_digest(), 'custom-digest')
                self.assertEqual(stores.embed(['question']), [[1.0, 0.0]])

            ollama.assert_called_with('/api/embed', {
                'model': 'custom-embedding:1', 'input': ['question'], 'truncate': False,
            })

    def test_custom_primary_key_and_snapshot_filter(self):
        fixture=sample.load_sample()
        chunk=fixture['chunks'][8]
        index={**fixture['metadata'],'embedding_digest':'digest','embedding_dimension':2,
               'query_instruction':'instruction: ','collection':'test_collection','chunks':[chunk]}
        from unittest.mock import MagicMock
        client=MagicMock()
        client.search.return_value=[[{'chunk_id':chunk['chunk_id'],'distance':.8}]]
        with patch.object(stores,'model_digest',return_value='digest'), \
             patch.object(stores,'embed',return_value=[[1.,0.]]), \
             patch.object(stores,'milvus',return_value=client):
            results=stores.vector_search('test question',index,5)
        self.assertEqual(results[0]['code'],chunk['code'])
        query_filter=client.search.call_args.kwargs['filter']
        self.assertIn(index['snapshot_id'],query_filter)
        self.assertIn(index['repository_id'],query_filter)
        self.assertIn('entity_type == "Method"',query_filter)
        client.close.assert_called_once()

    def test_changed_model_never_queries_existing_collection(self):
        with patch.object(stores,'model_digest',return_value='changed'), \
             patch.object(stores,'milvus') as client:
            with self.assertRaises(ServiceError):
                stores.vector_search('question',{'embedding_digest':'old'},5)
            client.assert_not_called()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_ui_and_secret_files_not_served(self):
        with urlopen(self.base+'/',timeout=3) as response:
            self.assertIn('知码',response.read().decode())
            self.assertIn("default-src 'self'",response.headers['Content-Security-Policy'])
        for path in ('/.env','/../.env','/reports/platform/history.jsonl'):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.base+path,timeout=3)
            self.assertEqual(error.exception.code,404)
            error.exception.close()

    def test_history_returns_all_saved_records(self):
        records = [{'id': index} for index in range(230)]
        with tempfile.TemporaryDirectory() as folder:
            history_path = Path(folder) / 'history.jsonl'
            history_path.write_text(
                ''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8',
            )
            with patch.object(server, 'HISTORY', history_path), patch.object(server, 'state', return_value=None):
                with urlopen(self.base + '/api/history', timeout=3) as response:
                    self.assertEqual(json.load(response)['records'], records)
                with urlopen(self.base + '/api/status', timeout=3) as response:
                    self.assertEqual(json.load(response)['history_count'], len(records))

    def test_foreign_origin_and_history_injection_rejected(self):
        request=Request(self.base+'/api/chat',data=b'{"mode":"A","question":"hi"}',
                        headers={'Content-Type':'application/json','Origin':'https://foreign.test'})
        with self.assertRaises(HTTPError) as error:
            urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,403)
        error.exception.close()
        request=Request(self.base+'/api/chat',data=b'{"mode":"A","question":"hi","history":[]}',
                        headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:
            urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,400)
        error.exception.close()
