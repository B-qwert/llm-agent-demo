# -*- coding: utf-8 -*-
"""按团队统一口径建三套样例索引：method / paragraph / character。

切分、向量化、集合命名、字段与索引参数全部复用 `bizcodeqa.platform`：
    chunking.py  决定切分口径与 profile_id
    sample.py    决定登记快照与实体
    stores.py    决定 Embedding 模型、模型摘要、Milvus 连接
    prepare.py   决定隔离集合命名、FLAT + COSINE、动态字段、图谱同批写入与数量校验

本文件只做"一次跑三种策略"的编排，不再维护第二套切分实现。
ast 与 token 两种按当前要求不做。

运行：.venv/bin/python code-slicing/slice_to_milvus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CANDIDATES = (HERE.parent, HERE.parent / "llm-agent-demo")
REPO = next((p for p in _CANDIDATES if (p / "bizcodeqa").is_dir()), None)
if REPO is None:
    raise SystemExit("找不到 bizcodeqa 包：请把本脚本放在仓库内，或与仓库同级")

sys.path.insert(0, str(REPO))

from bizcodeqa.config import load_env  # noqa: E402

load_env(REPO / ".env")

from bizcodeqa.platform.prepare import prepare  # noqa: E402

# 只跑现有三种。method 用团队默认参数；character 沿用本机 400/80 的对照口径。
PROFILES = (
    ("method", 800, 100),
    ("paragraph", 800, 100),
    ("character", 400, 80),
)


def main() -> int:
    done, failed = [], []
    for strategy, size, overlap in PROFILES:
        print(f"\n=== {strategy}（chunk={size} overlap={overlap}） ===", flush=True)
        try:
            result = prepare(
                strategy, size, overlap, progress=lambda msg: print("  · " + msg, flush=True)
            )
        except Exception as exc:  # 单个策略失败不影响其余，最后统一汇总退出码
            failed.append((strategy, str(exc)))
            print(f"  ✗ 失败：{exc}", flush=True)
            continue
        done.append(result)
        print(f"  ✓ {result['chunk_count']} 段 → {result['collection']}", flush=True)

    print("\n=== 汇总 ===")
    for r in done:
        print(f"{r['profile_id']:>22}  {r['chunk_count']:>3} 段  {r['collection']}")
    print(f"合计 {sum(r['chunk_count'] for r in done)} 段")
    if failed:
        print("失败项：" + "；".join(f"{s}（{m}）" for s, m in failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
