import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid
from .config import load_env, required


def neo4j_check():
    from neo4j import GraphDatabase
    marker = uuid.uuid4().hex
    with GraphDatabase.driver(os.getenv('NEO4J_URI', 'bolt://127.0.0.1:7687'),
                              auth=('neo4j', required('NEO4J_PASSWORD')),
                              connection_timeout=10, max_transaction_retry_time=10) as driver:
        driver.verify_connectivity()
        with driver.session(database=os.getenv('NEO4J_DATABASE', 'neo4j')) as session:
            # Always roll back smoke data, even when validation raises.
            with session.begin_transaction(timeout=20) as tx:
                record = tx.run('CREATE (a:EnvironmentSmoke {id:$id}) '
                                'CREATE (b:EnvironmentSmoke {id:$other}) '
                                'CREATE (a)-[:CALLS]->(b) '
                                'WITH a MATCH (a)-[:CALLS]->(b) RETURN b.id AS id',
                                id=marker, other=marker + '_callee').single()
                if record is None or record['id'] != marker + '_callee':
                    raise RuntimeError('Neo4j relationship readback mismatch')
                tx.rollback()
    return {'detail': 'authenticated; node/relationship write and read passed; transaction rolled back'}


def milvus_check():
    from pymilvus import MilvusClient
    name = 'env_smoke_' + uuid.uuid4().hex
    client = MilvusClient(uri=os.getenv('MILVUS_URI', 'http://127.0.0.1:19530'), timeout=20)
    try:
        client.create_collection(collection_name=name, dimension=4, metric_type='COSINE',
                                 consistency_level='Strong', timeout=60)
        client.insert(collection_name=name, data=[
            {'id': 1, 'vector': [1., 0., 0., 0.], 'symbol_id': 'smoke:caller'},
            {'id': 2, 'vector': [0., 1., 0., 0.], 'symbol_id': 'smoke:callee'}], timeout=20)
        result = client.search(collection_name=name, data=[[1., 0., 0., 0.]], limit=1,
                               output_fields=['symbol_id'], timeout=30)
        if not result or not result[0] or result[0][0]['id'] != 1:
            raise RuntimeError('Milvus Top-1 readback mismatch')
    finally:
        try:
            if client.has_collection(collection_name=name, timeout=10):
                client.drop_collection(collection_name=name, timeout=30)
        finally:
            client.close()
    return {'detail': 'temporary collection; vector insert and Top-1 search passed; collection removed'}


def llm_check():
    from .llm import chat
    result = chat([{'role': 'user', 'content': 'Connectivity check. Reply with OK.'}])
    return {'detail': 'non-empty completion received', 'model': result['model'], 'usage': result['usage']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', choices=['neo4j', 'milvus', 'llm', 'databases', 'all'], default='all')
    parser.add_argument('--report', default='reports/connectivity.json')
    args = parser.parse_args()
    load_env()
    checks = {'neo4j': neo4j_check, 'milvus': milvus_check, 'llm': llm_check}
    names = list(checks) if args.only == 'all' else ['neo4j', 'milvus'] if args.only == 'databases' else [args.only]
    results = []
    for name in names:
        start = time.monotonic()
        try:
            detail = checks[name]()
            result = {'service': name, 'status': 'PASS', **detail}
        except Exception as exc:
            # Driver errors can contain connection strings. Never record raw exceptions.
            safe_prefixes = ('Missing configuration:', 'LLM HTTP ', 'LLM network/',
                             'LLM returned no ', 'LLM_BASE_URL ', 'Remote LLM ', 'Invalid LLM ')
            message = type(exc).__name__
            if name == 'llm' and isinstance(exc, (ValueError, RuntimeError)):
                if str(exc).startswith(safe_prefixes):
                    message = str(exc)
            result = {'service': name, 'status': 'FAIL', 'error': message}
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                                 'scope': args.only, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(r['status'] == 'PASS' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
