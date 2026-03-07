"""
soul/dream/replay.py

LiDER（Lucid Dreaming for Experience Replay）經驗重播模組。
對應大腦分區：預設模式網路（DMN）— 睡眠期間的記憶重播與技能優化

設計原理：
  1. 從 soul_episodic 抽取高多巴胺、尚未重播的情節
  2. 將 LLM 狀態「倒轉」至過去情境
  3. 用當前最新策略重新推演（「作夢」）
  4. 若夢境路徑更優 → 寫入 soul_procedural（技能庫更新）
  5. 標記 is_dreamed = true

參考論文：
  LiDER: Lucid Dreaming for Experience Replay (2020)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic
from openai import OpenAI

from soul.core.config import settings
from soul.memory.episodic import EpisodicMemory
from soul.memory.graph import GraphClient
from soul.memory.procedural import ProceduralMemory


@dataclass
class ReplayReport:
    """LiDER 重播週期的執行報告。"""
    episodes_processed: int = 0
    procedures_created: int = 0
    procedures_refined: int = 0
    skipped: int = 0
    details: list[str] = field(default_factory=list)


class LiDERReplay:
    """
    Lucid Dreaming for Experience Replay 實作。

    在 Dream Engine 呼叫時運行，不阻塞即時對話。

    Usage:
        replay = LiDERReplay(graph_client)
        report = replay.run()
    """

    # 評估「夢境路徑是否更優」的系統提示詞
    _EVALUATOR_SYSTEM = """你是一個 AI 推理路徑評估器。
你的任務是比較「歷史回覆」與「夢境重演回覆」，判斷哪個更好。
評估標準：準確性、簡潔性、邏輯完整性。
請以 JSON 格式回覆：
{
  "winner": "dream" | "history",
  "reason": "一句話說明",
  "extract_procedure": true | false,
  "procedure_name": "如果 dream 更優，建議的程序名稱",
  "procedure_steps": ["步驟1", "步驟2", ...]
}
"""

    def __init__(self, client: GraphClient) -> None:
        self._episodic = EpisodicMemory(client)
        self._procedural = ProceduralMemory(client)
        self._provider = settings.soul_llm_provider.lower()
        if self._provider == "openrouter":
            self._llm = OpenAI(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key or "no-key",
            )
            self._or_headers = {"HTTP-Referer": "https://opensoul.ai", "X-Title": "OpenSoul"}
        else:
            self._llm_anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            self._or_headers = {}
        self._model = settings.soul_llm_model

    def run(self, batch_size: int = 5) -> ReplayReport:
        """
        執行一個完整的 LiDER 重播週期。

        Args:
            batch_size: 每次夢境週期最多處理的情節數

        Returns:
            ReplayReport 包含執行統計
        """
        report = ReplayReport()

        # 1. 抽取高顯著性、尚未重播的情節
        episodes = self._episodic.get_high_salience_undreamed(
            da_threshold=settings.soul_dream_replay_da_threshold,
            limit=batch_size,
        )

        if not episodes:
            report.details.append("無待重播情節（全部已處理或低於 DA 閾值）")
            return report

        for ep in episodes:
            try:
                result = self._replay_episode(ep)
                report.episodes_processed += 1

                if result.get("winner") == "dream" and result.get("extract_procedure"):
                    # 夢境路徑更優 → 寫入程序性記憶
                    self._save_dream_procedure(ep, result, report)
                else:
                    report.skipped += 1
                    report.details.append(
                        f"情節 {ep['id'][:8]}：歷史路徑仍為最優"
                    )

                # 標記已重播
                self._episodic.mark_dreamed(ep["id"])

            except Exception as exc:
                report.skipped += 1
                report.details.append(f"情節 {ep['id'][:8]} 重播失敗：{exc}")

        return report

    # ── Private ───────────────────────────────────────────────────────────────

    def _replay_episode(self, episode: dict[str, Any]) -> dict[str, Any]:
        """
        對單一情節進行「清醒夢」推演：
        - 將原始使用者輸入交給 LLM 重新推演
        - 讓評估器比較夢境回覆 vs 歷史回覆
        """
        user_input = episode.get("user_input", "")
        historical_response = episode.get("agent_response", "")

        if not user_input or not historical_response:
            return {"winner": "history", "reason": "缺少原始對話資料"}

        # 夢境推演：用當前最新策略重新回答
        dream_prompt = (
            f"[夢境重演模式] 這是一個過去的使用者問題，請用你目前最好的策略回答：\n\n"
            f"問題：{user_input}\n\n"
            f"請直接給出最佳回覆，無需說明這是重演。"
        )

        if self._provider == "openrouter":
            resp = self._llm.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                temperature=settings.soul_llm_temperature,
                extra_headers=self._or_headers,
                messages=[
                    {"role": "system", "content": "你是一個認知 AI，正在進行離線夢境推演以優化過去的回覆策略。"},
                    {"role": "user", "content": dream_prompt},
                ],
            )
            dream_response = resp.choices[0].message.content or ""
        else:
            dream_msg = self._llm_anthropic.messages.create(
                model=self._model,
                max_tokens=1024,
                temperature=settings.soul_llm_temperature,
                system="你是一個認知 AI，正在進行離線夢境推演以優化過去的回覆策略。",
                messages=[{"role": "user", "content": dream_prompt}],
            )
            dream_response = dream_msg.content[0].text

        # 評估器比較
        eval_prompt = (
            f"【歷史回覆】\n{historical_response}\n\n"
            f"【夢境重演回覆】\n{dream_response}\n\n"
            f"【使用者原始問題】\n{user_input}"
        )

        if self._provider == "openrouter":
            eval_resp = self._llm.chat.completions.create(
                model=self._model,
                max_tokens=512,
                temperature=settings.soul_llm_temperature,
                extra_headers=self._or_headers,
                messages=[
                    {"role": "system", "content": self._EVALUATOR_SYSTEM},
                    {"role": "user", "content": eval_prompt},
                ],
            )
            raw = eval_resp.choices[0].message.content or ""
        else:
            eval_msg = self._llm_anthropic.messages.create(
                model=self._model,
                max_tokens=512,
                temperature=settings.soul_llm_temperature,
                system=self._EVALUATOR_SYSTEM,
                messages=[{"role": "user", "content": eval_prompt}],
            )
            raw = eval_msg.content[0].text

        try:
            # 解析 JSON 回覆
            raw = eval_msg.content[0].text
            # 提取 JSON 區塊
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception:
            pass

        return {"winner": "history", "reason": "評估解析失敗"}

    def _save_dream_procedure(
        self,
        episode: dict[str, Any],
        eval_result: dict[str, Any],
        report: ReplayReport,
    ) -> None:
        """將夢境發現的更優路徑寫入程序性記憶。"""
        procedure_name = eval_result.get("procedure_name", "夢境優化程序")
        steps = eval_result.get("procedure_steps", [])
        reason = eval_result.get("reason", "")

        if not steps:
            return

        # 嘗試找同域的現有程序進行 refine，否則建立新程序
        existing = self._procedural.get_best_procedures(
            domain=episode.get("session_id", "general"), limit=1
        )

        if existing:
            try:
                self._procedural.refine_procedure(
                    original_id=existing[0]["id"],
                    new_steps=steps,
                    new_description=f"夢境優化：{reason}",
                )
                report.procedures_refined += 1
                report.details.append(f"精化程序：{procedure_name}")
                return
            except Exception:
                pass

        # 建立全新程序
        self._procedural.write_procedure(
            name=procedure_name,
            description=f"由 LiDER 夢境重播發現。原因：{reason}",
            steps=steps,
            domain="dream_discovery",
            source_episode_id=episode.get("id"),
        )
        report.procedures_created += 1
        report.details.append(f"新增程序：{procedure_name}")
