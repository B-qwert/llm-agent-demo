# 基于代码知识图谱与大模型的业务逻辑智能问询系统

本仓库包含一个面向固定图书借阅 Java 样例的问询原型。网页支持直接问答、向量检索和图谱扩展三种模式，可查看回答引用的源码和行号。

| 当前成果 | 仓库内容 |
| --- | --- |
| 开发环境 | Git 协作规范、Neo4j 与 Milvus 容器、DeepSeek API 接入及连通性检查；验收记录见[开发环境成果与验收报告](docs/开发环境成果与验收报告.md)。 |
| 研究准备 | [文献调研与综述笔记](docs/文献调研与综述笔记.md)、[技术选型调研报告](docs/技术选型调研报告.md)。 |
| 可行性论证 | [图书借阅原型测试记录](docs/图书借阅原型测试记录.md)、[210 条问答验证报告](docs/图书借阅210条问答验证结果.md)和[功能验证清单](docs/图书借阅人工评测参考答案与功能验证清单.md)。 |

## 快速开始

安装并启动 Docker Desktop，使用 WSL 2 与 Linux containers。若安装提示重启，先保存工作并重启，再打开 Docker Desktop 和新的 PowerShell。项目建议为 Docker 分配至少 4 核、8 GB 内存，预留 20 GB 磁盘；这是本项目开发建议，不代表百万行代码库容量保障。

在项目根目录执行：

```powershell
python scripts/init_env.py
powershell -File scripts/dev.ps1 up
```

第一条命令只创建一次 `.env` 并随机生成数据库密码。第二条启动四个基础容器、等待健康检查、构建 Python 3.12 验收容器，运行数据库实际读写检索。首次需联网拉取镜像与 Python 依赖。再次运行不会重置数据库。

脚本启动方式只用到宿主机 Python 的标准库，数据库驱动安装在容器中。需在本机直接运行检查或测试时，使用 Python 3.12，并先安装 `requirements.txt`。

### 启动问询网页

在本机 `.env` 填写 `LLM_API_KEY`，然后执行：

```powershell
powershell -File scripts/platform.ps1 start
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。使用 B/C 前，启动 Ollama，并在网页为所选切分策略准备索引。具体操作见[问询平台使用说明](docs/问询平台使用说明.md)。

## LLM 接入

配置示例使用 DeepSeek。默认地址为 `https://api.deepseek.com`，模型为 `deepseek-v4-flash`。基础地址填到服务端点即可，客户端会追加 `/chat/completions`。接口采用 OpenAI 兼容的 Chat Completions 协议。

连通性测试发送固定短文本，默认关闭思考并将输出限制为 128 Token。服务不支持思考参数时，将 `LLM_THINKING` 留空。测试会消耗接口额度。

```powershell
powershell -File scripts/dev.ps1 llm
powershell -File scripts/dev.ps1 check
```

LLM 测试收到非空文本才算通过。全量检查要求三项全部 PASS；配置缺失、鉴权失败、限流、网络失败均返回非零退出码，不能计为通过。报告保存在 `reports/`，默认不纳入 Git。离线单元测试只能验证代码行为，不能证明真实 API 已接通。

## 访问与日常操作

| 服务 | 本机地址 | 用途 |
| --- | --- | --- |
| Neo4j Browser | http://localhost:7474 | 用户名 neo4j，密码见本地 .env |
| Neo4j Bolt | bolt://localhost:7687 | Python 驱动连接 |
| Milvus | http://localhost:19530 | MilvusClient 连接 |
| Milvus 健康检查 | http://localhost:9091/healthz | 存活检测 |

etcd 和 MinIO 只在 Compose 内部网络访问。Milvus 使用本机隔离的开发配置，未开启用户鉴权，不应将端口绑定改为公网地址。三人分别运行本地环境；需要共享服务时另行配置认证、TLS 和网络访问控制。

```powershell
docker compose ps
docker compose logs --tail 100 neo4j milvus
powershell -File scripts/dev.ps1 stop
docker compose start
```

在本机运行单元测试：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

持久数据保存在五个 Docker 命名卷中。`stop` 和普通 `docker compose down` 保留数据；不要使用 `down -v`，它会删除卷。`.env` 的初始 Neo4j 密码只在空数据卷初始化时生效，已有数据的密码应在数据库内修改。

## 工程结构与资料

- `compose.yaml`：数据库、问询网页和验收容器。
- `bizcodeqa/llm.py`：可被后续业务模块复用的 LLM 客户端。
- `bizcodeqa/check.py`：真实连通性验收，带失败退出码与 JSON 报告。
- `bizcodeqa/platform/` 与 `web/`：本地 A/B/C 问询后端、样例索引准备及网页；模式切换、源码证据、历史与 JSON 导出见[使用说明](docs/问询平台使用说明.md)。
- `scripts/`：本地配置生成与 PowerShell 一键操作。
- `samples/book_borrow/`：图书借阅 Java 样例、快照登记与编译启动证据；运行 `python scripts/prototype/check_sample.py` 复现基础检查（需 JDK 17 或以上）。
- [协作规范](CONTRIBUTING.md)与[团队协作规范](docs/团队协作规范.md)：分支、提交、评审及全周期协作约定。
- [开发环境成果与验收报告](docs/开发环境成果与验收报告.md)：环境成果与连通性验收记录。
- [文献调研与综述笔记](docs/文献调研与综述笔记.md)：课题相关研究、研究问题与后续验证方向。
- [技术选型调研报告](docs/技术选型调研报告.md)：图数据库、向量数据库和 LLM API 的选型依据。
- [开题报告](docs/开题报告.md)：研究目标、技术路线、实验设计与进度安排。
- [Schema 设计规范](docs/Schema设计规范.md)：已确认采用的 v0.1.0 实体、关系、标识、溯源与版本规则。
- [图书借阅原型测试记录](docs/图书借阅原型测试记录.md)：样例冻结、编译启动证据和实施进度。[人工评测与功能验证清单](docs/图书借阅人工评测参考答案与功能验证清单.md)记录参考答案、评分口径及验证结果。

镜像版本参考 [Neo4j 5 发布说明](https://community.neo4j.com/t/neo4j-5-release/66912) 与 [Milvus 官方 Compose 配置](https://github.com/milvus-io/milvus/blob/v2.6.22/deployments/docker/standalone/docker-compose.yml)。后者在 v2.6.22 源码标签中仍引用 Milvus v2.6.21，本工程沿用 Milvus 与 etcd 版本；原 MinIO 镜像仓库现已无法公开拉取，因此改用 Coolify 从 MinIO 源码构建的固定版本镜像，而未将 Milvus 源码标签号当作镜像版本。版本固定用于开发复现，正式部署前需重新评估维护与升级。

操作依据：[Docker Desktop Windows 安装](https://docs.docker.com/desktop/setup/install/windows-install/)、[Neo4j Docker 部署](https://neo4j.com/docs/operations-manual/current/docker/introduction/)、[DeepSeek API](https://api-docs.deepseek.com/)。

远程仓库：[B-qwert/llm-agent-demo](https://github.com/B-qwert/llm-agent-demo)。
