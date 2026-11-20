# -*- coding: utf-8 -*-
"""
按《Schema 设计规范》v0.1.0 第 9 节，把 Java 源码切成块 → Ollama 向量化 → 存入 Milvus。

和上一版切片脚本的区别：
  1. 集合名统一为 code_chunks_v1（对比实验用 code_chunks_v1_paragraph / _fixed）
  2. 每条记录带齐规范要求的字段：chunk_id / repository_id / snapshot_id /
     commit_sha / symbol_id / file_path / start_line / end_line / embedding_model
  3. chunk_id 按 [snapshot_id, symbol_id, chunk_index, chunk_content_sha256] 算 SHA256，
     不再是自增整数，重跑结果稳定
  4. 补了 symbol_id，后续可以用它关联 Neo4j 里的方法节点

运行：python slice_to_milvus.py
"""

import hashlib
import json
import re
import urllib.request
from pathlib import Path

from pymilvus import DataType, MilvusClient

# ────────────────────────── 登记信息 ──────────────────────────
# 全部来自 samples/book_borrow/snapshot.json，不要自己改
REPOSITORY_ID = "50563430-64b6-45ad-85c8-74f9224c9ced"
COMMIT_SHA = "df2b56851beb70533c6f9eab441917f2379c4de6"
SNAPSHOT_ID = f"{REPOSITORY_ID}@{COMMIT_SHA}"
FILE_PATH = "samples/book_borrow/src/experiment/bookBorrowSystem.java"
LANGUAGE = "java"
PACKAGE_NAME = "experiment"
CLASS_NAME = "bookBorrowSystem"

# ────────────────────────── 环境参数 ──────────────────────────
_HERE = Path(__file__).resolve().parent
# 优先读仓库登记的样例（与 snapshot.json 的 file_path 对齐），没有再用脚本旁的副本
_REGISTERED = _HERE.parent / "samples" / "book_borrow" / "src" / "experiment" / "bookBorrowSystem.java"
JAVA_FILE = _REGISTERED if _REGISTERED.exists() else _HERE / "samples" / "bookBorrowSystem.java"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "qwen3-embedding:0.6b"
MILVUS_URI = "http://127.0.0.1:19530"
DIM = 1024          # qwen3-embedding:0.6b 的输出维度
BATCH = 16

FIXED_SIZE = 400    # 定长切：每块字符数
FIXED_OVERLAP = 80  # 定长切：相邻块重叠字符数

# ────────────────────────── 标识生成 ──────────────────────────


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_symbol_id(entity_type, canonical_name):
    """symbol_id = "sym_" + SHA256([repository_id, language, entity_type, canonical_name])"""
    identity = [REPOSITORY_ID, LANGUAGE, entity_type, canonical_name]
    payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return "sym_" + _sha256(payload)


def make_chunk_id(symbol_id, chunk_index, content):
    """chunk_id = SHA256([snapshot_id, symbol_id, chunk_index, chunk_content_sha256])"""
    payload = json.dumps(
        [SNAPSHOT_ID, symbol_id, chunk_index, _sha256(content)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _sha256(payload)


BASIC_TYPES = {
    "int", "long", "short", "byte", "char", "float", "double", "boolean",
}
REF_TYPES = {
    "String": "java.lang.String",
    "Object": "java.lang.Object",
}
IMPORT_RE = re.compile(r"import\s+(?:static\s+)?([\w.]+)\s*;")

# 由源码里的 import 语句填充：{"Scanner": "java.util.Scanner"}
IMPORTS = {}


def parse_imports(lines):
    """从 import 行解析简单类名 → 全限定名。"""
    mapping = {}
    for line in lines:
        m = IMPORT_RE.match(line.strip())
        if m:
            full = m.group(1)
            mapping[full.rsplit(".", 1)[-1]] = full
    return mapping


def normalize_type(raw):
    """把 Java 里的简单类型名补成全限定名，数组后缀原样保留。"""
    t = raw.strip()
    suffix = ""
    while t.endswith("[]"):
        suffix += "[]"
        t = t[:-2].strip()
    if t in BASIC_TYPES:
        return t + suffix
    if t in REF_TYPES:
        return REF_TYPES[t] + suffix
    if t in IMPORTS:
        return IMPORTS[t] + suffix
    return t + suffix   # 无法确认的保持原样


def canonical_method_name(name, params_text):
    """demo.OrderService#cancel(java.lang.String) 这种格式。"""
    if not params_text.strip():
        return f"{PACKAGE_NAME}.{CLASS_NAME}#{name}()"
    types = []
    for part in params_text.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        raw_type = " ".join(tokens[:-1]) if len(tokens) >= 2 else tokens[0]
        types.append(normalize_type(raw_type))
    return f"{PACKAGE_NAME}.{CLASS_NAME}#{name}({','.join(types)})"


# ────────────────────────── 三种切片 ──────────────────────────

SIG_RE = re.compile(r"\s*(?:public|private|protected)\s+static\s+[^\s(]+\s+(\w+)\s*(\([^)]*\))")


def slice_by_method(lines):
    """按函数切：从签名行开始数花括号，配对归零即一块。"""
    chunks = []
    i = 0
    while i < len(lines):
        m = SIG_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        params = m.group(2)[1:-1]
        depth = 0
        start = i
        j = i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if depth == 0 and j > start:
                break
            j += 1
        text = "\n".join(lines[start:j + 1])
        chunks.append({
            "text": text,
            "start": start + 1,
            "end": j + 1,
            "method_name": name,
            "canonical": canonical_method_name(name, params),
        })
        i = j + 1
    return chunks


def slice_by_paragraph(lines):
    """按段落切：空行断开。"""
    chunks = []
    cur = []
    start = 1
    for idx, line in enumerate(lines, 1):
        if line.strip() == "":
            if cur:
                chunks.append({"text": "\n".join(cur), "start": start, "end": idx - 1})
                cur = []
        else:
            if not cur:
                start = idx
            cur.append(line)
    if cur:
        chunks.append({"text": "\n".join(cur), "start": start, "end": len(lines)})
    return chunks


def slice_by_fixed(raw):
    """按字符长度切，带重叠。行号按块内首末字符推算。"""
    chunks = []
    start = 0
    while start < len(raw):
        piece = raw[start:start + FIXED_SIZE]
        s_line = raw.count("\n", 0, start) + 1
        e_line = s_line + piece.count("\n")
        chunks.append({"text": piece, "start": s_line, "end": e_line})
        start += FIXED_SIZE - FIXED_OVERLAP
    return chunks


# ────────────────────────── 向量化与入库 ──────────────────────────


def embed(texts):
    req = urllib.request.Request(
        url=f"{OLLAMA_URL}/api/embed",
        data=json.dumps({"model": EMBED_MODEL, "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["embeddings"]


def build_schema(client):
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=72)
    schema.add_field("repository_id", DataType.VARCHAR, max_length=64)
    schema.add_field("snapshot_id", DataType.VARCHAR, max_length=128)
    schema.add_field("commit_sha", DataType.VARCHAR, max_length=64)
    schema.add_field("symbol_id", DataType.VARCHAR, max_length=72)   # "sym_" + 64 位摘要 = 68
    schema.add_field("file_path", DataType.VARCHAR, max_length=512)
    schema.add_field("start_line", DataType.INT64)
    schema.add_field("end_line", DataType.INT64)
    schema.add_field("chunk_index", DataType.INT64)
    schema.add_field("embedding_model", DataType.VARCHAR, max_length=64)
    schema.add_field("chunk_content_sha256", DataType.VARCHAR, max_length=64)
    schema.add_field("text", DataType.VARCHAR, max_length=8192)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIM)
    return schema


def index_to_milvus(client, collection, chunks, symbol_of):
    """chunks 里的每一块 → 一条向量记录 → 写进集合。"""
    if client.has_collection(collection):
        client.drop_collection(collection)

    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(collection_name=collection,
                             schema=build_schema(client),
                             index_params=index_params)

    rows = []
    texts = [c["text"] for c in chunks]
    vectors = []
    for i in range(0, len(texts), BATCH):
        vectors.extend(embed(texts[i:i + BATCH]))

    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        symbol_id = symbol_of(chunk)
        content_hash = _sha256(chunk["text"])
        rows.append({
            "chunk_id": make_chunk_id(symbol_id, idx, chunk["text"]),
            "repository_id": REPOSITORY_ID,
            "snapshot_id": SNAPSHOT_ID,
            "commit_sha": COMMIT_SHA,
            "symbol_id": symbol_id,
            "file_path": FILE_PATH,
            "start_line": chunk["start"],
            "end_line": chunk["end"],
            "chunk_index": idx,
            "embedding_model": EMBED_MODEL,
            "chunk_content_sha256": content_hash,
            "text": chunk["text"][:8000],
            "vector": vec,
        })

    client.insert(collection_name=collection, data=rows)
    client.load_collection(collection_name=collection)   # 不 load 搜索会报 collection not loaded
    return len(rows)


def search(client, collection, question, limit=3):
    qv = embed([question])[0]
    hits = client.search(
        collection_name=collection,
        data=[qv],
        filter=f'snapshot_id == "{SNAPSHOT_ID}"',
        limit=limit,
        output_fields=["start_line", "end_line", "symbol_id", "text"],
    )
    return hits[0]


# ────────────────────────── 主流程 ──────────────────────────


def main():
    raw = JAVA_FILE.read_text(encoding="utf-8")
    lines = raw.splitlines()
    IMPORTS.update(parse_imports(lines))   # 先解析 import，方法签名才能补全限定名

    class_symbol = make_symbol_id("Class", f"{PACKAGE_NAME}.{CLASS_NAME}")

    groups = {
        "code_chunks_v1": (
            slice_by_method(lines),
            lambda c: make_symbol_id("Method", c["canonical"]),
        ),
        "code_chunks_v1_paragraph": (
            slice_by_paragraph(lines),
            lambda c: class_symbol,
        ),
        "code_chunks_v1_fixed": (
            slice_by_fixed(raw),
            lambda c: class_symbol,
        ),
    }

    client = MilvusClient(uri=MILVUS_URI)
    counts = {}
    for name, (chunks, symbol_of) in groups.items():
        counts[name] = index_to_milvus(client, name, chunks, symbol_of)
        print(f"{name}: 写入 {counts[name]} 条")

    print("\n--- 检索「怎么把书借出去」 ---")
    for name in groups:
        hits = search(client, name, "怎么把书借出去")
        top = hits[0]
        print(f"{name:26s} 最高分 {top['distance']:.4f}  行 {top['entity']['start_line']}-{top['entity']['end_line']}")

    print("\n--- 方法集合里的一条记录长这样 ---")
    print(json.dumps({
        k: v for k, v in client.query(
            collection_name="code_chunks_v1",
            filter=f'snapshot_id == "{SNAPSHOT_ID}"',
            output_fields=["chunk_id", "symbol_id", "start_line", "end_line",
                           "embedding_model", "file_path"],
            limit=1,
        )[0].items() if k != "vector"
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
