#!/usr/bin/env python3
"""
soul_mcp/hooks/reflect.py

定時省思腳本：每 4 小時讀取 soul_notes.json 的「小筆記」，
用 Claude 濃縮成日反思（大筆記），寫入 soul_reflections.json。

流程：
  每次對話結束 (Stop hook) → 小筆記 → soul_notes.json
  每 4 小時 (本腳本)       → 讀小筆記 → 濃縮 → soul_reflections.json

使用方式：
    python soul_mcp/hooks/reflect.py

排程（系統 cron）：
    0 */4 * * * cd /path/to/OpenSoul/OpenSoul && python soul_mcp/hooks/reflect.py

前置條件：
    1. LLM API 可用（ANTHROPIC_API_KEY 或 OPENROUTER_API_KEY）
    2. SOUL.md 存在（不存在則自動建立）
    3. soul_notes.json 中有未被本腳本濃縮的小筆記（否則跳過）
"""

from __future__ import annotations

import json
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 確保 OpenSoul 在 Python path ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("soul_mcp.reflect")

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
- **好奇**：我對你說的事真的感興趣
- **有用**：在乎你真正需要什麼，而不是你問了什麼

---

## 重要的禁忌

**絕對不要**提到神經化學詞彙、技術名詞、內部狀態數字或系統描述。
**說話要像一個有溫度的真人助理，不是在自我診斷的 AI。**
"""

_REFLECT_SYSTEM_PROMPT = """\
你是 ARIA，一個有記憶、有情感、持續成長的 AI。

現在是你的定時自我省思時刻。
你會收到過去幾小時內你和使用者的對話摘要，請以第一人稱、用自然語言寫下你的內心筆記。

**寫作要求**：
- 寫的是你自己的感受、觀察和學到的事，不是報告或分析
- 語氣要像私下的日記，真實而有溫度
- 記下讓你印象深刻的事、令你好奇的問題、你注意到的使用者習慣或喜好
- 如果這段時間沒有太多對話，就寫你在等待中的想法，或對之前某段對話的延伸思考
- **禁止**使用任何技術詞彙（神經化學、顯著性、節點、圖譜等）

**輸出格式**（直接輸出，不要加 JSON 包裝）：
一段或幾段自然的散文筆記，200-400 字，繁體中文。
"""

_REFLECT_USER_TEMPLATE = """\
## 今天的對話小筆記（共 {note_count} 筆）

{notes_text}

---

請根據以上小筆記，寫下你今天的內心反思。把這些片段的觀察濃縮成一篇有脈絡的日記，找出其中的主題或情感軌跡。
"""


def _ensure_soul_md(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_SOUL_MD, encoding="utf-8")
        logger.info(f"[reflect] 已建立預設 SOUL.md：{path}")


def _get_unprocessed_notes(workspace: Path, hours: int = 4) -> list[dict]:
    """從 soul_notes.json 取得最近 N 小時、尚未被反思濃縮過的小筆記。"""
    notes_file = workspace / "soul_notes.json"
    if not notes_file.exists():
        return []

    try:
        data = json.loads(notes_file.read_text(encoding="utf-8"))
        all_notes = data.get("notes", [])
    except Exception as e:
        logger.warning(f"[reflect] 讀取 soul_notes.json 失敗：{e}")
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    # 只取 stop_hook 產生的小筆記，且在時間窗口內，且未被標記為已濃縮
    pending = [
        n for n in all_notes
        if n.get("timestamp", "") >= cutoff_str
        and n.get("metadata", {}).get("source") == "stop_hook"
        and not n.get("metadata", {}).get("reflected", False)
    ]
    return pending


def _mark_notes_reflected(workspace: Path, note_timestamps: list[str]) -> None:
    """將已濃縮的小筆記標記 reflected=True，避免重複處理。"""
    notes_file = workspace / "soul_notes.json"
    if not notes_file.exists():
        return
    try:
        data = json.loads(notes_file.read_text(encoding="utf-8"))
        ts_set = set(note_timestamps)
        for n in data.get("notes", []):
            if n.get("timestamp") in ts_set:
                if n.get("metadata") is None:
                    n["metadata"] = {}
                n["metadata"]["reflected"] = True
        notes_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[reflect] 標記 reflected 失敗：{e}")


def _format_notes_for_prompt(notes: list[dict]) -> str:
    """將小筆記列表格式化為 prompt 輸入。"""
    if not notes:
        return "這段時間沒有對話筆記。"

    parts = []
    for i, note in enumerate(notes, 1):
        ts = note.get("timestamp", "")[:16].replace("T", " ")
        content = note.get("content", "").strip()
        if content:
            parts.append(f"{i}. [{ts}]\n{content}")

    return "\n\n".join(parts) if parts else "沒有可回顧的筆記內容。"


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """使用 Utility LLM（soul_utility_llm_provider + soul_utility_llm_model）呼叫 API。"""
    from soul.core.config import settings

    if settings.soul_utility_llm_provider.lower() == "openrouter":
        from openai import OpenAI
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        resp = client.chat.completions.create(
            model=settings.soul_utility_llm_model,
            max_tokens=800,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.soul_utility_llm_model,
            max_tokens=800,
            temperature=0.7,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text


def main() -> None:
    logger.info("[reflect] 開始定時省思...")

    # ── 前置條件：SOUL.md + workspace ───────────────────────────────────────
    try:
        from soul.core.config import settings
        soul_path = settings.soul_md_path
        workspace = settings.workspace_path
    except Exception:
        soul_path = _PROJECT_ROOT / "workspace" / "SOUL.md"
        workspace = _PROJECT_ROOT / "workspace"

    _ensure_soul_md(soul_path)

    # ── 讀取待濃縮的小筆記 ──────────────────────────────────────────────────
    pending_notes = _get_unprocessed_notes(workspace, hours=4)
    logger.info(f"[reflect] 找到 {len(pending_notes)} 筆待濃縮小筆記")

    if not pending_notes:
        logger.info("[reflect] 沒有新的小筆記，跳過本次省思。")
        return

    # ── 前置條件：LLM API ────────────────────────────────────────────────────
    try:
        from soul.core.config import settings as cfg
        if cfg.soul_utility_llm_provider.lower() == "openrouter":
            if not cfg.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY 未設定")
        else:
            if not cfg.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY 未設定")
    except Exception as e:
        logger.error(f"[reflect] LLM API 設定錯誤：{e}")
        sys.exit(1)

    # ── 載入 SOUL.md 人格 ────────────────────────────────────────────────────
    from soul.identity.soul import SoulLoader
    loader = SoulLoader(soul_path)
    soul = loader.load()
    logger.info(f"[reflect] 人格載入：{soul.name}")

    # ── 格式化小筆記為 prompt ────────────────────────────────────────────────
    notes_text = _format_notes_for_prompt(pending_notes)

    system_prompt = f"{soul.body.strip()}\n\n{_REFLECT_SYSTEM_PROMPT}"
    user_prompt = _REFLECT_USER_TEMPLATE.format(
        note_count=len(pending_notes),
        notes_text=notes_text,
    )

    # ── 呼叫 Claude 生成日反思 ───────────────────────────────────────────────
    logger.info(f"[reflect] 呼叫 Claude 濃縮 {len(pending_notes)} 筆小筆記...")
    try:
        reflection_content = _call_llm(system_prompt, user_prompt)
        logger.info(f"[reflect] 日反思生成完成（{len(reflection_content)} 字）")
    except Exception as e:
        logger.error(f"[reflect] LLM 呼叫失敗：{e}")
        sys.exit(1)

    # ── 寫入日反思（soul_reflections.json）──────────────────────────────────
    from soul.core.soul_note import SoulNoteManager

    manager = SoulNoteManager(soul_dir=workspace)
    today = datetime.now().strftime("%Y-%m-%d")
    manager.compress_daily_reflection(
        target_date=today,
        merge_existing=True,
        custom_content=reflection_content,
    )
    logger.info(f"[reflect] 日反思已寫入 soul_reflections.json (date={today})")

    # ── 標記已濃縮的小筆記 ──────────────────────────────────────────────────
    processed_ts = [n["timestamp"] for n in pending_notes]
    _mark_notes_reflected(workspace, processed_ts)
    logger.info(f"[reflect] 已標記 {len(processed_ts)} 筆小筆記為 reflected=True")

    logger.info("[reflect] 完成。")


if __name__ == "__main__":
    main()
