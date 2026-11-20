import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bizcodeqa.platform import chunking, qa, sample, server, stores


class CharacterChunkTests(unittest.TestCase):
    def test_exact_coverage_unicode_offsets_and_overlap(self):
        fixture=sample.load_sample()
        source=(sample.ROOT/fixture['chunks'][0]['file_path']).read_bytes().replace(b'\r\n',b'\n')
        text=source.decode('utf-8')
        pieces=chunking.character_chunks(fixture,800,100)
        self.assertGreater(len(pieces),1)
        self.assertEqual(pieces,chunking.character_chunks(fixture,800,100))
        reconstructed=pieces[0]['code']
        for i,item in enumerate(pieces):
            self.assertEqual(item['code'],text[item['source_start_char']:item['source_end_char']])
            self.assertEqual(item['code'],source[item['source_start_byte']:item['source_end_byte']].decode('utf-8'))
            self.assertEqual(len(item['code']),item['character_count'])
            self.assertLessEqual(item['character_count'],800)
            self.assertEqual(item['content_sha256'],hashlib.sha256(item['code'].encode()).hexdigest())
            self.assertEqual(item['start_line'],text[:item['source_start_char']].count('\n')+1)
            self.assertEqual(item['end_line'],text[:item['source_end_char']-1].count('\n')+1)
            if i:
                self.assertEqual(item['source_start_char'],pieces[i-1]['source_end_char']-100)
                reconstructed+=item['code'][100:]
        self.assertEqual(reconstructed,text)
        self.assertEqual(pieces[-1]['source_end_char'],len(text))
        self.assertEqual(len({p['chunk_id'] for p in pieces}),len(pieces))
        self.assertGreater(pieces[-1]['source_end_byte'],pieces[-1]['source_end_char'])

    def test_zero_overlap_and_cross_symbol_mapping(self):
        fixture=sample.load_sample()
        pieces=chunking.character_chunks(fixture,4000,0)
        source=(sample.ROOT/fixture['chunks'][0]['file_path']).read_bytes().replace(b'\r\n',b'\n').decode()
        self.assertEqual(''.join(p['code'] for p in pieces),source)
        self.assertTrue(any(len(p['symbol_ids'])>1 for p in pieces))
        actual={e['symbol_id'] for e in fixture['entities']}
        for piece in pieces:
            self.assertTrue(set(piece['symbol_ids'])<=actual)
            self.assertEqual(piece['entity_type'],'File')

    def test_invalid_or_tiny_step_configs_rejected(self):
        for args in [('unknown',800,100),('character',True,0),('character',100,0),
                     ('character',800,-1),('character',800,401),('character',800,800),
                     ('character',800,1.5),('character',5000,0)]:
            with self.subTest(args=args),self.assertRaises(ValueError):
                chunking.chunk_config(*args)

    def test_legacy_and_character_states_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(stores,'STATE',Path(folder)/'index.json'):
            legacy={'chunks':[],'commit_sha':'test','collection':'legacy'}
            stores.STATE.write_text(json.dumps(legacy))
            self.assertEqual(stores.state()['collection'],'legacy')
            self.assertIsNone(stores.state('character',800,100))
            config=chunking.chunk_config('character',800,100)
            stores.index_path('character',800,100).write_text(json.dumps({**legacy,'collection':'chars','chunking':config}))
            self.assertEqual(stores.state('character',800,100)['collection'],'chars')
            self.assertIsNone(stores.state('character',900,100))
            self.assertEqual(len(stores.index_profiles()),2)


class CharacterRoutingTests(unittest.TestCase):
    def test_character_search_does_not_apply_method_filter(self):
        fixture=sample.load_sample()
        pieces=chunking.character_chunks(fixture)
        config=chunking.chunk_config('character')
        index={**fixture['metadata'],'chunks':pieces,'chunking':config,'collection':'chars',
               'embedding_digest':'digest','embedding_dimension':2,'query_instruction':'instruction'}
        client=MagicMock()
        client.search.return_value=[[{'chunk_id':pieces[0]['chunk_id'],'distance':.5}]]
        with patch.object(stores,'model_digest',return_value='digest'),patch.object(stores,'embed',return_value=[[1,0]]),patch.object(stores,'milvus',return_value=client):
            result=stores.vector_search('question',index,5)
        self.assertNotIn('entity_type',client.search.call_args.kwargs['filter'])
        self.assertEqual(result[0]['chunk_id'],pieces[0]['chunk_id'])

    def test_graph_keeps_multiple_windows_of_one_symbol(self):
        seed={'chunk_id':'seed','symbol_id':'file','symbol_ids':['method1']}
        chunks=[seed,{'chunk_id':'a','symbol_id':'file','symbol_ids':['method2']},
                {'chunk_id':'b','symbol_id':'file','symbol_ids':['method2']}]
        driver=MagicMock();driver.__enter__.return_value=driver
        driver.execute_query.return_value=([{'symbol_id':'method2','seed_id':'method1','relations':[]}],None,None)
        with patch.object(stores,'graph',return_value=driver):
            extra,paths=stores.graph_expand([seed],{'snapshot_id':'snap','chunks':chunks},3)
        self.assertEqual([c['chunk_id'] for c in extra],['a','b'])
        self.assertEqual(driver.execute_query.call_args.kwargs['seeds'],['method1'])
        self.assertEqual([p['target_chunk_id'] for p in paths],['a','b'])

    def test_missing_character_index_never_falls_back_to_method(self):
        with patch.object(qa,'state',return_value=None) as state,patch.object(qa,'chat') as chat:
            with self.assertRaises(stores.ServiceError):
                qa.answer('B','question',chunking_strategy='character')
        state.assert_called_once_with('character',800,100)
        chat.assert_not_called()

    def test_a_stays_independent_and_b_records_selected_profile(self):
        response={'content':'answer','model':'test','usage':{},'finish_reason':'stop'}
        with patch.object(qa,'state',side_effect=AssertionError('A accessed index')),patch.object(qa,'chat',return_value=response):
            result=qa.answer('A','question',chunking_strategy='character')
        self.assertIsNone(result['chunking'])
        self.assertEqual(result['requested_chunking']['profile_id'],'character_800_100')
        fixture=sample.load_sample();pieces=chunking.character_chunks(fixture)
        index={**fixture['metadata'],'chunks':pieces,'chunking':chunking.chunk_config('character'),
               'collection':'chars','query_instruction':'query','embedding_digest':'digest'}
        with patch.object(qa,'state',return_value=index),patch.object(qa,'load_sample',return_value=fixture),patch.object(qa,'vector_search',return_value=[dict(pieces[0],origin='vector',score=.5)]),patch.object(qa,'graph_expand',side_effect=AssertionError('B accessed graph')),patch.object(qa,'chat',return_value=response):
            result=qa.answer('B','question',chunking_strategy='character')
        self.assertEqual(result['chunking']['profile_id'],'character_800_100')
        self.assertEqual(result['collection'],'chars')
        self.assertIn('字符区间',result['messages'][1]['content'])


class PreparationApiTests(unittest.TestCase):
    def test_prepare_endpoint_validates_and_runs_without_model_call(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{http.server_port}'
        def post(payload):
            return urlopen(Request(base+'/api/prepare',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=3)
        done=threading.Event()
        def finish(config):
            with server.PREPARATION_LOCK:
                server.PREPARATION.update(status='succeeded',config=config)
            server.BUSY.release()
            done.set()
        try:
            with self.assertRaises(HTTPError) as error:
                post({'chunking_strategy':'character','chunk_size':1})
            self.assertEqual(error.exception.code,400);error.exception.close()
            with patch.object(server,'prepare_in_background',side_effect=finish) as prepare,patch.object(server,'answer') as answer:
                with post({'chunking_strategy':'character','chunk_size':800,'chunk_overlap':100}) as response:
                    self.assertEqual(response.status,202)
                self.assertTrue(done.wait(2),'Test preparation job did not finish')
                self.assertEqual(prepare.call_args.args[0]['profile_id'],'character_800_100')
                answer.assert_not_called()
        finally:
            http.shutdown();http.server_close();worker.join(timeout=3)
            with server.PREPARATION_LOCK:
                server.PREPARATION.clear();server.PREPARATION['status']='idle'
