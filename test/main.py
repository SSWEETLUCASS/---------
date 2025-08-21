import asyncio
import logging
import os
from dotenv import load_dotenv

from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.interactive_media import InteractiveMediaGroup, InteractiveMedia, SelectableOption
from dialog_bot_sdk.entities.peers import Peer

load_dotenv()

BOT_ENDPOINT = os.getenv("BOT_ENDPOINT")  # например: 'https://uapp.dialog.ru'
BOT_TOKEN = os.getenv("BOT_TOKEN")        # токен от СберЧата

# === Логгер ===
logging.basicConfig(level=logging.INFO)

# === Инициализация SDK ===
bot: DialogBot = DialogBot.get_secure_bot(
    BOT_ENDPOINT,
    BOT_TOKEN
)

# === Обработка входящих сообщений ===
def on_msg(event):
    user_peer: Peer = event.peer
    text = event.message.textMessage.text.strip().lower()

    if text == "ping":
        bot.messaging.send_message(user_peer, "pong ✅")
    else:
        bot.messaging.send_message(user_peer, "Напиши 'ping' для проверки.")

# === Подписка на события ===
def main():
    print("🤖 Бот запущен. Ожидаем сообщения...")
    bot.messaging.on_message(on_msg)
    loop = asyncio.get_event_loop()
    loop.run_forever()

if __name__ == "__main__":
    main()
