import logging
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

class TelegramClient:
    def __init__(self):
        self.bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        self.chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', None)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    def send_message(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram Bot Token or Chat ID not configured. Skipping alert.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        try:
            with httpx.Client() as client:
                response = client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
                logger.info("Telegram alert sent successfully.")
                return True
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False
