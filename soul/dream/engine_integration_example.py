"""
梦境引擎 - Telegram 集成示例
在您的 soul/dream/engine.py 中添加以下代碼

⚠️ 重要：梦境反思直接使用 OpenClaw 已有的 Telegram Bot Token
無需重複配置，只需在 .env 中啟用：
  SOUL_DREAM_TELEGRAM_NOTIFY=true
"""

# 在 engine.py 的頂部添加導入
from soul.dream.telegram_notifier import send_reflection_to_telegram
import logging

logger = logging.getLogger(__name__)


class DreamEngine:
    """梦境引擎 - 帶有 Telegram 通知功能"""

    async def generate_reflection(self, user_session_id: str) -> str:
        """
        生成夢境反思

        Args:
            user_session_id: 用戶會話 ID

        Returns:
            反思內容
        """
        # ... 現有的反思生成邏輯 ...

        reflection_content = await self._generate_reflection_content()

        # 📝 保存到本地（原有功能）
        self._save_reflection_to_file(reflection_content)

        # 📤 發送給用戶（原有功能）
        await self._send_to_user(user_session_id, reflection_content)

        # 🤖 NEW: 同時發送到 Telegram
        send_reflection_to_telegram(reflection_content)

        logger.info(f"✅ 夢境反思完成並已同時發送到用戶和 Telegram")

        return reflection_content

    async def _generate_reflection_content(self) -> str:
        """生成反思內容"""
        # 掃描高顯著性記憶
        high_salience_memories = await self._scan_high_salience_memories()

        # 進行跨領域關聯
        insights = await self._generate_insights(high_salience_memories)

        # 生成最終反思文本
        reflection = f"""
## 今日夢境反思

### 🔍 關鍵發現
{insights}

### 💭 思考演化
{await self._summarize_thinking_evolution()}

### 🧬 神經化學狀態更新
多巴胺: {self.neurochemistry.dopamine:.2f}
血清素: {self.neurochemistry.serotonin:.2f}
"""
        return reflection

    async def _send_to_user(self, user_session_id: str, content: str) -> None:
        """發送反思給用戶（通過 WebSocket 或 API）"""
        # 現有的用戶通知邏輯
        await self.socket_manager.send_message(
            user_session_id,
            {
                "type": "dream_reflection",
                "content": content,
                "timestamp": datetime.now().isoformat()
            }
        )

    def _save_reflection_to_file(self, content: str) -> None:
        """保存反思到文件"""
        # 現有的檔案保存邏輯
        pass


# ============================================================================
# 使用示例：在不同的觸發場景中調用
# ============================================================================

class DreamEngineWithTelegram:
    """
    完整示例：梦境引擎的三種觸發場景
    """

    async def trigger_scheduled_dream(self):
        """場景 1: 定時觸發（如凌晨 3 點）"""
        logger.info("🌙 定時夢境觸發...")

        reflection = await self.engine.generate_reflection(
            user_session_id="system"
        )
        # ✅ 自動：保存到檔案 + 發送給用戶 + 發送到 Telegram

    async def trigger_idle_dream(self, user_session_id: str):
        """場景 2: 閒置觸發（120 分鐘無互動）"""
        logger.info(f"😴 閒置夢境觸發（用戶: {user_session_id}）...")

        reflection = await self.engine.generate_reflection(user_session_id)
        # ✅ 自動：保存到檔案 + 發送給用戶 + 發送到 Telegram

    async def trigger_dopamine_dream(self, user_session_id: str):
        """場景 3: 多巴胺閾值觸發（系統狀態激動）"""
        current_da = self.neurochemistry.dopamine

        if current_da > self.dopamine_threshold:
            logger.info(f"⚡ 多巴胺夢境觸發（DA: {current_da:.2f}）...")

            reflection = await self.engine.generate_reflection(user_session_id)
            # ✅ 自動：保存到檔案 + 發送給用戶 + 發送到 Telegram

    async def manual_dream_command(self, user_session_id: str):
        """場景 4: 手動觸發（用戶輸入 /dream 命令）"""
        logger.info(f"👤 手動夢境觸發（用戶: {user_session_id}）...")

        reflection = await self.engine.generate_reflection(user_session_id)
        # ✅ 自動：保存到檔案 + 發送給用戶 + 發送到 Telegram


# ============================================================================
# 實際集成步驟
# ============================================================================
"""
將以下更改應用於 soul/dream/engine.py:

1. 在頂部導入:
   from soul.dream.telegram_notifier import send_reflection_to_telegram

2. 在 generate_reflection() 方法的最後添加:
   # 發送到 Telegram（如果啟用）
   send_reflection_to_telegram(reflection_content)

3. 就這樣！無需修改其他代碼。

示例位置：
--------
async def generate_reflection(self, user_session_id: str):
    # ... 現有代碼 ...

    # 保存和發送邏輯
    self._save_reflection(reflection)
    await self._send_to_user(reflection)

    # 新增 ↓
    send_reflection_to_telegram(reflection)  # 發送到 Telegram

    return reflection
"""
