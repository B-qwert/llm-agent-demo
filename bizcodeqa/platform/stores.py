"""Real Ollama, Milvus and Neo4j adapters. No silent fallback between schemes."""
import json
import math
import os
from pathlib import Path
import urllib.request

from .sample import ROOT
from .chunking import chunk_config, symbol_ids

STATE = ROOT/'reports/platform/index.json'
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL','qwen3-embedding:0.6b')
QUERY_INSTRUCTION = 'Instruct: Retrieve Java source code that answers the business logic question.\nQuery: '


class ServiceError(RuntimeError):
    pass


def ollama(path, payload=None):
    base = os.getenv('OLLAMA_BASE_URL','http://127.0.0.1:11434').rstrip('/')
    request = urllib.request.Request(base+path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except Exception:
        raise ServiceError('无法连接 Ollama 或生成向量失败，请启动 Ollama 并确认模型已安装。') from None


def model_digest():
    models = ollama('/api/tags').get('models',[])
    found = next((m for m in models if m.get('name')==EMBEDDING_MODEL or m.get('model')==EMBEDDING_MODEL),None)
    if not found or not found.get('digest'):
        raise ServiceError('未找到配置的 Embedding 模型，请先在 Ollama 安装它。')
    return found['digest']


def embed(texts):
    result = ollama('/api/embed',{'model':EMBEDDING_MODEL,'input':texts,'truncate':False})
    vectors = result.get('embeddings',[])
    if len(vectors)!=len(texts) or not vectors:
        raise ServiceError('Embedding 返回数量不正确')
    dim = len(vectors[0])
    if dim<1 or any(len(v)!=dim or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) for v in vectors):
        raise ServiceError('Embedding 维度或数值不正确')
    return vectors


def index_path(strategy='method', chunk_size=800, chunk_overlap=100):
    config=chunk_config(strategy,chunk_size,chunk_overlap)
    return STATE if strategy=='method' else STATE.with_name('index_'+config['profile_id']+'.json')


def state(strategy='method', chunk_size=800, chunk_overlap=100):
    path=index_path(strategy,chunk_size,chunk_overlap)
    if not path.exists():
        return None
    index=json.loads(path.read_text(encoding='utf-8'))
    expected=chunk_config(strategy,chunk_size,chunk_overlap)
    actual=index.get('chunking',{'strategy':'method','profile_id':'method'})
    if actual!=expected:
        raise ServiceError('索引切分配置与请求不符，请重新准备该配置的索引。')
    return index


def index_profiles():
    profiles=[]
    for path in [STATE,*sorted(STATE.parent.glob('index_character_*.json')),*sorted(STATE.parent.glob('index_ast_*.json')),*sorted(STATE.parent.glob('index_token_*.json')),*sorted(STATE.parent.glob('index_paragraph_*.json'))]:
        if not path.exists():
            continue
        try:
            index=json.loads(path.read_text(encoding='utf-8'))
            config=index.get('chunking',{'strategy':'method','profile_id':'method'})
            if config!=chunk_config(config['strategy'],config.get('chunk_size',800),config.get('chunk_overlap',100)):
                continue
            profiles.append({**config,'chunk_count':len(index['chunks']),
                             'graph_ready':bool(index.get('graph_ready')),'commit_sha':index['commit_sha'],
                             'collection':index['collection']})
        except (ValueError,KeyError,TypeError,OSError):
            continue
    return profiles


def milvus():
    from pymilvus import MilvusClient
    return MilvusClient(uri=os.getenv('MILVUS_URI','http://127.0.0.1:19530'),timeout=15)


def graph():
    from neo4j import GraphDatabase
    password = os.getenv('NEO4J_PASSWORD','')
    if not password:
        raise ServiceError('Neo4j 密码未配置，请检查本地 .env')
    return GraphDatabase.driver(os.getenv('NEO4J_URI','bolt://127.0.0.1:7687'),
                               auth=('neo4j',password),connection_timeout=10)


def vector_search(question, index, top_k):
    client = None
    try:
        if model_digest()!=index['embedding_digest']:
            raise ServiceError('Embedding 模型版本已变更，请重建样例索引，不能混用向量空间。')
        vector = embed([index['query_instruction']+question])[0]
        if len(vector)!=index['embedding_dimension']:
            raise ServiceError('Embedding 维度已变更，请重建索引。')
        client = milvus()
        query_filter='repository_id == '+json.dumps(index['repository_id'])+' and snapshot_id == '+json.dumps(index['snapshot_id'])
        if index.get('chunking',{}).get('strategy','method')=='method':
            query_filter+=' and entity_type == "Method"'
        result = client.search(collection_name=index['collection'],data=[vector],limit=top_k,
                               filter=query_filter,
                               output_fields=['symbol_id','snapshot_id'],
                               search_params={'metric_type':'COSINE','params':{}})
        allowed = {c['chunk_id']:c for c in index['chunks']}
        hits = []
        for hit in result[0]:
            key = hit.get('chunk_id',hit.get('id'))
            if key not in allowed:
                raise ServiceError('向量与源码片段登记不一致，请重新导入。')
            item = dict(allowed[key],origin='vector',score=round(float(hit['distance']),5))
            hits.append(item)
        return hits
    except ServiceError:
        raise
    except Exception:
        raise ServiceError('Milvus 检索失败，请确认服务正常、且已准备当前样例索引。') from None
    finally:
        if client:
            client.close()


def graph_expand(seeds,index,limit=3):
    seed_ids = sorted({sid for c in seeds for sid in symbol_ids(c)})
    query = '''
    MATCH (s:CodeEntity) WHERE s.snapshot_id=$snapshot AND s.symbol_id IN $seeds
    CALL {
      WITH s MATCH (s)-[r:CALLS]-(n:CodeEntity)
      WHERE n.snapshot_id=$snapshot
      RETURN n, [r] AS rels, 0 AS priority
      UNION
      WITH s MATCH (s)-[r:REFERENCES]-(n:CodeEntity)
      WHERE n.snapshot_id=$snapshot
      RETURN n, [r] AS rels, 1 AS priority
      UNION
      WITH s MATCH (s)-[r:REFERENCES]->(f:Field)<-[r2:REFERENCES]-(n:Method)
      WHERE n.snapshot_id=$snapshot AND f.snapshot_id=$snapshot AND n.symbol_id<>s.symbol_id
      RETURN n, [r,r2] AS rels, 2 AS priority
    }
    RETURN n.symbol_id AS symbol_id, s.symbol_id AS seed_id, priority,
       [r IN rels | {source:r.source_symbol_id,target:r.target_symbol_id,type:type(r),
                     file:r.source_file,line:r.source_start_line}] AS relations
    ORDER BY priority, n.symbol_id LIMIT 60
    '''
    try:
        with graph() as driver:
            records,_,_ = driver.execute_query(query,snapshot=index['snapshot_id'],seeds=seed_ids,
                                               database_=os.getenv('NEO4J_DATABASE','neo4j'))
        by_symbol = {}
        for chunk in index['chunks']:
            for sid in symbol_ids(chunk):
                by_symbol.setdefault(sid,[]).append(chunk)
        seen = {c['chunk_id'] for c in seeds}
        extra, paths = [], []
        for record in records:
            sid = record['symbol_id']
            if sid not in by_symbol:
                continue
            for chunk in by_symbol[sid]:
                if chunk['chunk_id'] in seen:
                    continue
                seen.add(chunk['chunk_id'])
                extra.append(dict(chunk,origin='graph',score=None))
                paths.append({'seed_id':record['seed_id'],'target_id':sid,'target_chunk_id':chunk['chunk_id'],
                              'relations':[dict(r) for r in record['relations']]})
                if len(extra)>=limit:
                    break
            if len(extra)>=limit:
                break
        return extra,paths
    except ServiceError:
        raise
    except Exception:
        raise ServiceError('Neo4j 图扩展失败。C 模式需要图服务；不会自动降级为 B。') from None
