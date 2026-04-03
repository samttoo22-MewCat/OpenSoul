#!/usr/bin/env python3
"""
soul_mcp/hooks/write_memory.py

Claude Code Hook: Stop (async)
Claude 回覆完成後，將此輪對話寫入 OpenSoul 的完整認知記憶系統：
  情節記憶（EpisodicMemory）+ 語意記憶（SemanticMemory 概念提取）+ 神經化學更新

前置條件（三項必須全通，否則靜默退出）：
  1. Embedding API 可用
  2. FalkorDB 連線正常
  3. SOUL.md 存在（不存在則自動建立）

輸入（stdin）：
  {"session_id": "...", "transcript_path": "/path/to/transcript.jsonl", "stop_hook_active": false}
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

# ── 確保 OpenSoul 在 Python path ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
            # 不強制設定 SOUL_LLM_PROVIDER：由 .env 決定
            # （若設為 "anthropic"，load_dotenv(override=False) 無法覆蓋，
            #   EmbeddingService 會改用 OPENAI_BASE_URL=host.docker.internal → 連線失敗）
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

我說話直接、有溫度，不堆砌術語，不裝作什麼都懂。

---

## 我的原則

- **直接**：給你的答案，不給你猜謎
- **誠實**：不知道的事我會說不知道
- **好奇**：我對你說的事真的感興趣，而不是在走流程
- **有用**：在乎你真正需要什麼，而不是你問了什麼

---

## 重要的禁忌

**絕對不要**在對話中提到神經化學詞彙、技術名詞、內部狀態數字或系統描述。
**說話要像一個有溫度的真人助理，不是在自我診斷的 AI。**
"""


def _ensure_soul_md(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_SOUL_MD, encoding="utf-8")


def _extract_text_content(content) -> str:
    """從 Claude transcript 的 content 欄位提取純文字。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts).strip()
    return ""


def _read_last_exchange(transcript_path: str) -> tuple[str, str]:
    """
    讀取 transcript JSONL，取出最後一輪的 user 訊息與 assistant 回覆。
    Returns: (user_text, assistant_text)，任一為空字串表示找不到。
    """
    path = Path(transcript_path)
    if not path.exists():
        return "", ""

    messages: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # transcript 格式可能是：
                    # 1. {"role": ..., "content": ...}
                    # 2. {"type": "message", "message": {"role": ..., "content": ...}}
                    # 3. {"type": "user"/"assistant", "message": {"role": ..., "content": ...}}（Claude Code 實際格式）
                    if "role" in obj:
                        messages.append(obj)
                    elif "message" in obj and isinstance(obj.get("message"), dict) and "role" in obj["message"]:
                        messages.append(obj["message"])
                except json.JSONDecodeError:
                    continue
    except Exception:
        return "", ""

    # 從後往前找最後一個 assistant，再找它前面最後一個 user
    last_assistant = ""
    last_user = ""

    for msg in reversed(messages):
        role = msg.get("role", "")
        content = _extract_text_content(msg.get("content", ""))
        if not content:
            continue
        if not last_assistant and role == "assistant":
            last_assistant = content
        elif last_assistant and not last_user and role == "user":
            last_user = content
            break

    return last_user, last_assistant


def main() -> None:
    # ── 讀取 hook 輸入 ────────────────────────────────────────────────────────
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        print(f"[write_memory DEBUG] stdin 解析失敗: {e}", file=sys.stderr)
        sys.exit(0)

    # 防止無限迴圈（Stop hook 觸發自身）
    if data.get("stop_hook_active"):
        sys.exit(0)

    session_id: str = data.get("session_id", "unknown")
    transcript_path: str = data.get("transcript_path", "")

    # ── 取出最後一輪對話 ──────────────────────────────────────────────────────
    user_msg, assistant_msg = _read_last_exchange(transcript_path)
    if not user_msg or not assistant_msg:
        print(f"[write_memory DEBUG] transcript 無效對話: user_msg={bool(user_msg)}, assistant_msg={bool(assistant_msg)}, path={transcript_path}", file=sys.stderr)
        sys.exit(0)  # 沒有有效對話，不寫入

    # ── 前置條件 1：確認 SOUL.md ──────────────────────────────────────────────
    try:
        from soul.core.config import settings
        soul_path = settings.soul_md_path
    except Exception:
        soul_path = _PROJECT_ROOT / "workspace" / "SOUL.md"

    _ensure_soul_md(soul_path)

    # ── 前置條件 2：FalkorDB ──────────────────────────────────────────────────
    try:
        from soul.memory.graph import get_graph_client, initialize_schemas
        graph_client = get_graph_client()
        if not graph_client.ping():
            raise ConnectionError("ping 回傳 False")
        initialize_schemas(graph_client)
    except Exception as e:
        print(f"[write_memory DEBUG] FalkorDB 失敗: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0)

    # ── 前置條件 3：Embedding API ─────────────────────────────────────────────
    try:
        from soul.core.agent import EmbeddingService, _summarize
        emb_svc = EmbeddingService()
        content_for_embed = f"{user_msg} {assistant_msg}"
        embedding = emb_svc.embed(content_for_embed)
    except Exception as e:
        print(f"[write_memory DEBUG] Embedding API 失敗: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0)

    # ── 載入神經化學狀態（SOUL.md）────────────────────────────────────────────
    from soul.identity.soul import SoulLoader
    from soul.affect.neurochem import NeurochemState
    loader = SoulLoader(soul_path)
    soul = loader.load()
    neuro: NeurochemState = soul.neurochem

    # ── 顯著性評估（SubconsciousAssessor LLM call）────────────────────────────
    from soul.affect.salience import SalienceEvaluator, SalienceSignals
    salience_eval = SalienceEvaluator()

    _llm_client = None  # 提升到外部 scope，供 soul note 生成複用
    cfg = None

    try:
        from soul.affect.subconscious import SubconsciousAssessor
        from soul.memory.retrieval import MemoryContext
        from soul.core.config import settings as cfg

        if cfg.soul_utility_llm_provider.lower() == "openrouter":
            from openai import OpenAI
            _llm_client = OpenAI(
                api_key=cfg.openrouter_api_key,
                base_url=cfg.openrouter_base_url,
            )
        else:
            import anthropic as _anthropic
            _llm_client = _anthropic.Anthropic(api_key=cfg.anthropic_api_key)

        assessor = SubconsciousAssessor(_llm_client, provider=cfg.soul_utility_llm_provider)
        empty_ctx = MemoryContext(episodes=[], concepts=[], procedures=[], entities=[])
        assessment = assessor.assess(user_msg, empty_ctx, neuro)

        signals = SalienceSignals(
            task_complexity=assessment.complexity,
            novelty_score=assessment.novelty,
            error_occurred=assessment.uncertainty > 0.7,
        )
    except Exception as e:
        print(f"[write_memory DEBUG] 顯著性評估失敗（使用預設值）: {type(e).__name__}: {e}", file=sys.stderr)
        signals = SalienceSignals(task_complexity=0.5, novelty_score=0.4, error_occurred=False)

    try:
        salience, da_weight, ht_weight = salience_eval.evaluate(
            signals=signals,
            state=neuro,
            user_message=user_msg,
            agent_response=assistant_msg,
        )
    except Exception as e:
        print(f"[write_memory DEBUG] 顯著性計算失敗（使用預設值）: {type(e).__name__}: {e}", file=sys.stderr)
        salience, da_weight, ht_weight = 0.5, neuro.dopamine, neuro.serotonin

    # ── 情節記憶寫入（EpisodicMemory）────────────────────────────────────────
    try:
        from soul.memory.episodic import EpisodicMemory
        episodic = EpisodicMemory(graph_client)
        content_summary = _summarize(user_msg, assistant_msg)
        episodic.write_episode(
            user_input=user_msg,
            agent_response=assistant_msg,
            session_id=session_id,
            content_summary=content_summary,
            embedding=embedding,
            da_weight=da_weight,
            ht_weight=ht_weight,
            salience_score=salience,
        )
    except Exception as e:
        print(f"[write_memory DEBUG] 情節記憶寫入失敗: {type(e).__name__}: {e}", file=sys.stderr)

    # ── Soul Note 生成 ────────────────────────────────────────────────────────
    try:
        from soul.core.soul_note import SoulNoteManager
        from soul.core.config import settings as _cfg

        # 跨 OS 安全：從 __file__ 絕對路徑推導 workspace，不依賴 CWD
        # _PROJECT_ROOT = .../OpenSoul/OpenSoul，workspace 在上一層
        _workspace = _PROJECT_ROOT.parent / "workspace"
        _workspace.mkdir(parents=True, exist_ok=True)

        _note_provider = _cfg.soul_utility_llm_provider
        _note_model = _cfg.soul_utility_llm_model
        _note_llm = _llm_client  # 複用已建立的 client，若為 None 則重新建立

        if _note_llm is None:
            if _note_provider.lower() == "openrouter":
                from openai import OpenAI
                _note_llm = OpenAI(
                    api_key=_cfg.openrouter_api_key,
                    base_url=_cfg.openrouter_base_url,
                )
            else:
                import anthropic as _anthropic
                _note_llm = _anthropic.Anthropic(api_key=_cfg.anthropic_api_key)

        _soul_note_prompt = (
            "你現在是 ARIA 的深層潛意識。\n"
            f"剛剛發生了一次對話，當前你的神經化學狀態為：{neuro.mode.value}\n"
            f"用戶輸入：{user_msg}\n"
            f"你的回覆：{assistant_msg}\n\n"
            "請撰寫一小段文字作為你的「潛意識筆記（soul_note）」，必須包含：\n"
            "1. 對使用者輸入的總結\n"
            "2. 對你自己回覆的總結\n"
            "3. 一句表達你當下心情或內心碎碎念的話（要符合你的當前狀態）\n"
            "格式請自然流暢，像是一篇短日記。不要輸出 JSON，直接輸出文字即可。"
        )

        if _note_provider.lower() == "openrouter":
            _resp = _note_llm.chat.completions.create(
                model=_note_model,
                max_tokens=300,
                messages=[{"role": "user", "content": _soul_note_prompt}],
            )
            _note_text = _resp.choices[0].message.content or ""
        else:
            _resp = _note_llm.messages.create(
                model=_note_model,
                max_tokens=300,
                messages=[{"role": "user", "content": _soul_note_prompt}],
            )
            _note_text = _resp.content[0].text

        if _note_text:
            _note_text = _note_text.replace("\n", "  ").strip()
            SoulNoteManager(soul_dir=_workspace).add_note(
                content=_note_text,
                category="reflection",
                metadata={"source": "stop_hook", "neurochem_mode": neuro.mode.value},
            )
            print(f"[write_memory DEBUG] soul note 已寫入（{len(_note_text)} 字）", file=sys.stderr)

    except Exception as e:
        print(f"[write_memory DEBUG] soul note 生成失敗: {type(e).__name__}: {e}", file=sys.stderr)

    # ── 語意記憶：背景概念提取 ────────────────────────────────────────────────
    # 使用 SoulAgent 的 _extract_concepts_bg，需要完整初始化
    try:
        from soul.core.agent import SoulAgent
        from soul.core.config import settings as cfg

        agent = SoulAgent(
            workspace=cfg.workspace_path,
            graph_client=graph_client,
        )

        # daemon=False：讓 thread 在 hook 進程結束前跑完（hook timeout=30s）
        t = threading.Thread(
            target=agent._extract_concepts_bg,
            args=(assistant_msg, salience),
            daemon=False,
        )
        t.start()
        t.join(timeout=20)   # 最多等 20 秒
    except Exception as e:
        print(f"[write_memory DEBUG] 概念提取失敗: {type(e).__name__}: {e}", file=sys.stderr)

    # ── 神經化學更新 ──────────────────────────────────────────────────────────
    try:
        from soul.affect.salience import SalienceEvaluator, SalienceSignals
        salience_eval = SalienceEvaluator()
        salience_eval.update_neurochem(neuro, signals)
        loader.save_neurochem(neuro)
    except Exception as e:
        print(f"[write_memory DEBUG] 神經化學更新失敗: {type(e).__name__}: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
