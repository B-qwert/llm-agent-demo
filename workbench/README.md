# 代码问询工作台（workbench）

单机闭环版：**提问 → Ollama 向量化 → Milvus 检索 → DeepSeek 作答**，页面把索引、检索打分与链路状态一起画出来。

## 与 `web/` 的关系

仓库里的 `web/` 是课题组原型外壳（“知码 CODE INSIGHT”，自带后端接口约定）；本目录是另一套**独立可跑的完整闭环**，自带 `serve.py` 服务端与单文件页面，不依赖也不修改 `web/`。两者可并存，评审时请当作两条并行方案看，不要互相覆盖。

## 启动前需要

1. Milvus 已起：`docker compose up -d`，`127.0.0.1:19530` 可连（macOS 上由 OrbStack 提供，重启电脑后要手动打开等绿灯）
2. Ollama 常驻，且已 `ollama pull qwen3-embedding:0.6b`
3. 仓库根有 `.env`（从 `.env.example` 复制后填 `LLM_API_KEY`），
4. 三套集合已建：先跑 `code-slicing/slice_to_milvus.py`

## 运行

macOS：双击 `启动问询平台.command`，或

```bash
cd <仓库根>
.venv/bin/python workbench/serve.py
```

Windows（PowerShell）：

```powershell
cd <仓库根>
.\.venv\Scripts\python.exe workbench\serve.py
```

打开 `http://127.0.0.1:8777`，如端口被占可用环境变量 `QA_PORT` 指定别的端口。

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/` | 页面（每次请求重读 HTML，改页面不用重启） |
| GET | `/api/health` | Ollama / Milvus 连通性 |
| GET | `/api/overview` | 集合规模、维度、模型、源码范围 |
| GET | `/api/chunks?chunk=` | 三套切分的行号区间，用于索引视图 |
| GET | `/api/graph` | Neo4j 节点与关系，用于调用关系图 |
| GET | `/api/history` | 查询历史 |
| GET | `/api/scan` | 可索引的源码文件 |
| POST | `/api/ask` | 提问，`{question, mode(A/B/C), chunk(method/paragraph/fixed)}` |
| POST | `/api/eval` | 批量评测，`{chunk}`，返回 8 题首位命中率 |

## 不入库的东西

`certs/`（本机系统根证书导出）、`_runtime/`（查询历史）、`_backup/`、`_shots/` 都在 `.gitignore` 里。首次运行会调用 `security find-certificate` 自动生成 `certs/macos-system-ca.pem`，这是为了绕过本机 HTTPS 中间人（aTrust 一类客户端）；非 macOS 会跳过这一步。

## 已知限制

- 目前只索引 `samples/book_borrow/src/experiment/bookBorrowSystem.java` 一个源码文件，多文件/多仓库接入还没做
- 评测集是固定 8 题，只对方法切分跑过（首位命中 4/8）
- 真实作答需要可用的 DeepSeek 额度，离线只能验前两段链路
