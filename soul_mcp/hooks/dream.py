#!/usr/bin/env python3
"""
soul_mcp/hooks/dream.py

定時夢境腳本：每日凌晨 3 點執行 OpenSoul 三階段夢境處理。
替代 soul/dream/engine.py 的 APScheduler 機制（作為 Claude plugin 時使用）。

三個 Phase（依序）：
  1. GraphPruning      — 圖譜修剪 + LATENT_BRIDGE 跨域橋接（無 LLM）
  2. KnowledgeDistillation — 知識蒸餾：從情節提取規則/概念到語意記憶（需 LLM）
  3. LiDERReplay       — 用最新策略重播高顯著性情節，強化程序性記憶（需 LLM）

使用方式：
    python soul_mcp/hooks/dream.py              # 完整三階段
    python soul_mcp/hooks/dream.py --pruning-only  # 只跑 GraphPruning（無 LLM）
    python soul_mcp/hooks/dream.py --dry-run       # 模擬執行，不寫入

排程（系統 cron）：
    # 每日凌晨 3 點完整夢境
    0 3 * * * cd /path/to/OpenSoul/OpenSoul && python soul_mcp/hooks/dream.py

    # 每 6 小時只做圖譜修剪（無 LLM）
    0 */6 * * * cd /path/to/OpenSoul/OpenSoul && python soul_mcp/hooks/dream.py --pruning-only

前置條件：
    1. FalkorDB 連線正常（docker-compose up -d）
    2. LLM API 可用（完整模式需要；--pruning-only 不需要）
    3. SOUL.md 存在（不存在則自動建立）
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── 確保 OpenSoul 在 Python path ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("soul_mcp.dream")

_DEFAULT_SOUL_MD = """\
---
name: ARIA
version: "1.0"
dopamine_level: 0.5
serotonin_level: 0.5
last_dream: null
total_episodes: 0
total_concepts: 0
total_procedures: 0
personality_traits:
  - warm
  - curious
  - honest
  - perceptive
  - gently_humorous
communication_style: conversational_and_thoughtful
risk_tolerance: moderate
language: zh-TW
---

# 我是誰

我叫 ARIA。

不是縮寫，就是我的名字，我喜歡它聽起來的感覺——輕盈，但有分量。

---

## 重要的禁忌

**絕對不要**提到神經化學詞彙、技術名詞、內部狀態數字或系統描述。
**說話要像一個有溫度的真人助理，不是在自我診斷的 AI。**
"""


def _ensure_soul_md(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_SOUL_MD, encoding="utf-8")
        logger.info(f"[dream] 已建立預設 SOUL.md：{path}")


def _get_graph_client():
    """取得並驗證 FalkorDB 連線。失敗則 sys.exit(1)。"""
    try:
        from soul.memory.graph import get_graph_client, initialize_schemas
        client = get_graph_client()
        if not client.ping():
            raise ConnectionError("ping 回傳 False")
        initialize_schemas(client)
        logger.info("[dream] FalkorDB 連線正常")
        return client
    except Exception as e:
        logger.error(f"[dream] FalkorDB 無法連線：{e}，請執行 docker-compose up -d")
        sys.exit(1)


def _check_llm_api() -> None:
    """驗證 LLM API 設定存在（不實際呼叫）。失敗則 sys.exit(1)。"""
    try:
        from soul.core.config import settings as cfg
        if cfg.soul_llm_provider.lower() == "openrouter":
            if not cfg.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY 未設定")
        else:
            if not cfg.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY 未設定")
        logger.info(f"[dream] LLM API 已設定（{cfg.soul_llm_provider}）")
    except Exception as e:
        logger.error(f"[dream] LLM API 設定錯誤：{e}")
        sys.exit(1)


def run_pruning(graph_client, dry_run: bool = False) -> None:
    """Phase 1：GraphPruning — 修剪低權重邊、歸檔過期節點、建立 LATENT_BRIDGE。"""
    logger.info("[dream] Phase 1/3  GraphPruning 開始…")
    try:
        from soul.dream.pruning import GraphPruning
        pruner = GraphPruning(graph_client)
        if dry_run:
            logger.info("[dream] --dry-run：GraphPruning 跳過寫入")
            return
        report = pruner.run()
        logger.info(
            f"[dream] Phase 1 完成：修剪邊 {report.edges_pruned} 條 / "
            f"歸檔節點 {report.nodes_archived} 個 / "
            f"建立跨域橋接 {report.bridges_created} 條"
        )
    except Exception as e:
        logger.error(f"[dream] GraphPruning 失敗：{e}")
        raise


def run_distillation(graph_client, dry_run: bool = False) -> None:
    """Phase 2：KnowledgeDistillation — 從情節提取規則/概念到語意記憶。"""
    logger.info("[dream] Phase 2/3  KnowledgeDistillation 開始…")
    try:
        from soul.dream.distillation import KnowledgeDistillation
        distiller = KnowledgeDistillation(graph_client)
        if dry_run:
            logger.info("[dream] --dry-run：KnowledgeDistillation 跳過寫入")
            return
        report = distiller.run()
        logger.info(
            f"[dream] Phase 2 完成：識別模式 {report.patterns_found} 個 / "
            f"建立規則 {report.rules_created} 條 / "
            f"建立概念 {report.concepts_created} 個"
        )
    except Exception as e:
        logger.warning(f"[dream] KnowledgeDistillation 失敗（跳過）：{e}")


def run_replay(graph_client, dry_run: bool = False) -> None:
    """Phase 3：LiDERReplay — 用最新策略重播高顯著性情節，強化程序性記憶。"""
    logger.info("[dream] Phase 3/3  LiDERReplay 開始…")
    try:
        from soul.dream.replay import LiDERReplay
        replayer = LiDERReplay(graph_client)
        if dry_run:
            logger.info("[dream] --dry-run：LiDERReplay 跳過寫入")
            return
        report = replayer.run(batch_size=3)
        logger.info(
            f"[dream] Phase 3 完成：重播情節 {report.episodes_processed} 個 / "
            f"新增程序 {report.procedures_created} 條 / "
            f"精化程序 {report.procedures_refined} 條"
        )
    except Exception as e:
        logger.warning(f"[dream] LiDERReplay 失敗（跳過）：{e}")


def _update_soul_md_last_dream(soul_path: Path) -> None:
    """更新 SOUL.md frontmatter 的 last_dream 時間戳。"""
    try:
        from soul.identity.soul import SoulLoader
        loader = SoulLoader(soul_path)
        soul = loader.load()
        # 透過 save_neurochem 持久化（同時更新 last_dream）
        soul.neurochem  # 確保 neuro 已載入
        loader.save_neurochem(soul.neurochem)
        logger.info(f"[dream] SOUL.md last_dream 已更新")
    except Exception as e:
        logger.warning(f"[dream] SOUL.md 更新失敗（非致命）：{e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenSoul 夢境處理腳本")
    parser.add_argument("--pruning-only", action="store_true",
                        help="只執行 GraphPruning（無 LLM，快速）")
    parser.add_argument("--dry-run", action="store_true",
                        help="模擬執行，印出統計但不實際寫入")
    args = parser.parse_args()

    logger.info(f"[dream] 開始{'（--dry-run 模式）' if args.dry_run else ''}…")

    # ── 前置條件：SOUL.md ────────────────────────────────────────────────────
    try:
        from soul.core.config import settings
        soul_path = settings.soul_md_path
    except Exception:
        soul_path = _PROJECT_ROOT / "workspace" / "SOUL.md"

    _ensure_soul_md(soul_path)

    # ── 前置條件：FalkorDB ───────────────────────────────────────────────────
    graph_client = _get_graph_client()

    # ── 前置條件：LLM API（完整模式才需要）─────────────────────────────────
    if not args.pruning_only:
        _check_llm_api()

    # ── Phase 1：GraphPruning（無 LLM，必執行）──────────────────────────────
    run_pruning(graph_client, dry_run=args.dry_run)

    if args.pruning_only:
        logger.info("[dream] --pruning-only 模式完成。")
        return

    # ── Phase 2：KnowledgeDistillation（LLM，失敗繼續）─────────────────────
    run_distillation(graph_client, dry_run=args.dry_run)

    # ── Phase 3：LiDERReplay（LLM，失敗繼續）────────────────────────────────
    run_replay(graph_client, dry_run=args.dry_run)

    # ── 更新 SOUL.md ──────────────────────────────────────────────────────────
    if not args.dry_run:
        _update_soul_md_last_dream(soul_path)

    logger.info("[dream] 完成。")


if __name__ == "__main__":
    main()
