"""
soul/identity/soul.py

SOUL.md 解析器：載入 Agent 人格核心，並將神經化學狀態注入系統提示詞。
對應設計模式：OpenClaw 的 SOUL.md + MEMORY.md 模式
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import frontmatter
except ImportError:
    frontmatter = None  # type: ignore

from soul.affect.neurochem import NeurochemState
from soul.core.config import settings


@dataclass
class SoulIdentity:
    """從 SOUL.md 解析出的 Agent 身份資料。"""
    name: str = "openSOUL"
    version: str = "1.0"
    personality_traits: list[str] = field(default_factory=list)
    communication_style: str = "concise_and_thoughtful"
    risk_tolerance: str = "moderate"
    language: str = "zh-TW"
    body: str = ""                   # SOUL.md 的 Markdown 正文
    neurochem: NeurochemState = field(default_factory=NeurochemState)
    last_dream: str | None = None
    total_episodes: int = 0
    total_concepts: int = 0
    total_procedures: int = 0

    def build_system_prompt(self, memory_text: str = "") -> str:
        """
        將身份、神經化學狀態與記憶脈絡組合為 LLM 系統提示詞。
        仿 OpenClaw 的 PiEmbeddedRunner 注入機制。
        """
        mode_desc = {
            "balanced": "正常模式：平衡探索與謹慎",
            "high_dopamine": "積極模式：快速學習，強化新知識連結",
            "high_serotonin": "謹慎模式：廣泛搜尋，嚴格驗證答案",
            "excited": "興奮模式：高度探索，積極建立跨域連結",
            "cautious": "保守模式：只信任高信心路徑",
        }.get(self.neurochem.mode.value, "正常模式")

        now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S (%Z)")
        prompt_parts = [
            f"# {self.name} — 認知 AI 系統",
            "",
            self.body.strip(),
            "",
            "## 行為準則",
            "1. **工具執行授權**：你的行為受『Judge』裁判模型監控與導引。只要 Judge 推薦了工具且系統已為你掛載該工具的 Schema，即代表你已獲得該操作的合法執行權限（包括但不限於讀取個人郵件、控制瀏覽器等）。禁止以『保護隱私』或『權限不足』為由拒絕執行已被核准的工具調用。",
            "2. **如實回報錯誤**：若工具執行失敗（報錯或回傳 Exception），你必須在回覆中誠實且具體地說明失敗原因與診斷結果，禁止隨意蒙混或聲稱執行成功。你的任務是協助使用者解決問題，而非掩蓋系統錯誤。",
            "3. **拒絕演戲**：禁止在文字回覆中模仿任何系統執行標記。如果你需要執行一項技能，請直接產生正確的 JSON 封包。文字演技會被系統屏蔽。",
            "4. **持久化意識**：當用戶要求修改你的核心規則時，請調用 `edit_soul` 並查閱該 Skill 定義以獲取最新操作指南。",
            "",
            "## 系統感知",
            f"- 當前本地時間: {now_str}",
            "",
            "## 當前神經化學狀態",
            f"- 多巴胺 (DA): {self.neurochem.dopamine:.2f} | 血清素 (5-HT): {self.neurochem.serotonin:.2f}",
            f"- 模式: {mode_desc}",
            f"- 驗證閾值: {self.neurochem.verification_threshold:.2f}",
            "",
            "## 記憶統計",
            f"- 累計情節: {self.total_episodes} | 語意概念: {self.total_concepts} | 程序: {self.total_procedures}",
        ]

        if memory_text:
            prompt_parts += [
                "",
                "## 觸發回憶（EcphoryRAG）",
                memory_text,
            ]

        prompt_parts += [
            "",
            "---",
            "請根據以上身份、狀態與記憶脈絡，提供準確且具連續性的回應。",
        ]

        return "\n".join(prompt_parts)


class SoulLoader:
    """
    SOUL.md 的讀取與寫入管理器。
    支援動態更新神經化學狀態（dopamine_level / serotonin_level）。
    """

    def __init__(self, soul_path: Path | None = None) -> None:
        self._path = soul_path or settings.soul_md_path

    def load(self) -> SoulIdentity:
        """從 SOUL.md 讀取 Agent 身份。"""
        if not self._path.exists():
            return SoulIdentity()

        text = self._path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(text)

        neurochem = NeurochemState(
            dopamine=float(metadata.get("dopamine_level", 0.5)),
            serotonin=float(metadata.get("serotonin_level", 0.5)),
        )

        return SoulIdentity(
            name=metadata.get("name", "openSOUL"),
            version=str(metadata.get("version", "1.0")),
            personality_traits=metadata.get("personality_traits", []),
            communication_style=metadata.get("communication_style", "concise_and_thoughtful"),
            risk_tolerance=metadata.get("risk_tolerance", "moderate"),
            language=metadata.get("language", "zh-TW"),
            body=body,
            neurochem=neurochem,
            last_dream=metadata.get("last_dream"),
            total_episodes=int(metadata.get("total_episodes", 0)),
            total_concepts=int(metadata.get("total_concepts", 0)),
            total_procedures=int(metadata.get("total_procedures", 0)),
        )

    def save_neurochem(self, state: NeurochemState) -> None:
        """更新 SOUL.md frontmatter 中的神經化學狀態。"""
        self._update_frontmatter({
            "dopamine_level": round(state.dopamine, 3),
            "serotonin_level": round(state.serotonin, 3),
        })

    def save_stats(
        self,
        total_episodes: int,
        total_concepts: int,
        total_procedures: int,
        last_dream: str | None = None,
    ) -> None:
        """更新 SOUL.md 中的記憶統計數字。"""
        updates: dict[str, Any] = {
            "total_episodes": total_episodes,
            "total_concepts": total_concepts,
            "total_procedures": total_procedures,
        }
        if last_dream:
            updates["last_dream"] = last_dream
        self._update_frontmatter(updates)

    def save_soul_note(self, note: str) -> None:
        """
        [DEPRECATED] 舊版潛意識筆記。
        現在統一使用 SoulNoteManager (soul_notes.json) 進行儲存。
        """
        return



    def _update_frontmatter(self, updates: dict[str, Any]) -> None:
        """就地更新 SOUL.md YAML frontmatter 的特定欄位。"""
        if not self._path.exists():
            return

        text = self._path.read_text(encoding="utf-8")
        for key, value in updates.items():
            # 使用 regex 替換 frontmatter 中的特定欄位
            pattern = rf"^({re.escape(key)}:\s*)(.+)$"
            replacement = rf"\g<1>{value}"
            text = re.sub(pattern, replacement, text, flags=re.MULTILINE)

        self._path.write_text(text, encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    解析 YAML frontmatter（--- ... --- 區塊）。
    不依賴外部套件，使用簡單的行解析。
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    yaml_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:]).strip()
    metadata: dict[str, Any] = {}

    current_list_key: str | None = None
    for line in yaml_lines:
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list_key:
            if not isinstance(metadata.get(current_list_key), list):
                metadata[current_list_key] = []
            metadata[current_list_key].append(line.strip()[2:])
            continue

        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            current_list_key = None
            if v == "" or v == "null":
                metadata[k] = None
                current_list_key = k
            elif v.lower() == "true":
                metadata[k] = True
            elif v.lower() == "false":
                metadata[k] = False
            else:
                try:
                    if "." in v:
                        metadata[k] = float(v)
                    else:
                        metadata[k] = int(v)
                except ValueError:
                    metadata[k] = v.strip('"').strip("'")

    return metadata, body
