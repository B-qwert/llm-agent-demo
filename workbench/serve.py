"""本地问答服务：问题 → Ollama 向量 → Milvus 检索 → DeepSeek 作答。

启动：<仓库根>/.venv/bin/python workbench/serve.py
打开：http://127.0.0.1:8777

零新依赖：复用仓库 bizcodeqa 的 urllib 客户端 + 已装的 pymilvus。
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 兼容两种运行位置：仓库内（<repo>/workbench/）与仓库外并列（<root>/code-insight-workbench/）
REPO = HERE.parent if (HERE.parent / "bizcodeqa").is_dir() else HERE.parent / "llm-agent-demo"
sys.path.insert(0, str(REPO))

from bizcodeqa.config import load_env  # noqa: E402

load_env(REPO / ".env")
from bizcodeqa.llm import chat  # noqa: E402

HTML_FILE = HERE / "代码问询工作台.html"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b")
MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
PORT = int(os.getenv("QA_PORT", "8777"))
TOP_K = 5

# 仓库 .env 里 LLM_MAX_TOKENS=128，对问答偏短；只在本进程内放宽，不改团队配置。
os.environ["LLM_MAX_TOKENS"] = "400"

# 索引由团队统一的 prepare 流程产出，状态写在 reports/platform（已被 .gitignore 排除）。
# 前端沿用的三个 key 映射到对应 profile 的 index 文件，集合名不再写死。
INDEX_DIR = REPO / "reports" / "platform"
PROFILE_FILES = {
    "method": "index.json",
    "paragraph": "index_paragraph_blank_v1.json",
    "fixed": "index_character_400_80.json",
}
PROFILE_LABELS = {"method": "按方法/字段", "paragraph": "按段落", "fixed": "按定长"}


def load_index(chunk):
    """读某个切分配置的激活索引；文件不存在返回 None。"""
    path = INDEX_DIR / PROFILE_FILES.get(chunk, "index.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def chunk_lookup(index):
    """chunk_id → 片段本体，用来取 Milvus 里不存的正文。"""
    return {c["chunk_id"]: c for c in index.get("chunks", [])}

# 源码目录与查询历史都放在工作台自己的目录里，不进仓库。
SOURCE_DIRS = [HERE.parent / "code-slicing" / "samples", REPO / "samples"]
HISTORY_FILE = HERE / "_runtime" / "history.jsonl"
_LOCK = threading.Lock()

# 方法切分对应的 12 个方法起始行（与 samples/bookBorrowSystem.java 一致），
# 用于评测时把命中块的行号换算回方法名。
METHODS = [
    ("main", 18), ("initData", 23), ("startSystem", 42), ("borrowRank", 97),
    ("addBook", 129), ("showBook", 161), ("deleteBook", 179), ("borrowBook", 211),
    ("returnBook", 257), ("addReader", 305), ("showReader", 335), ("deleteReader", 351),
]

# 评测固定题集：每题给出期望命中的方法，用来算首位命中率。
EVAL_SET = [
    ("借书前需要检查哪些条件？", "borrowBook"),
    ("有未还图书时还能再借吗？", "borrowBook"),
    ("图书排行榜是按什么排序的？", "borrowRank"),
    ("删除一本已经借出的书会怎样？", "deleteBook"),
    ("归还图书的流程是什么？", "returnBook"),
    ("新增一本图书要录入哪些信息？", "addBook"),
    ("怎么查看所有读者的借阅情况？", "showReader"),
    ("系统启动后先做了什么？", "startSystem"),
]

CA_FILE = HERE / "certs" / "macos-system-ca.pem"


def ensure_ca():
    """把系统钥匙串里的根证书导出成 PEM，供 Python 的 TLS 校验使用。

    这台机器上有 aTrust 一类客户端做 HTTPS 中间人，它的根证书只在系统钥匙串里，
    Python 自带的证书池不认识，会报 CERTIFICATE_VERIFY_FAILED。
    """
    if CA_FILE.exists() and CA_FILE.stat().st_size > 1000:
        os.environ["SSL_CERT_FILE"] = str(CA_FILE)
        return
    if sys.platform != "darwin":
        return
    pieces = []
    for keychain in (
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        "/Library/Keychains/System.keychain",
    ):
        try:
            out = subprocess.run(
                ["security", "find-certificate", "-a", "-p", keychain],
                capture_output=True, text=True, timeout=20,
            ).stdout
            if out:
                pieces.append(out)
        except Exception:
            continue
    data = "\n".join(pieces)
    if data.count("BEGIN CERTIFICATE") < 10:
        print("提示：未能从系统钥匙串导出证书，HTTPS 调用可能失败")
        return
    CA_FILE.parent.mkdir(parents=True, exist_ok=True)
    CA_FILE.write_text(data, encoding="utf-8")
    os.environ["SSL_CERT_FILE"] = str(CA_FILE)
    print(f"已导出系统根证书 {data.count('BEGIN CERTIFICATE')} 张 → {CA_FILE}")


ensure_ca()

_milvus = None


def milvus():
    global _milvus
    if _milvus is None:
        from pymilvus import MilvusClient
        _milvus = MilvusClient(uri=MILVUS_URI)
    return _milvus


def embed(text):
    payload = json.dumps({"model": EMBED_MODEL, "input": text}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["embeddings"][0]


def retrieve(question, chunk, k=TOP_K):
    """按团队口径检索：同一快照过滤 + 查询指令前缀 + 方法模式只召回 Method。"""
    index = load_index(chunk)
    if not index:
        raise RuntimeError("未找到 " + chunk + " 的索引（先跑 code-slicing/slice_to_milvus.py）")
    name = index["collection"]
    client = milvus()
    if not client.has_collection(name):
        raise RuntimeError("集合不存在：" + name + "（重新跑 slice_to_milvus.py）")
    vec = embed(index.get("query_instruction", "") + question)
    query_filter = (
        "repository_id == " + json.dumps(index["repository_id"])
        + " and snapshot_id == " + json.dumps(index["snapshot_id"])
    )
    if index.get("chunking", {}).get("strategy") == "method":
        query_filter += ' and entity_type == "Method"'
    rows = client.search(
        collection_name=name,
        data=[vec],
        limit=k,
        filter=query_filter,
        output_fields=["chunk_id", "symbol_id", "start_line", "end_line", "content_sha256"],
        search_params={"metric_type": "COSINE"},
    )[0]
    lookup = chunk_lookup(index)
    hits = []
    for row in rows:
        ent = row.get("entity", {})
        cid = ent.get("chunk_id") or row.get("id")
        src = lookup.get(cid, {})
        hits.append({
            "chunk_id": cid,
            "score": round(float(row.get("distance", 0.0)), 4),
            "symbol_id": ent.get("symbol_id", src.get("symbol_id", "")),
            "file_path": src.get("file_path", ""),
            "start_line": int(ent.get("start_line", src.get("start_line", 0)) or 0),
            "end_line": int(ent.get("end_line", src.get("end_line", 0)) or 0),
            "text": src.get("code", ""),
        })
    return name, hits


def build_context(hits):
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[片段{i}] 文件 {Path(h['file_path']).name}，行 {h['start_line']}-{h['end_line']}，相似度 {h['score']}\n{h['text']}"
        )
    return "\n\n".join(parts)


SYSTEM_GROUNDED = (
    "你是代码问询助手。只能依据用户提供的代码片段回答，每条结论后面用（文件名 行号）标注依据。"
    "片段里没有的信息就直接说「代码里没有这部分」，禁止编造方法名、字段名或行号。"
    "中文回答，120 字以内，直接给结论，不要复述问题。"
)

SYSTEM_PLAIN = (
    "你是通用编程助手。本次没有提供项目代码，按常识回答即可，但不要臆测具体的方法名、字段名或行号，"
    "也不要把猜测写成事实。中文回答，120 字以内。"
)


def ask_llm(question, hits=None):
    if hits:
        user = "问题：" + question + "\n\n可用代码片段：\n" + build_context(hits)
        system = SYSTEM_GROUNDED
    else:
        user = "问题：" + question
        system = SYSTEM_PLAIN
    res = chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    return res["content"], res.get("model", "")


def graph_context(symbol_ids):
    """C 模式：从 Neo4j 补一层调用关系；没数据就跳过，不阻断回答。"""
    try:
        from neo4j import GraphDatabase
    except Exception:
        return []
    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=("neo4j", os.getenv("NEO4J_PASSWORD", "")),
        )
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as s:
            total = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            if not total:
                return []
            rows = s.run(
                "MATCH (a)-[r]->(b) WHERE a.symbol_id IN $ids OR b.symbol_id IN $ids "
                "RETURN coalesce(a.name,a.symbol_id) AS src, type(r) AS rel, "
                "coalesce(b.name,b.symbol_id) AS dst LIMIT 12",
                ids=list(symbol_ids),
            ).data()
            return [f"{r['src']} -{r['rel']}→ {r['dst']}" for r in rows]
    except Exception:
        return []


def chunk_map(chunk):
    """返回某个切分配置的全部切片区间，直接读激活索引，不再查 Milvus。"""
    index = load_index(chunk)
    if not index:
        raise RuntimeError("未找到 " + chunk + " 的索引（先跑 code-slicing/slice_to_milvus.py）")
    chunks = sorted(index.get("chunks", []), key=lambda c: (int(c.get("start_line", 0)), int(c.get("end_line", 0))))
    segs = [
        {
            "i": i,
            "start": int(c.get("start_line", 0)),
            "end": int(c.get("end_line", 0)),
            "symbol": (c.get("symbol_id") or "")[:12],
            "name": c.get("name", ""),
        }
        for i, c in enumerate(chunks)
    ]
    total = max([s["end"] for s in segs], default=0)
    return {
        "chunk": chunk,
        "collection": index["collection"],
        "count": len(segs),
        "total_lines": total,
        "segments": segs,
    }


def graph_overview(limit=60):
    """Neo4j 全景：节点/边数量与关系清单，没数据就返回空，前端显示空态。"""
    out = {"total": 0, "edges": [], "error": None}
    try:
        from neo4j import GraphDatabase
    except Exception:
        out["error"] = "未安装 neo4j 驱动"
        return out
    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=("neo4j", os.getenv("NEO4J_PASSWORD", "")),
        )
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as s:
            out["total"] = int(s.run("MATCH (n) RETURN count(n) AS c").single()["c"])
            if not out["total"]:
                return out
            out["edges"] = s.run(
                "MATCH (a)-[r]->(b) RETURN coalesce(a.name, a.symbol_id) AS src, "
                "type(r) AS rel, coalesce(b.name, b.symbol_id) AS dst LIMIT $n",
                n=limit,
            ).data()
        return out
    except Exception as e:
        out["error"] = str(e)[:120]
        return out


TOTAL_LINES = 383


def method_span(name):
    """期望方法的 [起始行, 结束行]，用来判断片段有没有覆盖到它。"""
    for i, (m, start) in enumerate(METHODS):
        if m == name:
            end = METHODS[i + 1][1] - 1 if i + 1 < len(METHODS) else TOTAL_LINES
            return start, end
    return None


def cover_ratio(start, end, span):
    """片段盖住期望方法的比例，0 表示完全没沾到。"""
    if not span:
        return 0.0
    inter = min(int(end), span[1]) - max(int(start), span[0]) + 1
    return max(inter, 0) / (span[1] - span[0] + 1)


def method_of_line(line, total=384):
    """把行号换算成它所在的方法名。行号落在两个方法之间时归到前一个。"""
    name = METHODS[0][0]
    for m, start in METHODS:
        if line >= start:
            name = m
        else:
            break
    return name if 0 < line <= total else "—"


def record_history(item):
    """每次问答追加一行到 history.jsonl，并让页面能读到。"""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with HISTORY_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as exc:
        print("历史写入失败：", exc)


def read_history(limit=30):
    if not HISTORY_FILE.exists():
        return []
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return []
    items = []
    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(items))


def overview():
    """总览看板的数据源：三套集合规模、向量维度、源码范围、近期统计。"""
    out = {
        "collections": [],
        "dim": 1024,
        "embed_model": EMBED_MODEL,
        "llm_model": os.getenv("LLM_MODEL", ""),
        "sources": scan_sources(),
        "stats": {},
        "errors": [],
    }
    client = milvus()
    for key in PROFILE_FILES:
        index = load_index(key)
        row = {
            "key": key,
            "label": PROFILE_LABELS.get(key, key),
            "name": index["collection"] if index else "-",
            "exists": bool(index),
            "count": len(index.get("chunks", [])) if index else 0,
            "lines": max([int(c.get("end_line", 0)) for c in index.get("chunks", [])], default=0) if index else 0,
            "profile": index.get("chunking", {}).get("profile_id", "") if index else "",
        }
        out["collections"].append(row)
    for key in PROFILE_FILES:
        index = load_index(key)
        if not index:
            continue
        try:
            if not client.has_collection(index["collection"]):
                out["errors"].append(f"{index['collection']}: 集合不存在，需要重跑切片入库")
                continue
            out["dim"] = int(index.get("embedding_dimension", out["dim"]))
        except Exception as exc:
            out["errors"].append(f"{index['collection']}: {str(exc)[:80]}")
        break

    hist = read_history(50)
    hits = [h for h in hist if h.get("top_score") is not None]
    out["stats"] = {
        "total": len(hist),
        "avg_ms": int(sum(h.get("elapsed_ms", 0) for h in hist) / len(hist)) if hist else 0,
        "avg_top": round(sum(h["top_score"] for h in hits) / len(hits), 3) if hits else None,
        "by_mode": {m: len([h for h in hist if h.get("mode") == m]) for m in ("A", "B", "C")},
    }
    return out


def scan_sources():
    """列出当前可供索引的源码文件，多文件接入的可见范围。"""
    files = []
    for base in SOURCE_DIRS:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in (".java", ".py", ".js", ".ts"):
                continue
            try:
                n = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                n = 0
            files.append({
                "path": str(p.relative_to(HERE.parent)),
                "name": p.name,
                "lines": n,
                "kb": round(p.stat().st_size / 1024, 1),
            })
    return files


def eval_run(chunk="method"):
    """跑固定题集，返回每题的首位命中与耗时，用来算首位命中率。"""
    rows = []
    started = time.time()
    for question, expected in EVAL_SET:
        t0 = time.time()
        try:
            _, hits = retrieve(question, chunk, 5)
        except Exception as exc:
            rows.append({"question": question, "expected": expected, "got": "—",
                         "hit": False, "hit5": False, "cover": 0.0,
                         "error": str(exc)[:80], "ms": 0})
            continue
        top = hits[0] if hits else None
        got = method_of_line(int(top["start_line"])) if top else "—"
        span = method_span(expected)
        # 字符与段落段会跨方法：期望方法至少被盖住一半才算命中，擦边不算
        c1 = cover_ratio(top["start_line"], top["end_line"], span) if top else 0.0
        c5 = max([cover_ratio(h["start_line"], h["end_line"], span) for h in hits], default=0.0)
        rows.append({
            "question": question,
            "expected": expected,
            "got": got,
            "hit": c1 >= 0.5,
            "hit5": c5 >= 0.5,
            "cover": round(c1, 3),
            "score": float(top["score"]) if top else 0.0,
            "lines": f"{top['start_line']}-{top['end_line']}" if top else "—",
            "ms": int((time.time() - t0) * 1000),
        })
    hit = len([r for r in rows if r["hit"]])
    hit5 = len([r for r in rows if r.get("hit5")])
    return {
        "chunk": chunk,
        "rows": rows,
        "hit": hit,
        "hit5": hit5,
        "total": len(rows),
        "rate": round(hit / len(rows), 3) if rows else 0.0,
        "rate5": round(hit5 / len(rows), 3) if rows else 0.0,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def run(question, mode, chunk):
    started = time.time()
    hits = []
    collection = None
    if mode in ("B", "C"):
        collection, hits = retrieve(question, chunk, TOP_K)
    answer, model = ask_llm(question, hits if hits else None)
    graph = []
    if mode == "C" and hits:
        graph = graph_context({h["symbol_id"] for h in hits if h["symbol_id"]})
    result = {
        "answer": answer,
        "mode": mode,
        "chunk": chunk,
        "collection": collection,
        "model": model,
        "elapsed_ms": int((time.time() - started) * 1000),
        "hits": [{k: v for k, v in h.items() if k != "text"} for h in hits],
        "snippets": [{"lines": f"{h['start_line']}-{h['end_line']}", "score": h["score"],
                      "symbol_id": h["symbol_id"], "text": h["text"]} for h in hits],
        "graph": graph,
    }
    record_history({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "mode": mode,
        "chunk": chunk,
        "elapsed_ms": result["elapsed_ms"],
        "hits": len(hits),
        "top_score": hits[0]["score"] if hits else None,
        "top_method": method_of_line(hits[0]["start_line"]) if hits else None,
    })
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "codeqa/1.0"

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/health":
            state = {"ok": True}
            try:
                state["ollama"] = bool(embed("健康检查"))
            except Exception as e:
                state["ok"] = False
                state["ollama_error"] = str(e)[:120]
            try:
                client = milvus()
                state["milvus"] = any(
                    (lambda idx: bool(idx) and client.has_collection(idx["collection"]))(load_index(k))
                    for k in PROFILE_FILES
                )
            except Exception as e:
                state["ok"] = False
                state["milvus_error"] = str(e)[:120]
            self._json(state)
        elif self.path.startswith("/api/chunks"):
            qs = urllib.parse.urlparse(self.path).query
            chunk = urllib.parse.parse_qs(qs).get("chunk", ["method"])[0]
            try:
                self._json(chunk_map(chunk))
            except Exception as e:
                self._json({"error": str(e)[:160]}, 500)
        elif self.path == "/api/graph":
            try:
                self._json(graph_overview())
            except Exception as e:
                self._json({"error": str(e)[:160]}, 500)
        elif self.path == "/api/overview":
            try:
                self._json(overview())
            except Exception as e:
                self._json({"error": str(e)[:160]}, 500)
        elif self.path.startswith("/api/history"):
            qs = urllib.parse.urlparse(self.path).query
            limit = 30
            try:
                limit = min(200, max(1, int(urllib.parse.parse_qs(qs).get("limit", ["30"])[0])))
            except Exception:
                pass
            self._json({"items": read_history(limit)})
        elif self.path == "/api/scan":
            self._json({"files": scan_sources()})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/eval":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                chunk = str(payload.get("chunk", "method"))
                if chunk not in PROFILE_FILES:
                    chunk = "method"
                self._json(eval_run(chunk))
            except Exception as exc:
                self._json({"error": str(exc)[:200]}, 500)
            return
        if self.path != "/api/ask":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            question = str(payload.get("question", "")).strip()
            mode = str(payload.get("mode", "B")).upper()[:1] or "B"
            chunk = str(payload.get("chunk", "method"))
            if not question:
                self._json({"error": "问题不能为空"}, 400)
                return
            if len(question) > 2000:
                self._json({"error": "问题过长"}, 400)
                return
            if mode not in ("A", "B", "C"):
                mode = "B"
            if chunk not in PROFILE_FILES:
                chunk = "method"
            self._json(run(question, mode, chunk))
        except Exception as exc:
            self._json({"error": str(exc)[:200]}, 500)


def main():
    if not HTML_FILE.exists():
        raise SystemExit("找不到页面文件：" + str(HTML_FILE))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"服务已启动 → http://127.0.0.1:{PORT}    (embed={EMBED_MODEL}, milvus={MILVUS_URI})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
