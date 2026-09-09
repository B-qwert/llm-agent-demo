# 业务逻辑智能问询系统开发环境

本工程对应课题的四项底座任务：Git 协作规范、Neo4j 部署、Milvus 部署、LLM API 接入与连通性测试。部署目标为 Windows 上的 Docker Desktop 与 WSL 2，数据库使用 Linux 容器。当前验收状态见 [开发环境交付与验收](docs/开发环境交付与验收.md)。

## 快速开始

安装并启动 Docker Desktop，使用 WSL 2 与 Linux containers。若安装提示重启，先保存工作并重启，再打开 Docker Desktop 和新的 PowerShell。项目建议为 Docker 分配至少 4 核、8 GB 内存，预留 20 GB 磁盘；这是本项目开发建议，不代表百万行代码库容量保障。

在项目根目录执行：

```powershell
python scripts/init_env.py
powershell -File scripts/dev.ps1 up
```

第一条命令只创建一次 `.env` 并随机生成数据库密码。第二条启动四个基础容器、等待健康检查、构建 Python 3.12 验收容器，运行数据库实际读写检索。首次需联网拉取镜像与 Python 依赖。再次运行不会重置数据库。

本机 Python 仅需支持标准库；数据库驱动在容器内安装，避免本机 Python 3.14 与二进制依赖的兼容问题。若已有 Python 3.12，可创建 `.venv`、安装 `requirements.txt` 后直接运行 `python -m bizcodeqa.check`。

## LLM 接入

已按用户选型配置 DeepSeek：`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-v4-flash`。编辑 `.env` 填写 `LLM_API_KEY`。基础地址不要带 `/chat/completions` 后缀。本实现支持 OpenAI 兼容的 Chat Completions 协议；原生 Claude Messages 协议需要另写适配器。

模型名已对照 [DeepSeek 官方文档](https://api-docs.deepseek.com/) 核实，但账号权限仍需真实调用验证。短连通性测试配置 `LLM_THINKING=disabled`，避免默认思考模式耗尽 128 token 的测试预算；其他兼容服务不支持此参数时将该项留空。业务推理阶段可按需求重新配置模式和预算。测试默认限制 128 输出 token，发送固定的短文本，不上传课题资料或业务源码。调用会消耗服务商额度。

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
python -m unittest discover -s tests -v
```

持久数据保存在五个 Docker 命名卷中。`stop` 和普通 `docker compose down` 保留数据；不要使用 `down -v`，它会删除卷。`.env` 的初始 Neo4j 密码只在空数据卷初始化时生效，已有数据的密码应在数据库内修改。

## 工程结构与资料

- `compose.yaml`：Neo4j、Milvus、etcd、MinIO 与验收容器。
- `bizcodeqa/llm.py`：可被后续业务模块复用的 LLM 客户端。
- `bizcodeqa/check.py`：真实连通性验收，带失败退出码与 JSON 报告。
- `scripts/`：本地配置生成与 PowerShell 一键操作。
- [协作规范](CONTRIBUTING.md)：分支、提交、评审、三人职责。
- [开发环境交付与验收](docs/开发环境交付与验收.md)：依据、验收标准、剩余事项。

镜像版本参考 [Neo4j 5 发布说明](https://community.neo4j.com/t/neo4j-5-release/66912) 与 [Milvus 官方 Compose 配置](https://github.com/milvus-io/milvus/blob/v2.6.22/deployments/docker/standalone/docker-compose.yml)。后者在 v2.6.22 源码标签中仍引用 Milvus v2.6.21，本工程沿用配置内的版本与配套 etcd/MinIO，而未将标签号当作镜像版本。版本固定用于开发复现，正式部署前需重新评估维护与升级。

操作依据：[Docker Desktop Windows 安装](https://docs.docker.com/desktop/setup/install/windows-install/)、[Neo4j Docker 部署](https://neo4j.com/docs/operations-manual/current/docker/introduction/)、[DeepSeek API](https://api-docs.deepseek.com/)。

远程仓库：[B-qwert/llm-agent-demo](https://github.com/B-qwert/llm-agent-demo)。
