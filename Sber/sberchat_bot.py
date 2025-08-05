import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, MessageContentType
from dialog_bot_sdk.entities.messaging import MessageHandler, CommandHandler
from ai_agent import check_general_message_with_gigachat, check_idea_with_gigachat_local, generate_files


from dialog_bot_sdk.interactive_media import (
    InteractiveMedia,
    InteractiveMediaGroup,
    InteractiveMediaButton,
    InteractiveMediaWidget,
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
            InteractiveMedia(
                buttons=[
                    InteractiveMediaButton("Давай шаблон!", "Давай шаблон!"),
                    InteractiveMediaButton("Я могу и сам написать", "Я могу и сам написать")
                ]
            )
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

def text_handler(update: UpdateMessage, widget=None):
    text = update.message.text.lower()
    peer = update.peer
    user_id = peer.id

    # Получаем ответ от GigaChat
    response_text, is_maybe_idea, command = check_general_message_with_gigachat(text)
    bot.messaging.send_message(peer, f"🤖 GigaChat ответил:\n\n{response_text}")

    if command:
        if command == "start":
            start_handler(update)
        elif command == "help":
            help_handler(update)
        elif command == "idea":
            idea_handler(update)
        elif command == "ai_agent":
            agent_handler(update)
        elif command == "group":
            group_handler(update)

        # Показываем кнопки
        media_group = InteractiveMediaGroup(
            media=[
                InteractiveMedia(
                    widget=InteractiveMediaWidget(
                        buttons=[
                            InteractiveMediaButton("🟢 Начать", "start"),
                            InteractiveMediaButton("📝 Описать идею", "idea"),
                            InteractiveMediaButton("📂 Скачать агентов", "ai_agent"),
                            InteractiveMediaButton("🔍 Найти инициативы", "group"),
                            InteractiveMediaButton("📮 Помощь", "help"),
                        ]
                    )
                )
            ]
        )
        bot.messaging.send_message(peer, "🔘 Выберите действие:", [media_group])
        return

    # Обработка идей (если это идея)
    if is_maybe_idea:
        user_states[user_id] = {"mode": "choose"}
        bot.messaging.send_message(peer,
            "🧠 Похоже, у вас идея! Хотите её оформить?\n\n"
            "1️⃣ *Давай шаблон!* — я помогу поэтапно сформулировать идею.\n"
            "2️⃣ *Я сам напишу* — напишите идею одним сообщением.\n\n"
            "👉 Напишите `шаблон` или `сам`, или нажмите кнопку ниже:")
        
        idea_group = InteractiveMediaGroup(
            media=[
                InteractiveMedia(
                    widget=InteractiveMediaWidget(
                        buttons=[
                            InteractiveMediaButton("Давай шаблон!", "Давай шаблон!"),
                            InteractiveMediaButton("Я могу и сам написать", "Я могу и сам написать"),
                        ]
                    )
                )
            ]
        )
        bot.messaging.send_message(peer, "Выберите формат описания идеи:", [idea_group])

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
