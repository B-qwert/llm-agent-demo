"""Independent slicing profiles; character windows use Unicode code points, not bytes."""
import hashlib

from .sample import ROOT, hashed


def chunk_config(strategy='method', chunk_size=800, chunk_overlap=100):
    if strategy=='method':
        return {'strategy':'method','profile_id':'method'}
    if strategy=='ast':
        return {'strategy':'ast','profile_id':'ast_statement_v1',
                'parser':'tree-sitter-java','parser_version':'0.23.5',
                'runtime_version':'0.25.2','unit':'direct_statement','compound_policy':'keep_whole'}
    if strategy=='paragraph':
        return {'strategy':'paragraph','profile_id':'paragraph_blank_v1',
                'separator':'blank_line','long_paragraph':'keep_whole'}
    if strategy=='token':
        if type(chunk_size) is not int or not 64<=chunk_size<=2048:
            raise ValueError('每块 Token 数必须是 64—2048 的整数')
        if type(chunk_overlap) is not int or not 0<=chunk_overlap<=chunk_size//2:
            raise ValueError('重叠 Token 数必须是非负整数且不能超过块长的一半')
        return {'strategy':'token','chunk_size':chunk_size,'chunk_overlap':chunk_overlap,
                'profile_id':f'token_qwen3_v1_{chunk_size}_{chunk_overlap}',
                'tokenizer':'Qwen/Qwen3-Embedding-0.6B',
                'tokenizer_sha256':'def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a',
                'tokenizers_version':'0.22.1','special_tokens':False}
    if strategy!='character':
        raise ValueError('切分方式必须是 method、character、ast、token 或 paragraph')
    if type(chunk_size) is not int or not 200<=chunk_size<=4000:
        raise ValueError('每块字符数必须是 200—4000 的整数')
    if type(chunk_overlap) is not int or not 0<=chunk_overlap<=chunk_size//2:
        raise ValueError('重叠字符数必须是非负整数，且不能超过块长的一半')
    return {'strategy':'character','chunk_size':chunk_size,'chunk_overlap':chunk_overlap,
            'profile_id':f'character_{chunk_size}_{chunk_overlap}',
            'character_unit':'unicode_code_point'}


def character_chunks(fixture, chunk_size=800, chunk_overlap=100):
    config=chunk_config('character',chunk_size,chunk_overlap)
    file=next(e for e in fixture['entities'] if e['entity_type']=='File')
    text=(ROOT/file['file_path']).read_bytes().replace(b'\r\n',b'\n').decode('utf-8')
    if hashlib.sha256(text.encode()).hexdigest()!=file['content_sha256']:
        raise ValueError('源码与已登记快照不一致，不能切分')
    # Maps exact source intervals to existing symbols without inventing a Method for a cross-method window.
    lines=text.splitlines(keepends=True)
    line_offsets=[0]
    for line in lines:
        line_offsets.append(line_offsets[-1]+len(line))
    byte_offsets=[0]
    for char in text:
        byte_offsets.append(byte_offsets[-1]+len(char.encode('utf-8')))
    intervals=[(e['symbol_id'],line_offsets[e['start_line']-1],line_offsets[e['end_line']])
               for e in fixture['entities'] if e['entity_type'] in ('Method','Field')]
    result=[]
    start=0
    while start<len(text):
        end=min(start+chunk_size,len(text))
        code=text[start:end]
        content_hash=hashlib.sha256(code.encode()).hexdigest()
        symbols=[sid for sid,left,right in intervals if left<end and right>start]
        index=len(result)
        item={k:file[k] for k in ('repository_id','snapshot_id','commit_sha','symbol_id',
                                  'file_path','canonical_name')}
        item.update(chunk_id=hashed('chk_',[file['snapshot_id'],file['symbol_id'],index,content_hash]),
                    content_sha256=content_hash,code=code,entity_type='File',
                    name=f'字符片段 {index+1:02d}',chunk_index=index,
                    symbol_ids=symbols or [file['symbol_id']],
                    start_line=text.count('\n',0,start)+1,
                    end_line=text.count('\n',0,end-1)+1,
                    source_start_char=start,source_end_char=end,
                    source_start_byte=byte_offsets[start],source_end_byte=byte_offsets[end],
                    character_count=end-start,chunking_strategy='character')
        result.append(item)
        if end==len(text):
            break
        start=end-chunk_overlap
    return result


def symbol_ids(chunk):
    return chunk.get('symbol_ids') or [chunk['symbol_id']]


def ast_chunks(fixture):
    """Cut direct method-body AST nodes; compound statements stay whole.

    Comments and inter-statement whitespace are not standalone evidence. Source
    spans are exact UTF-8 offsets, not reconstructed or pretty-printed Java.
    This only slices the registered sample; it does not resolve Java symbols.
    """
    from importlib.metadata import version
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_java
    except ImportError:
        raise ValueError('AST 切分需要 tree-sitter 和 tree-sitter-java，请安装 requirements.txt 并重建平台镜像。') from None
    config=chunk_config('ast')
    if version('tree-sitter')!=config['runtime_version'] or version('tree-sitter-java')!=config['parser_version']:
        raise ValueError('AST 解析器版本不一致，请按 requirements.txt 安装固定版本。')
    file=next(e for e in fixture['entities'] if e['entity_type']=='File')
    source=(ROOT/file['file_path']).read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(source).hexdigest()!=file['content_sha256']:
        raise ValueError('源码与已登记快照不一致，不能切分')
    parser=Parser(Language(tree_sitter_java.language()))
    tree=parser.parse(source)
    if tree.root_node.has_error:
        raise ValueError('Java AST 存在语法错误，停止准备索引，不退回其他切分方式。')
    entities=[e for e in fixture['entities'] if e['entity_type'] in ('Method','Field')]
    selected=[]
    def visit(node):
        if node.type in ('method_declaration','constructor_declaration','field_declaration'):
            line=node.start_point.row+1
            kind='Field' if node.type=='field_declaration' else 'Method'
            owners=[e for e in entities if e['entity_type']==kind and
                    e['start_line']<=line<=e['end_line']]
            if not owners:
                raise ValueError('AST 声明无法关联现有符号，停止准备索引。')
            body=node.child_by_field_name('body') if kind=='Method' else None
            nodes=[n for n in body.named_children if n.type not in ('line_comment','block_comment')] if body else []
            # Empty/abstract methods and field declarations remain discoverable.
            for unit in nodes or [node]:
                selected.append((unit,owners))
            return
        for child in node.named_children:
            visit(child)
    visit(tree.root_node)
    result=[]
    for node,owners in sorted(selected,key=lambda pair:pair[0].start_byte):
        start,end=node.start_byte,node.end_byte
        code=source[start:end].decode('utf-8')
        content_hash=hashlib.sha256(code.encode()).hexdigest()
        owner=owners[0]
        index=len(result)
        item={k:owner[k] for k in ('repository_id','snapshot_id','commit_sha','symbol_id',
                                  'file_path','canonical_name','entity_type')}
        item.update(chunk_id=hashed('chk_',[owner['snapshot_id'],owner['symbol_id'],
                                          config['profile_id'],index,content_hash]),
                    content_sha256=content_hash,code=code,
                    name=f"{owner['name']} · {node.type} {index+1}",chunk_index=index,
                    symbol_ids=[e['symbol_id'] for e in owners],
                    start_line=source.count(b'\n',0,start)+1,
                    end_line=source.count(b'\n',0,end-1)+1,
                    source_start_char=len(source[:start].decode('utf-8')),
                    source_end_char=len(source[:end].decode('utf-8')),
                    source_start_byte=start,source_end_byte=end,character_count=len(code),
                    chunking_strategy='ast',ast_node_type=node.type,
                    ast_parser=config['parser'],ast_parser_version=config['parser_version'])
        result.append(item)
    if not result:
        raise ValueError('未提取到可用 AST 语句，不激活空索引。')
    return result


def token_chunks(fixture, chunk_size=800, chunk_overlap=100):
    """Pinned Qwen tokenizer windows with exact source slices and safe Unicode edges.

    Token spans refer to the full-source encoding; each slice is re-encoded to
    verify its actual standalone length. Requested overlap rounds down to a
    safe character boundary when several byte tokens share one Unicode point.
    """
    import bisect
    config=chunk_config('token',chunk_size,chunk_overlap)
    tokenizer=_load_tokenizer(config)
    file=next(e for e in fixture['entities'] if e['entity_type']=='File')
    source=(ROOT/file['file_path']).read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(source).hexdigest()!=file['content_sha256']:
        raise ValueError('源码与已登记快照不一致，不能切分')
    text=source.decode('utf-8')
    encoded=tokenizer.encode(text,add_special_tokens=False)
    offsets=encoded.offsets
    if not offsets:
        raise ValueError('源码未生成 Token，不能激活空索引。')
    # A byte-level tokenizer may give multiple tokens the same character span.
    safe=[0]+[i for i in range(1,len(offsets)) if offsets[i-1][1]<=offsets[i][0]]+[len(offsets)]
    def char_at(i):
        return offsets[i][0] if i<len(offsets) else len(text)
    byte_offsets=[0]
    for char in text:
        byte_offsets.append(byte_offsets[-1]+len(char.encode('utf-8')))
    lines=text.splitlines(keepends=True)
    line_offsets=[0]
    for line in lines:
        line_offsets.append(line_offsets[-1]+len(line))
    intervals=[(e['symbol_id'],line_offsets[e['start_line']-1],line_offsets[e['end_line']])
               for e in fixture['entities'] if e['entity_type'] in ('Method','Field')]
    result=[]; start=0
    while start<len(offsets):
        boundary=bisect.bisect_right(safe,min(start+chunk_size,len(offsets)))-1
        while boundary>=0:
            end=safe[boundary]
            if end<=start:
                raise ValueError('Token 窗口无法安全前进，请增大块长。')
            left,right=char_at(start),char_at(end)
            code=text[left:right]
            count=len(tokenizer.encode(code,add_special_tokens=False).ids)
            if count<=chunk_size:break
            boundary-=1
        content_hash=hashlib.sha256(code.encode()).hexdigest()
        symbols=[sid for sid,a,b in intervals if a<right and b>left]
        index=len(result)
        item={k:file[k] for k in ('repository_id','snapshot_id','commit_sha','symbol_id','file_path','canonical_name')}
        item.update(chunk_id=hashed('chk_',[file['snapshot_id'],file['symbol_id'],config['profile_id'],index,content_hash]),
                    content_sha256=content_hash,code=code,entity_type='File',
                    name=f'Token 片段 {index+1:02d}',chunk_index=index,symbol_ids=symbols or [file['symbol_id']],
                    start_line=text.count('\n',0,left)+1,end_line=text.count('\n',0,right-1)+1,
                    source_start_char=left,source_end_char=right,
                    source_start_byte=byte_offsets[left],source_end_byte=byte_offsets[right],
                    character_count=right-left,source_start_token=start,source_end_token=end,
                    token_count=count,tokenizer=config['tokenizer'],tokenizer_sha256=config['tokenizer_sha256'],
                    chunking_strategy='token')
        result.append(item)
        if end==len(offsets):break
        start=safe[bisect.bisect_left(safe,max(start+1,end-chunk_overlap))]
    return result


def _load_tokenizer(config):
    from importlib.metadata import version
    try:
        from tokenizers import Tokenizer
    except ImportError:
        raise ValueError('Token 切分需要 tokenizers，请安装 requirements.txt 并重建平台镜像。') from None
    if version('tokenizers')!=config['tokenizers_version']:
        raise ValueError('Token 分词器运行版本不符，请按 requirements.txt 安装。')
    asset=ROOT/'assets/tokenizers/qwen3_embedding/tokenizer.json'
    if not asset.exists() or hashlib.sha256(asset.read_bytes()).hexdigest()!=config['tokenizer_sha256']:
        raise ValueError('Token 分词器文件缺失或摘要不符，不能准备索引。')
    tokenizer=Tokenizer.from_file(str(asset))
    tokenizer.no_truncation();tokenizer.no_padding()
    return tokenizer


def paragraph_chunks(fixture):
    """One exact source slice per nonempty blank-line paragraph; no size cap."""
    config=chunk_config('paragraph')
    file=next(e for e in fixture['entities'] if e['entity_type']=='File')
    source=(ROOT/file['file_path']).read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(source).hexdigest()!=file['content_sha256']:
        raise ValueError('源码与已登记快照不一致，不能切分')
    text=source.decode('utf-8')
    lines=text.splitlines(keepends=True)
    line_offsets=[0]
    paragraphs=[];begin=None
    for line in lines:
        offset=line_offsets[-1]
        if line.rstrip('\n').strip(' \t'):
            if begin is None:begin=offset
        elif begin is not None:
            paragraphs.append((begin,offset));begin=None
        line_offsets.append(offset+len(line))
    if begin is not None:paragraphs.append((begin,len(text)))
    intervals=[(e['symbol_id'],line_offsets[e['start_line']-1],line_offsets[e['end_line']])
               for e in fixture['entities'] if e['entity_type'] in ('Method','Field')]
    byte_offsets=[0]
    for char in text:byte_offsets.append(byte_offsets[-1]+len(char.encode('utf-8')))
    result=[]
    for index,(left,right) in enumerate(paragraphs):
        code=text[left:right]
        content_hash=hashlib.sha256(code.encode()).hexdigest()
        symbols=[sid for sid,a,b in intervals if a<right and b>left]
        item={k:file[k] for k in ('repository_id','snapshot_id','commit_sha','symbol_id','file_path','canonical_name')}
        item.update(chunk_id=hashed('chk_',[file['snapshot_id'],file['symbol_id'],config['profile_id'],index,content_hash]),
                    content_sha256=content_hash,code=code,entity_type='File',
                    name=f'段落 {index+1:02d}',chunk_index=index,
                    symbol_ids=symbols or [file['symbol_id']],
                    start_line=text.count('\n',0,left)+1,end_line=text.count('\n',0,right-1)+1,
                    source_start_char=left,source_end_char=right,
                    source_start_byte=byte_offsets[left],source_end_byte=byte_offsets[right],
                    character_count=right-left,paragraph_index=index,chunking_strategy='paragraph')
        result.append(item)
    if not result:raise ValueError('没有非空段落，不能激活空索引。')
    return result
