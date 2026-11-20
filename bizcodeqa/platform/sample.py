"""A curated fixture for one immutable Java sample, NOT a generic Java parser."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
METHODS = [('main',18,21), ('initData',23,40), ('startSystem',42,95),
           ('borrowRank',97,127), ('addBook',129,159), ('showBook',161,177),
           ('deleteBook',179,209), ('borrowBook',211,255), ('returnBook',257,303),
           ('addReader',305,333), ('showReader',335,349), ('deleteReader',351,382)]
FIELDS = [('bookName',8,'java.lang.String[]'), ('bookState',9,'int[]'),
          ('bookDate',10,'java.lang.String[]'), ('bookCount',11,'int[]'),
          ('readerName',13,'java.lang.String[]'), ('readerId',14,'java.lang.String[]'),
          ('borrowName',15,'java.lang.String[]'), ('readerState',16,'int[]')]


def hashed(prefix, value):
    return prefix + hashlib.sha256(json.dumps(value, ensure_ascii=False,
                                             separators=(',', ':')).encode()).hexdigest()


def load_sample():
    manifest = json.loads((ROOT/'samples/book_borrow/snapshot.json').read_text(encoding='utf-8'))
    spec = manifest['source_files'][0]
    path = spec['file_path']
    source = (ROOT/path).read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(source).hexdigest() != spec['content_sha256']:
        raise ValueError('样例源码已改变，请先登记新快照；不能沿用当前索引。')
    text = source.decode('utf-8')
    lines = text.splitlines(keepends=True)
    if len(lines) != spec['line_count']:
        raise ValueError('样例行数与快照不符')
    repo, snap, commit = (manifest[k] for k in ('repository_id','snapshot_id','commit_sha'))
    metadata = {'schema_version':'0.1.0','repository_id':repo,'snapshot_id':snap,'commit_sha':commit}
    entities, relationships, chunks, unresolved = [], [], [], []

    def entity(entity_type, name, canonical, start=None, end=None, **extra):
        sid = hashed('sym_', [repo,'java',entity_type,canonical])
        item = {**metadata,'entity_type':entity_type,'name':name,'canonical_name':canonical,
                'language':'java','symbol_id':sid,'entity_key':snap+':'+sid,
                'extraction_method':'manual_verified','parser_name':'curated_book_borrow_fixture',
                'parser_version':'1.0.0', **extra}
        item.pop('schema_version')
        if start is not None:
            item.update(file_path=path,start_line=start,end_line=end)
        entities.append(item)
        return item

    def relation(kind, source_entity, target, start, end, byte_start=None, byte_end=None, **extra):
        occurrence = [byte_start,byte_end] if kind in ('CALLS','REFERENCES') else None
        rid = hashed('rel_', [repo,kind,source_entity['symbol_id'],target['symbol_id'],path,occurrence])
        item = {k:v for k,v in metadata.items() if k!='schema_version'}
        item.update(relationship_type=kind,relationship_id=rid,relationship_key=snap+':'+rid,
                    source_symbol_id=source_entity['symbol_id'],target_symbol_id=target['symbol_id'],
                    extraction_method='manual_verified',resolution_status='resolved',source_file=path,
                    source_start_line=start,source_end_line=end, **extra)
        if occurrence:
            item.update(source_start_byte=byte_start,source_end_byte=byte_end)
        relationships.append(item)

    def chunk(item):
        code = ''.join(lines[item['start_line']-1:item['end_line']])
        content_hash = hashlib.sha256(code.encode()).hexdigest()
        chunks.append({k:item[k] for k in ('repository_id','snapshot_id','commit_sha','symbol_id',
                                          'file_path','start_line','end_line','name','canonical_name')})
        chunks[-1].update(chunk_id=hashed('chk_',[snap,item['symbol_id'],0,content_hash]),
                          content_sha256=content_hash,code=code,entity_type=item['entity_type'])

    repository = entity('Repository','图书借阅样例',repo)
    file = entity('File','bookBorrowSystem.java',path,1,len(lines),content_sha256=spec['content_sha256'])
    cls = entity('Class','bookBorrowSystem','experiment.bookBorrowSystem',7,383,
                 kind='class',package_name='experiment',modifiers=['public'])
    relation('CONTAINS',repository,file,1,len(lines))
    relation('DECLARES',file,cls,7,383)
    fields, methods = {}, {}
    for name, line, field_type in FIELDS:
        fields[name] = entity('Field',name,cls['canonical_name']+'#'+name,line,line,
                              declaring_type_id=cls['symbol_id'],field_type=field_type,
                              modifiers=['private','static'])
        relation('DECLARES',cls,fields[name],line,line)
        chunk(fields[name])
    for name,start,end in METHODS:
        parameters = ['java.lang.String[]'] if name=='main' else (
            ['java.util.Scanner'] if name in ('addBook','deleteBook','borrowBook','returnBook',
                                               'addReader','deleteReader') else [])
        if not re.search(r'\b'+name+r'\s*\(',lines[start-1]):
            raise ValueError('人工核对的方法位置已不匹配')
        item = entity('Method',name,cls['canonical_name']+'#'+name+'('+','.join(parameters)+')',start,end,
                      declaring_type_id=cls['symbol_id'],parameter_types=parameters,return_type='void',
                      is_constructor=False,modifiers=['public','static'] if name=='main' else ['private','static'])
        methods[name] = item
        relation('DECLARES',cls,item,start,end)
        chunk(item)
    # Curated internal calls: no inference about arbitrary external APIs or runtime dispatch.
    calls = {'main':['initData','startSystem'], 'startSystem':[
        'borrowRank','addBook','showBook','deleteBook','borrowBook','returnBook','addReader','showReader','deleteReader']}
    for caller,targets in calls.items():
        item = methods[caller]
        prefix = ''.join(lines[:item['start_line']-1])
        body = ''.join(lines[item['start_line']-1:item['end_line']])
        for target in targets:
            match = re.search(r'\b'+target+r'\([^)]*\)',body)
            if not match:
                raise ValueError('人工核对的调用不存在')
            before = prefix + body[:match.start()]
            line = before.count('\n')+1
            relation('CALLS',item,methods[target],line,line,len(before.encode()),
                     len((prefix+body[:match.end()]).encode()))
    # Deliberately only the first verified occurrence of each field per method, not a complete access graph.
    for name,item in methods.items():
        prefix = ''.join(lines[:item['start_line']-1])
        body = ''.join(lines[item['start_line']-1:item['end_line']])
        for field,target in fields.items():
            match = re.search(r'\b'+field+r'\b',body)
            if not match:
                continue
            before = prefix+body[:match.start()]
            tail = body[match.end():]
            write = re.match(r'\[[^\]\n]*\]\s*=(?!=)',tail)
            relation('REFERENCES',item,target,before.count('\n')+1,before.count('\n')+1,
                     len(before.encode()),len((prefix+body[:match.end()]).encode()),
                     access_kind='write' if write else 'read')
    for line, raw in enumerate(lines,1):
        if raw.startswith('import '):
            unresolved.append({'source_symbol_id':file['symbol_id'],'target_symbol_id':None,
                               'source_file':path,'source_start_line':line,'source_end_line':line,
                               'reference_kind':'IMPORTS','raw_target':raw.strip(),
                               'reason':'external_symbol','resolution_status':'unresolved'})
    return {'metadata':metadata,'entities':entities,'relationships':relationships,
            'unresolved_references':unresolved,'diagnostics':[
                '人工核对的单文件夹具，不是通用解析器；REFERENCES 仅覆盖每方法每字段首个发生位置；外部调用未完整枚举。'],
            'chunks':chunks}
