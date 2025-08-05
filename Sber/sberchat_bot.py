import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, MessageContentType
from dialog_bot_sdk.entities.messaging import MessageHandler, CommandHandler
from dialog_bot_sdk.interactive_media import (
    InteractiveMedia,
    InteractiveMediaGroup,
    InteractiveMediaButton,
)

from ai_agent import (
    check_general_message_with_gigachat,
    check_idea_with_gigachat_local,
    generate_files,
)

# Загрузка переменных окружения
load_dotenv()

# Установка путей к сертификатам
os.environ["REQUESTS_CA_BUNDLE"] = "/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/SberCA.pem"
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = "/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/russiantrustedca.pem"

BOT_TOKEN = os.getenv("DIALOG_BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

TEMPLATE_FIELDS = [
    "Название инициативы", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
    "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
    "Достижимый идеал(to-be)", "Масштаб процесса"
]

user_states = {}

def format_response(text: str) -> str:
    lines = text.strip().split("\n")
    formatted = "\n".join([
        f"• {line.strip().lstrip('*').rstrip('*')}"
        if not line.strip().startswith("#") else f"\n{line.strip('#').strip()}\n"
        for line in lines if line.strip()
    ])
    return formatted.strip()

def start_handler(update: UpdateMessage) -> None:
    bot.messaging.send_message(update.peer, """
👋 Привет!
Меня зовут *Агентолог*, я помогу тебе с идеями для AI-агентов.

Вот что я могу сделать:
1. *У меня есть идея!*💡 — проверить, уникальна ли идея
2. *АИ-агенты?*📍 — скачать список уже реализованных
3. *Кто поможет?*💬 — найти владельцев
4. *Поддержка📝* — задать вопрос команде
""")

    bot.messaging.send_message(update.peer, "Выберите действие:", [
        InteractiveMediaGroup([
            InteractiveMedia([
                InteractiveMediaButton("Помощь", "help"),
                InteractiveMediaButton("Скачать агентов", "agents"),
                InteractiveMediaButton("Инициативы", "groups"),
                InteractiveMediaButton("Проверить идею", "idea"),
            ])
        ])
    ])

def idea_handler(update: UpdateMessage) -> None:
    peer = update.peer
    user_id = peer.id
    user_states[user_id] = {"mode": "choose"}

    bot.messaging.send_message(peer,
        "📝 *Как вы хотите описать свою идею?*\n\n"
        "1️⃣ *Давай шаблон!* — я помогу поэтапно сформулировать идею по полям.\n"
        "2️⃣ *Я могу и сам написать* — если ты уже знаешь, что хочешь, напиши всё одним сообщением.\n\n"
        "👉 Напиши `шаблон` или `сам`, или нажми кнопку ниже:")

    media_group = InteractiveMediaGroup(
        media=[
            InteractiveMedia([
                InteractiveMediaButton("Давай шаблон!", "Давай шаблон!"),
                InteractiveMediaButton("Я могу и сам написать", "Я могу и сам написать")
            ])
        ]
    )
    bot.messaging.send_message(peer, "Выберите формат описания идеи:", [media_group])

def agent_handler(update: UpdateMessage) -> None:
    peer = update.peer
    agents_file_path = "agents.xlsx"
    if os.path.exists(agents_file_path):
        with open(agents_file_path, "rb") as f:
            bot.messaging.send_file(peer, f, filename="agents.xlsx")
    else:
        bot.messaging.send_message(peer, "⚠️ Файл с агентами не найден.")

def group_handler(update: UpdateMessage) -> None:
    peer = update.peer
    agents_file_path = "agents.xlsx"
    if not os.path.exists(agents_file_path):
        bot.messaging.send_message(peer, "⚠️ Файл с агентами не найден.")
        return

    query_text = "Найди информацию по AI-агентам на основе файла"
    user_data = {"Файл": agents_file_path}
    bot.messaging.send_message(peer, "🔍 Выполняю поиск через GigaChat...")
    response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(query_text, user_data, is_free_form=True)
    bot.messaging.send_message(peer, f"🤖 Результат:\n\n{format_response(response)}")

def help_handler(update: UpdateMessage) -> None:
    bot.messaging.send_message(update.peer, """
📝 Поддержка:
📬 @sigma.sbrf.ru@22754707
📧 sigma.sbrf.ru@22754707
""")

    bot.messaging.send_message(update.peer, "Могу предложить:", [
        InteractiveMediaGroup([
            InteractiveMedia([
                InteractiveMediaButton("Хочу начать", "start"),
                InteractiveMediaButton("Скачать агентов", "agents"),
                InteractiveMediaButton("Инициативы", "groups"),
            ])
        ])
    ])

def text_handler(update: UpdateMessage, widget=None):
    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer

    gpt_response, maybe_idea, command = check_general_message_with_gigachat(text)

    logging.info(f"📩 Пользователь: {text}")
    logging.info(f"🔎 Ответ GigaChat: {gpt_response}, CMD: {command}, Похоже на идею: {maybe_idea}")

    # Обработка команд через текст
    if command == "help":
        help_handler(update)
        return

    elif command == "start":
        start_handler(update)
        return

    elif command == "ai_agent":
        agent_handler(update)
        return

    elif command == "group":
        group_handler(update)
        return

    elif command == "idea":
        idea_handler(update)
        return

    # Если GigaChat распознал идею
    if maybe_idea:
        bot.messaging.send_message(peer, "💡 Похоже, вы описали идею. Сейчас проверю...")

        user_data = {"Описание в свободной форме": text}
        response, is_unique, parsed_data, suggest_processing = check_idea_with_gigachat_local(text, user_data, is_free_form=True)

        bot.messaging.send_message(peer, f"🧠 Ответ GigaChat:\n\n{format_response(response)}")

        if parsed_data:
            word_path, excel_path = generate_files(parsed_data)
            bot.messaging.send_message(peer, "📎 Прикладываю файлы с вашей инициативой:")

            with open(word_path, "rb") as f_docx:
                bot.messaging.send_file(peer, f_docx, filename=os.path.basename(word_path))

            with open(excel_path, "rb") as f_xlsx:
                bot.messaging.send_file(peer, f_xlsx, filename=os.path.basename(excel_path))

            os.remove(word_path)
            os.remove(excel_path)

        elif suggest_processing:
            bot.messaging.send_message(peer, "🤔 Вы хотите проверить идею на уникальность? Могу помочь!")

    else:
        # Если ничего не распознано — просто ответ от GigaChat
        bot.messaging.send_message(
            peer,
            gpt_response or "🤖 Я вас не понял. Попробуйте ещё раз.",
            [InteractiveMediaGroup([
                InteractiveMedia([
                    InteractiveMediaButton("Помощь", "help"),
                    InteractiveMediaButton("Начать", "start"),
                ])
            ])]
        )

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": "epbotsift.sberchat.sberbank.ru",
        "token": BOT_TOKEN,
        "is_secure": True,
    })

    bot.messaging.command_handler([
        CommandHandler(start_handler, "start"),
        CommandHandler(idea_handler, "idea"),
        CommandHandler(agent_handler, "ai_agent"),
        CommandHandler(group_handler, "group"),
        CommandHandler(help_handler, "help"),
    ])

    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)
    ])

    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()
