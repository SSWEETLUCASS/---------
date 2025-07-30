import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage
from dialog_bot_sdk.models import InteractiveMedia, InteractiveButton
from dialog_bot_sdk.entities.messaging import MessageContentType, MessageHandler, CommandHandler

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


def text_handler(message: UpdateMessage) -> None:
    user_id = message.sender.uid
    msg = message.message.text_message.text.strip()
    peer = message.peer

    state = user_states.get(user_id, {})

    if state.get("mode") == "freeform":
        user_data = {"Описание в свободной форме": msg}
        bot.messaging.send_message(peer, "🔍 Отправляю идею в GigaChat...")
        response, is_unique, parsed_data = check_idea_with_gigachat_local(msg, user_data, is_free_form=True)
        bot.messaging.send_message(peer, f"🤖 Ответ GigaChat:\n\n{response}")

        if is_unique and parsed_data:
            word_path, excel_path = generate_files(parsed_data)
            bot.messaging.send_file(peer, word_path)
            bot.messaging.send_file(peer, excel_path)

        user_states.pop(user_id)
        return

    elif state.get("mode") == "template":
        step = state.get("step", 0)
        state.setdefault("data", {})
        field = TEMPLATE_FIELDS[step]
        state["data"][field] = msg
        step += 1

        if step < len(TEMPLATE_FIELDS):
            user_states[user_id]["step"] = step
            bot.messaging.send_message(peer, f"{step + 1}️⃣ {TEMPLATE_FIELDS[step]}:")
        else:
            bot.messaging.send_message(peer, "✅ Проверяю инициативу через GigaChat...")
            result, is_unique, _ = check_idea_with_gigachat_local("", state["data"], is_free_form=False)
            bot.messaging.send_message(peer, f"🤖 Ответ GigaChat:\n\n{result}")
            if is_unique:
                word_path, excel_path = generate_files(state["data"])
                bot.messaging.send_file(peer, word_path)
                bot.messaging.send_file(peer, excel_path)
            user_states.pop(user_id)
        return

    if msg == "У меня есть идея!💌":
        user_states[user_id] = {
            "mode": "choose",
            "step": None,
            "data": {},
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

    if msg == "Давай шаблон!":
        user_states[user_id] = {
            "mode": "template",
            "step": 0,
            "data": {}
        }
        bot.messaging.send_message(peer, f"1️⃣ {TEMPLATE_FIELDS[0]}:")
        return

    if msg == "Я могу и сам написать":
        user_states[user_id] = {"mode": "freeform"}
        bot.messaging.send_message(peer, "✍️ Введите вашу идею в свободной форме:")
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
    bot.messaging.send_message(message.peer, "👋 Привет! Я Агентолог — бот, который помогает оценить идеи для AI-агентов!")


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
