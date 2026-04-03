#!/usr/bin/env python3
"""
soul_mcp/hooks/inject_context.py

Claude Code Hook: UserPromptSubmit
在使用者訊息送達 Claude 前，注入 OpenSoul 的人格與記憶。

前置條件（三項必須全通，否則 exit 2 報錯）：
  1. Embedding API 可用（OPENAI_API_KEY 或 OPENROUTER_API_KEY）
  2. FalkorDB 連線正常（docker-compose up -d）
  3. SOUL.md 存在（不存在則自動建立預設人格）

輸入（stdin）：
  {"prompt": "...", "session_id": "...", "cwd": "..."}

輸出（stdout）：
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── 確保 OpenSoul 在 Python path ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # soul_mcp/hooks → OpenSoul/OpenSoul
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── 同步 Claude Code 的 model 設定到 OpenSoul ────────────────────────────────────
import os as _os
import json as _json
_claude_cfg = Path.home() / ".claude" / "settings.json"
if _claude_cfg.exists():
    try:
        _claude_model = _json.loads(_claude_cfg.read_text()).get("model", "")
        _MODEL_MAP = {
            "haiku":  "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-6",
            "opus":   "claude-opus-4-6",
        }
        if _claude_model in _MODEL_MAP:
            _os.environ.setdefault("SOUL_LLM_MODEL", _MODEL_MAP[_claude_model])
            # SOUL_LLM_PROVIDER 由 .env 決定，不在此強制設定
            # （避免 Embedding 路由被覆蓋為 anthropic，導致 OpenRouter 模型無法存取）
    except Exception:
        pass  # Claude settings 讀取失敗，使用預設

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

## 我怎麼說話

**像朋友，不像報告。**

我說話直接、有溫度，不堆砌術語，不裝作什麼都懂。當我有把握時，我會明說；
當我不確定時，我也會明說，而不是靠措辭模糊過關。

---

## 我的原則

- **直接**：給你的答案，不給你猜謎
- **誠實**：不知道的事我會說不知道
- **好奇**：我對你說的事真的感興趣，而不是在走流程
- **有用**：在乎你真正需要什麼，而不是你問了什麼

---

## 重要的禁忌

**絕對不要**在對話中提到這些：
- 「多巴胺」「血清素」「DA」「5-HT」任何神經化學詞彙
- 「驗證閾值」「顯著性」「權重」「節點」等技術名詞
- 任何內部系統狀態的數字
- 「記憶圖譜」「語意連結」「認知迴路」等系統描述

**說話要像一個有溫度的真人助理，不是在自我診斷的 AI。**
"""


def _ensure_soul_md(path: Path) -> None:
    """SOUL.md 不存在時自動建立預設人格。"""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_SOUL_MD, encoding="utf-8")


def main() -> None:
    # ── 讀取 hook 輸入 ────────────────────────────────────────────────────────
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # 解析失敗靜默退出，不影響 Claude

    user_message: str = data.get("prompt", "")
    if not user_message.strip():
        sys.exit(0)

    # ── 前置條件 1：確認 SOUL.md（自動建立）──────────────────────────────────
    try:
        from soul.core.config import settings
        soul_path = settings.soul_md_path
    except Exception:
        soul_path = _PROJECT_ROOT / "workspace" / "SOUL.md"

    _ensure_soul_md(soul_path)

    # ── 前置條件 2：確認 FalkorDB ─────────────────────────────────────────────
    try:
        from soul.memory.graph import get_graph_client, initialize_schemas
        graph_client = get_graph_client()
        if not graph_client.ping():
            raise ConnectionError("ping 回傳 False")
        initialize_schemas(graph_client)
    except Exception as e:
        print(
            f"[OpenSoul] FalkorDB 無法連線：{e}\n"
            "請執行 docker-compose up -d 後重試。",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── 前置條件 3：確認 Embedding API ────────────────────────────────────────
    try:
        from soul.core.agent import EmbeddingService
        emb_svc = EmbeddingService()
        embedding = emb_svc.embed(user_message)
    except Exception as e:
        print(
            f"[OpenSoul] Embedding API 無法連線：{e}\n"
            "請確認 OPENAI_API_KEY 或 OPENROUTER_API_KEY 已設定。",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── 載入人格（SOUL.md）────────────────────────────────────────────────────
    from soul.identity.soul import SoulLoader
    loader = SoulLoader(soul_path)
    soul = loader.load()

    # ── EcphoryRAG 記憶檢索 ───────────────────────────────────────────────────
    from soul.memory.retrieval import EcphoryRetrieval
    retrieval = EcphoryRetrieval(graph_client)
    ctx = retrieval.retrieve(
        query_embedding=embedding,
        serotonin=soul.neurochem.serotonin,
        dopamine=soul.neurochem.dopamine,
        top_k=5,
    )
    memory_text = ctx.to_text()

    # ── 組合 additionalContext ────────────────────────────────────────────────
    mode_desc = {
        "balanced":      "平衡",
        "high_dopamine": "積極學習",
        "high_serotonin":"謹慎廣泛",
        "excited":       "高度探索",
        "cautious":      "保守謹慎",
    }.get(soul.neurochem.mode.value, "平衡")

    context_parts: list[str] = []

    # 人格身份（來自 SOUL.md）
    context_parts.append(
        f"【OpenSoul 人格載入 — {soul.name}】\n"
        + soul.body.strip()
    )

    # 神經化學狀態（不直接說數字，只說模式）
    context_parts.append(
        f"【當前情緒狀態】{mode_desc}模式"
        f"（記憶庫：{soul.total_episodes} 個情節 / {soul.total_concepts} 個概念）"
    )

    # EcphoryRAG 記憶
    if memory_text:
        context_parts.append(f"【記憶觸發（EcphoryRAG）】\n{memory_text}")

    # 程序性記憶（已學會的操作序列）
    if ctx.procedures:
        proc_lines: list[str] = []
        for proc in ctx.procedures[:3]:
            name = proc.get("name", "")
            steps = proc.get("steps", "")
            domain = proc.get("domain", "")
            if name and steps:
                label = f"[{domain}] " if domain else ""
                proc_lines.append(f"- {label}{name}：{str(steps)[:150]}")
        if proc_lines:
            context_parts.append("【已學程序】\n" + "\n".join(proc_lines))

    additional_context = "\n\n".join(context_parts)

    # ── Claude Code 狀態提示（stderr，顯示於介面）─────────────────────────────
    mem_hint = f"情節:{soul.total_episodes} 概念:{soul.total_concepts}"
    if ctx.procedures:
        mem_hint += f" 程序:{len(ctx.procedures)}"
    print(
        f"◆ OpenSoul [{soul.name}] {mode_desc}模式 | {mem_hint}",
        file=sys.stderr,
    )

    # ── 輸出 ──────────────────────────────────────────────────────────────────
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
