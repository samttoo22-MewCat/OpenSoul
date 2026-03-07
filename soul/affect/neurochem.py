"""
soul/affect/neurochem.py

虛擬神經化學調節器：多巴胺（DA）與血清素（5-HT）狀態機。
對應大腦分區：杏仁核 (Amygdala) + 基底核（獎勵迴路）

設計原理：
  - 多巴胺（DA）：與獎勵預測誤差相關，驅動學習率與探索意願
  - 血清素（5-HT）：與穩定性和風險規避相關，調節謹慎程度
  - 兩者共同決定：圖譜搜尋廣度、邊緣權重學習率、基底核驗證閾值
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NeurochemMode(str, Enum):
    BALANCED = "balanced"
    HIGH_DOPAMINE = "high_dopamine"
    HIGH_SEROTONIN = "high_serotonin"
    EXCITED = "excited"       # 高 DA + 低 5-HT
    CAUTIOUS = "cautious"     # 低 DA + 高 5-HT


@dataclass
class NeurochemState:
    """
    虛擬神經化學狀態。

    所有屬性都在 [0.0, 1.0] 範圍內。
    可被序列化進 SOUL.md 的 YAML frontmatter，持久化跨 Session。

    改進（v2.0）：
      - 採用緩和式遞增調控（目標值接近，而非直接加減）
      - 每次事件有上限增量（da_max_per_cycle, ht_max_per_cycle）
      - 更快的自然衰減（5% per hour）
      - 調制參數可配置
    """

    dopamine: float = 0.5    # 多巴胺：獎勵/學習信號
    serotonin: float = 0.5   # 血清素：穩定性/謹慎信號

    # 🆕 調制參數（控制調節速度）
    da_update_rate: float = 0.08       # 朝向目標值的速率 [0.0, 1.0]
    ht_update_rate: float = 0.06       # 朝向目標值的速率 [0.0, 1.0]
    da_max_per_cycle: float = 0.15     # 單個事件的最大增量
    ht_max_per_cycle: float = 0.12     # 單個事件的最大增量
    decay_per_hour: float = 0.05       # 自然衰減速度（趨向 0.5）

    # ── 衍生屬性 ──────────────────────────────────────────────────────────────

    @property
    def mode(self) -> NeurochemMode:
        """根據 DA 與 5-HT 濃度判斷當前神經化學模式。"""
        da, ht = self.dopamine, self.serotonin
        if da >= 0.75 and ht < 0.4:
            return NeurochemMode.EXCITED
        if da < 0.35 and ht >= 0.65:
            return NeurochemMode.CAUTIOUS
        if da >= 0.65:
            return NeurochemMode.HIGH_DOPAMINE
        if ht >= 0.65:
            return NeurochemMode.HIGH_SEROTONIN
        return NeurochemMode.BALANCED

    @property
    def learning_rate(self) -> float:
        """邊緣權重更新的學習率（DA 越高 → 學得越快）。"""
        return 0.1 + self.dopamine * 0.9

    @property
    def search_breadth(self) -> int:
        """EcphoryRAG BFS 的廣度（血清素越高 → 搜尋越廣）。"""
        return int(5 + self.serotonin * 15)

    @property
    def verification_threshold(self) -> float:
        """基底核驗證通過所需的最低一致性分數（血清素越高 → 標準越嚴）。"""
        base = 0.5
        return min(0.9, base + self.serotonin * 0.4)

    @property
    def salience_boost(self) -> float:
        """DA 飆升時，新記憶的情感顯著性加乘因子。"""
        return 1.0 + self.dopamine * 0.5

    # ── 狀態更新事件 ──────────────────────────────────────────────────────────

    def on_success(self, reward: float = 0.3) -> None:
        """
        任務成功 / 使用者正向回饋 → 多巴胺平緩上升。
        使用緩和式遞增調控，而非直接加減。

        Args:
            reward: 獎勵強度 [0.0, 1.0]（預設0.3 = 中等獎勵）
        """
        # 🆕 目標多巴胺值
        da_target = 0.5 + reward * 0.4  # 目標值在 [0.5, 0.9] 之間
        # 計算朝向目標的增量（梯度下降）
        da_delta = (da_target - self.dopamine) * self.da_update_rate
        # 限制單步增量
        da_delta = min(da_delta, self.da_max_per_cycle)
        self.dopamine = _clamp(self.dopamine + da_delta)

        # 🆕 血清素反向反應（可承擔更多風險，但速度更緩）
        ht_delta = -reward * self.ht_update_rate * 0.5
        ht_delta = max(ht_delta, -self.ht_max_per_cycle)
        self.serotonin = _clamp(self.serotonin + ht_delta)

    def on_failure(self, penalty: float = 0.2) -> None:
        """
        驗證失敗 / 使用者負向回饋 → DA 緩和下降，5-HT 上升（謹慎模式）。

        Args:
            penalty: 懲罰強度 [0.0, 1.0]（預設0.2 = 輕微懲罰）
        """
        # 🆕 目標多巴胺值（下降但不低於0.2）
        da_target = max(0.2, 0.5 - penalty * 0.3)
        # 計算朝向目標的增量
        da_delta = (da_target - self.dopamine) * self.da_update_rate
        # 限制單步減幅
        da_delta = max(da_delta, -self.da_max_per_cycle)
        self.dopamine = _clamp(self.dopamine + da_delta)

        # 🆕 血清素上升（進入謹慎/保守模式，但有上限）
        ht_delta = penalty * self.ht_update_rate * 0.8
        ht_delta = min(ht_delta, self.ht_max_per_cycle)
        self.serotonin = _clamp(self.serotonin + ht_delta)

    def on_uncertainty(self, level: float = 0.2) -> None:
        """
        偵測到模糊指令 / 高不確定性 → 血清素平緩上升。

        Args:
            level: 不確定性程度 [0.0, 1.0]
        """
        # 🆕 血清素朝向更高目標上升
        ht_target = 0.5 + level * 0.3  # [0.5, 0.8]
        ht_delta = (ht_target - self.serotonin) * self.ht_update_rate
        ht_delta = min(ht_delta, self.ht_max_per_cycle)
        self.serotonin = _clamp(self.serotonin + ht_delta)

        # 多巴胺輕微下降
        da_delta = -level * self.da_update_rate * 0.2
        da_delta = max(da_delta, -self.da_max_per_cycle * 0.5)
        self.dopamine = _clamp(self.dopamine + da_delta)

    def on_discovery(self, novelty: float = 0.4) -> None:
        """
        發現新知識連結 / 圖譜頓悟捷徑 → DA 溫和飆升（但不超過0.85）。

        Args:
            novelty: 新穎性程度 [0.0, 1.0]
        """
        # 🆕 新知識給予中等獎勵（相比成功略低，但有上限）
        da_target = min(0.85, 0.5 + novelty * 0.35)  # [0.5, 0.85]
        # 速率稍高於成功事件（新知識更激勵）
        da_delta = (da_target - self.dopamine) * (self.da_update_rate * 1.2)
        # 有更寬鬆的上限（1.3倍）
        da_delta = min(da_delta, self.da_max_per_cycle * 1.3)
        self.dopamine = _clamp(self.dopamine + da_delta)

    def natural_decay(self, hours: float = 1.0) -> None:
        """
        隨時間自然衰減，趨向中性平衡（0.5, 0.5）。

        改進邏輯：
          - 衰減速度 = decay_per_hour * hours（預設5% per hour）
          - 衰減不超過20%（防止過度平坦化）
          - 例：DA=0.8 → 1小時後 DA≈0.7（衰減10%）
          - 例：DA=0.8 → 14小時後 DA≈0.6（衰減25%）
        """
        decay_factor = 1.0 - (self.decay_per_hour * hours)
        # 防止衰減過度（衰減不超過20%）
        decay_factor = max(0.8, decay_factor)

        # 趨向平衡值0.5（保留偏差的80-100%）
        self.dopamine = 0.5 + (self.dopamine - 0.5) * decay_factor
        self.serotonin = 0.5 + (self.serotonin - 0.5) * decay_factor

        # 鉗制到有效範圍
        self.dopamine = _clamp(self.dopamine)
        self.serotonin = _clamp(self.serotonin)

    def reset_to_balanced(self) -> None:
        """Dream Cycle 結束後重置至中性狀態。"""
        self.dopamine = 0.5
        self.serotonin = 0.5

    # ── 序列化 ─────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, float | str]:
        return {
            "dopamine": round(self.dopamine, 3),
            "serotonin": round(self.serotonin, 3),
            "mode": self.mode.value,
            "learning_rate": round(self.learning_rate, 3),
            "verification_threshold": round(self.verification_threshold, 3),
            "search_breadth": self.search_breadth,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NeurochemState":
        return cls(
            dopamine=float(data.get("dopamine_level", data.get("dopamine", 0.5))),
            serotonin=float(data.get("serotonin_level", data.get("serotonin", 0.5))),
        )

    def __repr__(self) -> str:
        return (
            f"NeurochemState(DA={self.dopamine:.2f}, "
            f"5-HT={self.serotonin:.2f}, "
            f"mode={self.mode.value})"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
