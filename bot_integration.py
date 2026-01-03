# bot_integration.py
import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError
import os

logger = logging.getLogger(__name__)


class TelegramSender:
    def __init__(self, token=None):
        self.token = token or os.environ.get('BOT_TOKEN')
        self.bot = None
        if self.token:
            try:
                self.bot = Bot(token=self.token)
                logger.info("Telegram бот инициализирован для рассылки")
            except Exception as e:
                logger.error(f"Ошибка инициализации Telegram бота: {e}")

    async def send_message_async(self, chat_id, text):
        """Асинхронная отправка сообщения"""
        if not self.bot:
            return False

        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='HTML'
            )
            return True
        except TelegramError as e:
            logger.error(f"Ошибка отправки пользователю {chat_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка отправки пользователю {chat_id}: {e}")
            return False

    def send_message_sync(self, chat_id, text):
        """Синхронная обертка для асинхронной отправки"""
        if not self.bot:
            return False

        try:
            # Создаем новое событийное луп для каждого вызова
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.send_message_async(chat_id, text))
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Ошибка в синхронной обертке: {e}")
            return False


# Глобальный экземпляр для использования в admin_panel.py
telegram_sender = TelegramSender()