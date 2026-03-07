"""
soul/dream/engine.py

Dream Engine：離線記憶鞏固主協調器。
對應大腦分區：預設模式網路（Default Mode Network, DMN）

職責：
  1. 管理 APScheduler 排程（閒置觸發 + 定時 Cron）
  2. 協調三個子模組的執行順序：
       LiDERReplay → KnowledgeDistillation → GraphPruning
  3. 更新 SOUL.md 的神經化學狀態與統計
  4. 生成夢境報告

觸發條件（雙觸發機制）：
  - 閒置觸發：距離上次對話超過 SOUL_DREAM_IDLE_MINUTES（預設 5 分鐘）
  - Cron 觸發：每日凌晨 3 點（SOUL_DREAM_CRON）
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from soul.core.config import settings
from soul.dream.distillation import DistillationReport, KnowledgeDistillation
from soul.dream.pruning import GraphPruning, PruningReport
from soul.dream.replay import LiDERReplay, ReplayReport
from soul.identity.soul import SoulLoader
from soul.memory.graph import GraphClient, get_graph_client


@dataclass
class DreamReport:
    """單次完整夢境週期的綜合報告。"""
    started_at: str = ""
    finished_at: str = ""
    triggered_by: str = "manual"          # "idle" | "cron" | "manual"
    replay: ReplayReport = field(default_factory=ReplayReport)
    distillation: DistillationReport = field(default_factory=DistillationReport)
    pruning: PruningReport = field(default_factory=PruningReport)
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        try:
            s = datetime.fromisoformat(self.started_at)
            f = datetime.fromisoformat(self.finished_at)
            return (f - s).total_seconds()
        except Exception:
            return 0.0

    def summary(self) -> str:
        parts = [
            f"🌙 夢境週期完成 [{self.triggered_by}]",
            f"  耗時：{self.duration_seconds:.1f}s",
            f"  重播：{self.replay.episodes_processed} 個情節，"
            f"新增程序 {self.replay.procedures_created}，精化 {self.replay.procedures_refined}",
            f"  蒸餾：{self.distillation.rules_created} 條規則，"
            f"{self.distillation.concepts_created} 個概念",
            f"  修剪：{self.pruning.edges_pruned} 條邊緣，"
            f"橋接 {self.pruning.bridges_created} 個頓悟捷徑",
        ]
        if self.error:
            parts.append(f"  ⚠️ 錯誤：{self.error}")
        return "\n".join(parts)


class DreamEngine:
    """
    openSOUL Dream Engine 主體。

    設計為單例模式（透過 get_dream_engine() 取得）。
    內部使用 APScheduler BackgroundScheduler，
    不佔用主執行緒，對即時對話完全透明。

    Usage:
        engine = DreamEngine()
        engine.start()             # 啟動排程器

        # 手動觸發（CLI / 測試用）
        report = engine.dream_now(triggered_by="manual")
        print(report.summary())

        engine.stop()              # 關閉排程器
    """

    def __init__(
        self,
        graph_client: GraphClient | None = None,
        soul_loader: SoulLoader | None = None,
    ) -> None:
        self._graph = graph_client or get_graph_client()
        self._loader = soul_loader or SoulLoader()
        self._scheduler = BackgroundScheduler(timezone="Asia/Taipei")
        self._lock = threading.Lock()           # 防止並發夢境週期
        self._is_dreaming = False
        self._last_interaction: datetime = datetime.utcnow()
        self._last_dream_report: DreamReport | None = None

        # 子模組
        self._replay = LiDERReplay(self._graph)
        self._distillation = KnowledgeDistillation(self._graph)
        self._pruning = GraphPruning(self._graph)

    # ── 排程控制 ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        """啟動 APScheduler 排程器，設定雙觸發條件。"""
        if self._scheduler.running:
            return

        # 閒置觸發：每 60 秒檢查一次，若閒置超過設定時間則觸發
        self._scheduler.add_job(
            func=self._idle_check,
            trigger=IntervalTrigger(seconds=60),
            id="idle_check",
            replace_existing=True,
            misfire_grace_time=30,
        )

        # Cron 觸發：定時（預設凌晨 3 點）
        try:
            cron_parts = settings.soul_dream_cron.split()
            if len(cron_parts) == 5:
                minute, hour, day, month, day_of_week = cron_parts
                self._scheduler.add_job(
                    func=lambda: self._trigger_dream("cron"),
                    trigger=CronTrigger(
                        minute=minute,
                        hour=hour,
                        day=day,
                        month=month,
                        day_of_week=day_of_week,
                    ),
                    id="cron_dream",
                    replace_existing=True,
                    misfire_grace_time=300,
                )
        except Exception:
            pass  # Cron 解析失敗不影響整體運作

        self._scheduler.start()
        # 注意：Gmail 輪詢現已獨立為 openclaw/skills/gmail，不在 Dream Engine 中管理

    def stop(self) -> None:
        """關閉排程器（應在程式結束時呼叫）。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def notify_interaction(self) -> None:
        """每次使用者對話時呼叫，重置閒置計時器。"""
        self._last_interaction = datetime.utcnow()

    # ── 夢境執行 ───────────────────────────────────────────────────────────────

    def dream_now(self, triggered_by: str = "manual") -> DreamReport:
        """
        立即執行一個完整的夢境週期。

        Args:
            triggered_by: 觸發來源標籤（"manual" / "idle" / "cron"）

        Returns:
            DreamReport 完整執行報告
        """
        with self._lock:
            if self._is_dreaming:
                # 防止並發執行
                r = DreamReport()
                r.error = "夢境週期已在執行中，跳過本次觸發"
                return r
            self._is_dreaming = True

        report = DreamReport(
            started_at=datetime.utcnow().isoformat(),
            triggered_by=triggered_by,
        )

        try:
            # ── 階段 1：LiDER 經驗重播 ──────────────────────────────────────
            report.replay = self._replay.run()

            # ── 階段 2：知識蒸餾（情節 → 語意規則）─────────────────────────
            report.distillation = self._distillation.run()

            # ── 階段 3：圖譜修剪 + 跨域橋接 ─────────────────────────────────
            report.pruning = self._pruning.run()

            # ── 更新 SOUL.md ─────────────────────────────────────────────────
            self._sync_soul_md(report)

        except Exception as exc:
            report.error = str(exc)
        finally:
            report.finished_at = datetime.utcnow().isoformat()
            with self._lock:
                self._is_dreaming = False
            self._last_dream_report = report

        return report

    def status(self) -> dict[str, Any]:
        """回傳 Dream Engine 目前的狀態快照（供 CLI / API 展示）。"""
        idle_seconds = (datetime.utcnow() - self._last_interaction).total_seconds()
        return {
            "scheduler_running": self._scheduler.running,
            "is_dreaming": self._is_dreaming,
            "idle_seconds": round(idle_seconds, 1),
            "idle_threshold_seconds": settings.soul_dream_idle_minutes * 60,
            "last_dream_report": (
                self._last_dream_report.summary()
                if self._last_dream_report else "尚未執行任何夢境週期"
            ),
        }

    # ── Private ───────────────────────────────────────────────────────────────

    def _idle_check(self) -> None:
        """每分鐘執行的閒置檢查，若超過閾值則觸發夢境。"""
        idle_minutes = (
            datetime.utcnow() - self._last_interaction
        ).total_seconds() / 60.0

        if idle_minutes >= settings.soul_dream_idle_minutes:
            self._trigger_dream("idle")

    def _trigger_dream(self, source: str) -> None:
        """在背景執行緒中啟動夢境週期。"""
        if self._is_dreaming:
            return
        threading.Thread(
            target=self.dream_now,
            args=(source,),
            daemon=True,
        ).start()

    def _sync_soul_md(self, report: DreamReport) -> None:
        """將夢境完成後的狀態同步回 SOUL.md。"""
        try:
            soul = self._loader.load()
            neurochem = soul.neurochem

            # 夢境品質越高，給予輕微多巴胺獎勵（鼓勵系統自我優化）
            discoveries = report.pruning.bridges_created + report.replay.procedures_created
            if discoveries > 0:
                neurochem.on_discovery(novelty=min(0.3, discoveries * 0.05))

            # 夢境結束 → 血清素略微正規化
            neurochem.natural_decay(hours=0.5)

            self._loader.save_neurochem(neurochem)
            self._loader.save_stats(
                total_episodes=0,    # 實際數值由 CLI status 動態查詢
                total_concepts=0,
                total_procedures=0,
                last_dream=report.finished_at,
            )
        except Exception:
            pass  # SOUL.md 更新失敗不影響夢境主流程


# ── 全域單例 ──────────────────────────────────────────────────────────────────

_dream_engine: DreamEngine | None = None


def get_dream_engine() -> DreamEngine:
    """取得全域 DreamEngine 單例（Lazy 初始化）。"""
    global _dream_engine
    if _dream_engine is None:
        _dream_engine = DreamEngine()
    return _dream_engine
