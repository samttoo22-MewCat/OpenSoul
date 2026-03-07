"""
Telegram 通知模組 - 用於發送夢境反思到 Telegram
"""

import os
import logging
from typing import Optional
import asyncio
import httpx

logger = logging.getLogger(__name__)


class DreamTelegramNotifier:
    """負責將夢境反思發送到 Telegram（使用 OpenClaw 的 Telegram 配置）"""

    def __init__(self):
        self.enabled = os.getenv("SOUL_DREAM_TELEGRAM_NOTIFY", "false").lower() == "true"

        # 使用 OpenClaw 的 Telegram 配置（無需重複配置）
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

        # Chat ID 可以在 OpenClaw 配置或環境變數中取得
        # 優先使用專用配置，否則從 OpenClaw 的 Telegram 配置讀取
        self.chat_id = os.getenv("SOUL_TELEGRAM_CHAT_ID") or self._read_openclaw_chat_id()

        if self.enabled and (not self.chat_id or not self.bot_token):
            logger.warning(
                "Telegram 通知已啟用但配置不完整。"
                "請在 openclaw/.env 中設置 TELEGRAM_BOT_TOKEN，"
                "並設置 SOUL_TELEGRAM_CHAT_ID 環境變數"
            )
            self.enabled = False

    def _read_openclaw_chat_id(self) -> str:
        """
        嘗試從 OpenClaw 配置讀取 Chat ID
        如果 openclaw.json 中有配置則讀取
        """
        try:
            import json
            openclaw_config_path = os.getenv(
                "OPENCLAW_CONFIG_PATH",
                os.path.expanduser("~/.openclaw/openclaw.json")
            )
            if os.path.exists(openclaw_config_path):
                with open(openclaw_config_path, 'r') as f:
                    config = json.load(f)
                    # 嘗試從 channels 配置中取得 Telegram Chat ID
                    return config.get("channels", {}).get("telegram", {}).get("chat_id", "")
        except Exception as e:
            logger.debug(f"無法從 OpenClaw 配置讀取 Chat ID: {e}")
        return ""

    async def send_reflection(self, reflection_content: str) -> bool:
        """
        發送夢境反思到 Telegram

        Args:
            reflection_content: 反思內容

        Returns:
            是否發送成功
        """
        if not self.enabled or not self.chat_id or not self.bot_token:
            return False

        try:
            # 格式化消息
            message = self._format_message(reflection_content)

            # 發送到 Telegram
            await self._send_telegram_message(message)
            logger.info("✅ 夢境反思已發送到 Telegram")
            return True

        except Exception as e:
            logger.error(f"❌ 發送 Telegram 消息失敗: {e}")
            return False

    def _format_message(self, reflection_content: str) -> str:
        """格式化要發送到 Telegram 的消息"""
        return f"""🧠 **夢境反思**

{reflection_content}

---
⏰ 自動生成於梦境引擎
"""

    async def _send_telegram_message(self, text: str) -> None:
        """通過 Telegram Bot API 發送消息"""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"  # 支持 Markdown 格式
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()


# 全局實例（單例）
_telegram_notifier: Optional[DreamTelegramNotifier] = None


def get_telegram_notifier() -> DreamTelegramNotifier:
    """獲取 Telegram 通知器實例"""
    global _telegram_notifier
    if _telegram_notifier is None:
        _telegram_notifier = DreamTelegramNotifier()
    return _telegram_notifier


# 同步包裝函數（用於非異步上下文）
def send_reflection_to_telegram(reflection_content: str) -> bool:
    """同步發送反思到 Telegram"""
    notifier = get_telegram_notifier()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果已在異步上下文，創建任務
            asyncio.create_task(notifier.send_reflection(reflection_content))
            return True
        else:
            # 否則運行異步函數
            return loop.run_until_complete(notifier.send_reflection(reflection_content))
    except RuntimeError:
        # 沒有事件循環，創建新的
        return asyncio.run(notifier.send_reflection(reflection_content))
