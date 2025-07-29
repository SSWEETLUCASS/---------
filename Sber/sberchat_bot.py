import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage
from dialog_bot_sdk.models import InteractiveMedia, InteractiveButton
from dialog_bot_sdk.entities.messaging import MessageContentType, MessageHandler, CommandHandler

from openpyxl import load_workbook
from ai_agent import check_idea_with_gigachat_local, generate_files

load_dotenv()

# Установка переменных среды для сертификации SSL
os.environ["REQUESTS_CA_BUNDLE"] = '/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/SberCA.pem'
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = '/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/russiantrustedca.pem'

BOT_TOKEN = os.getenv("DIALOG_BOT_TOKEN")

TEMPLATE_FIELDS = [
    "Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
    "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
    "Достижимый идеал(to-be)", "Масштаб процесса"
]

user_states = {}
agent_query_state = {}

def text_handler(message: UpdateMessage) -> None:
    user_id = message.sender.uid
    msg = message.message.text_message.text.strip()
    peer = message.peer

    if msg == "У меня есть идея!💌":
        user_states[user_id] = {
            "mode": "choose",
            "step": None,
            "data": {},
            "giga_mode": False
        }
        bot.messaging.send_message(
            peer,
            "📝 Как хотите описать идею?",
            [InteractiveMedia(
                actions=[
                    InteractiveButton("Давай шаблон!"),
                    InteractiveButton("Я могу и сам написать"),
                ]
            )]
        )
        return

    bot.messaging.send_message(
        peer,
        "👋 Привет, @lucas_no_way! \n"
        "Меня зовут Агентолог, я помогу тебе с идеями для AI-агентов.\n\n"
        "Вот что я могу сделать:\n"
        "1. У меня есть идея!💡\n"
        "   Я помогу тебе узнать, насколько твоя идея уникальна!\n\n"
        "2. АИ-агенты?📍\n"
        "   АИ-агенты разрабатываются каждый день, здесь мы собрали самый свежий список агентов!\n\n"
        "3. Кто поможет?💬\n"
        "   Агентов очень много и не всегда можно найти, кто их разрабатывает. Давай подскажем, кто эти люди!\n\n"
        "4. Поддержка📝\n"
        "   Остались вопросы или предложения по работе чат-бота? Пиши нам!\n\n"
        "Скорее выбирай, что мы будем делать👇",
        [InteractiveMedia(
            actions=[
                InteractiveButton("У меня есть идея!💌", "У меня есть идея!💌"),
                InteractiveButton("АИ-агенты?📍", "АИ-агенты?📍"),
                InteractiveButton("Кто поможет?💬", "Кто поможет?💬"),
                InteractiveButton("Поддержка📝", "Поддержка📝"),
            ]
        )]
    )

def start_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, "👋 Привет! Я эхо-бот, готов помочь с идеями!")

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": "epbotsift.sberchat.sberbank.ru",
        "token": BOT_TOKEN,
        "is_secure": True,
    })

    bot.messaging.command_handler([
        CommandHandler(start_handler, "start", description="Поздороваться"),
    ])

    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE),
    ])

    print("✅ Бот успешно запущен и готов к работе.")
    while True:
        pass

if __name__ == "__main__":
    main()
