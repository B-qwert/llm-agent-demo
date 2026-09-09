# 三人协作规范

本规范用于本课题代码、部署配置与技术文档的共同维护。原始分工以《三人任务分工进度计划_详细分工.xlsx》为准。本阶段 Git 仓库与规范负责人为白乐刚；Neo4j、Milvus、LLM API 三项由白乐刚、夏高婷、周笑彤共同完成。

## 职责与评审

为方便执行，建议白乐刚维护仓库、CI 与集成，夏高婷重点复核 Neo4j，周笑彤重点复核 Milvus 与 LLM 接口。这是本阶段建议的复核分工，不替代原表共同负责的安排。每项工作指定一位实施者和至少一位非作者评审者，第三人复现启动与验收。

## 仓库与分支

主分支为 `main`，仅保留可复现版本。日常从最新 main 创建短期分支，如 `feat/neo4j-smoke`、`fix/llm-timeout`、`docs/dev-setup`。每个分支围绕一个问题，完成后发 Pull Request，至少一位非作者批准且 CI 通过，使用 squash 合并。禁止直接向 main 推送、禁止对共享分支 force push。

远程仓库已确定为 `https://github.com/B-qwert/llm-agent-demo.git`。由负责人在 GitHub 添加其余两名成员，并配置分支保护。仓库公开性由团队在平台确认。后续是否开源及采用何种许可证由团队确认；课题介绍中的预期成果不等于现在授权公开资料。

```powershell
git remote -v
git config user.name "本人姓名"
git config user.email "本人邮箱"
git push -u origin main
git switch -c feat/your-topic
```

首次 push 前检查暂存区没有 `.env`、密钥、数据库卷及未授权业务代码。远程开启 main 分支保护、至少一个审批、禁止 force push 和删除、要求 `offline` CI 成功。这些远程规则需在平台实际配置，本地文档不能强制执行。

## 提交与问题跟踪

提交格式 `类型(范围): 具体变化`。类型采用 feat、fix、docs、test、refactor、chore；范围可用 infra、neo4j、milvus、llm。正文说明原因和验证方式，避免使用“修改一些东西”等含糊描述。

Issue 记录目标、负责人、验收条件与依赖。PR 描述问题及最终行为、涉及配置、测试结果与待办事项。跨服务接口、Schema 和依赖版本变更需先在 Issue 中说明影响，再随 PR 更新文档。以 `symbol_id` 关联图谱和向量记录的正式契约留到原计划 Schema 设计阶段，本阶段测试数据不构成最终模型。

## 配置、数据与测试

统一 UTF-8，Python 四空格，YAML 两空格。提交前运行 `python -m unittest discover -s tests -v`；基础设施变更额外运行 `docker compose config --quiet` 和数据库验收。LLM 变更通过离线测试后由有额度的成员执行真实测试，不把付费 API 密钥放入 PR 或 CI 日志。

固定直接依赖及镜像版本，升级时在独立 PR 验证；传递依赖当前由 pip 解析，本工程尚未提供完整哈希锁文件。记录实际验收时间与服务版本，不能用离线 mock 结果代替部署或联网成功。

每天更新当前 Issue 的阻碍与下一步，周末合并已验证功能并由第三人从干净目录复现。阶段完成标准为部署可重现、验收全通过、证据齐全，随后再更新 Excel 状态。
