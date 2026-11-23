"""Prepare idempotent, isolated sample indexes for the local prototype."""
import argparse
import json
import os
import uuid

from ..config import load_env
from .sample import ROOT, load_sample
from .chunking import chunk_config, character_chunks, ast_chunks, token_chunks, paragraph_chunks
from .stores import STATE, QUERY_INSTRUCTION, embed, embedding_model, model_digest, milvus, graph, index_path


def prepare(strategy='method', chunk_size=800, chunk_overlap=100, progress=None):
    from pymilvus import DataType, MilvusClient
    config=chunk_config(strategy,chunk_size,chunk_overlap)
    notify=progress or (lambda message: None)
    notify('校验源码与切分配置')
    fixture = load_sample()
    chunks = (fixture['chunks'] if strategy=='method' else
              ast_chunks(fixture) if strategy=='ast' else
              token_chunks(fixture,chunk_size,chunk_overlap) if strategy=='token' else
              paragraph_chunks(fixture) if strategy=='paragraph' else character_chunks(fixture,chunk_size,chunk_overlap))
    notify(f'正在为 {len(chunks)} 个片段生成向量')
    model = embedding_model()
    digest = model_digest()
    vectors = embed([c['canonical_name']+'\n'+c['code'] for c in chunks])
    dimension = len(vectors[0])
    # Each preparation builds an isolated collection; only activate after both stores verify.
    collection = 'book_borrow_'+config['profile_id']+'_'+fixture['metadata']['commit_sha'][:8]+'_'+digest[:8]+'_'+uuid.uuid4().hex[:8]
    client = milvus()
    created=False
    activated=False
    try:
        notify('正在创建独立 Milvus 索引并写入向量')
        schema = MilvusClient.create_schema(auto_id=False,enable_dynamic_field=True)
        schema.add_field(field_name='chunk_id',datatype=DataType.VARCHAR,is_primary=True,max_length=256)
        schema.add_field(field_name='vector',datatype=DataType.FLOAT_VECTOR,dim=dimension)
        indexes = client.prepare_index_params()
        indexes.add_index(field_name='vector',index_type='FLAT',metric_type='COSINE')
        client.create_collection(collection_name=collection,schema=schema,index_params=indexes,
                                 consistency_level='Strong')
        created=True
        rows = [{**{k:v for k,v in c.items() if k!='code'},'embedding_model':model,
                 'embedding_digest':digest,'vector':vector} for c,vector in zip(chunks,vectors)]
        client.upsert(collection_name=collection,data=rows)
        client.flush(collection_name=collection)
        count = len(client.query(collection_name=collection,filter='',output_fields=['chunk_id'],limit=len(chunks)+1))
        if count!=len(chunks):
            raise RuntimeError('Milvus 片段数量校验失败')
        notify('正在校验并写入共享代码图谱')
        with graph() as driver:
            database = os.getenv('NEO4J_DATABASE','neo4j')
            schema_script = (ROOT/'bizcodeqa/platform/neo4j_schema.cypher').read_text(encoding='utf-8')
            for statement in schema_script.split(';'):
                if statement.strip():
                    driver.execute_query(statement,database_=database)
            def write(tx):
                for entity in fixture['entities']:
                    label = entity['entity_type']
                    tx.run('MERGE (n:CodeEntity:'+label+' {entity_key:$key}) SET n=$props',
                           key=entity['entity_key'],props=entity).consume()
                for rel in fixture['relationships']:
                    kind=rel['relationship_type']
                    tx.run('MATCH (s:CodeEntity {entity_key:$s}),(t:CodeEntity {entity_key:$t}) '
                           'MERGE (s)-[r:'+kind+' {relationship_key:$key}]->(t) SET r=$props',
                           s=rel['snapshot_id']+':'+rel['source_symbol_id'],
                           t=rel['snapshot_id']+':'+rel['target_symbol_id'],
                           key=rel['relationship_key'],props=rel).consume()
            with driver.session(database=database) as session:
                session.execute_write(write)
            records,_,_ = driver.execute_query('MATCH (n:CodeEntity {snapshot_id:$s}) '
                                               'RETURN count(n) AS count',
                                               s=fixture['metadata']['snapshot_id'],database_=database)
            if records[0]['count']!=len(fixture['entities']):
                raise RuntimeError('Neo4j 实体数量校验失败')
        index = {**fixture['metadata'],'collection':collection,'embedding_model':model,
                 'embedding_digest':digest,'embedding_dimension':dimension,'metric':'COSINE',
                 'query_instruction':QUERY_INSTRUCTION,'chunks':chunks,'graph_ready':True,
                 'entity_count':len(fixture['entities']),'relationship_count':len(fixture['relationships']),
                 'fixture_method':'manual_verified','context_character_budget':18000}
        index.update(chunking=config,symbol_names={e['symbol_id']:e['name'] for e in fixture['entities']})
        target=index_path(strategy,chunk_size,chunk_overlap)
        notify('正在激活该切分配置的索引')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
        (STATE.parent/'graph_fixture.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(target)
        activated=True
        print(json.dumps({k:v for k,v in index.items() if k!='chunks'},ensure_ascii=False,indent=2))
        print(f'Prepared {len(chunks)} chunks; A/B/C platform is ready.')
        return {**config,'chunk_count':len(chunks),'collection':collection}
    except Exception:
        if created and not activated:
            try:
                client.drop_collection(collection_name=collection)
            except Exception:
                pass
        raise
    finally:
        client.close()


if __name__=='__main__':
    load_env(ROOT/'.env')
    parser=argparse.ArgumentParser()
    parser.add_argument('--strategy',choices=['method','character','ast','token','paragraph'],default='method')
    parser.add_argument('--chunk-size',type=int,default=800)
    parser.add_argument('--chunk-overlap',type=int,default=100)
    args=parser.parse_args()
    prepare(args.strategy,args.chunk_size,args.chunk_overlap)
