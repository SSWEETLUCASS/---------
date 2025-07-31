import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, MessageContentType
from dialog_bot_sdk.entities.messaging import MessageHandler, CommandHandler
from dialog_bot_sdk.interactive_media import InteractiveMediaGroup, InteractiveMedia, InteractiveMediaButton

from ai_agent import check_idea_with_gigachat_local, generate_files

# Загрузка переменных окружения
load_dotenv()

# Установка путей к сертификатам
os.environ["REQUESTS_CA_BUNDLE"] = "/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/SberCA.pem"
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = "/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/russiantrustedca.pem"

BOT_TOKEN = os.getenv("DIALOG_BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

TEMPLATE_FIELDS = [
    "Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
    "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
    "Достижимый идеал(to-be)", "Масштаб процесса"
]

user_states = {}

def text_handler(update: UpdateMessage) -> None:
    message = update.message
    peer = update.peer
    user_id = peer.id

    # Получение текста и payload
    msg_text = message.text_message.text if message.text_message and message.text_message.text else ""
    payload = message.text_message.payload if message.text_message and message.text_message.payload else ""
    msg = payload.strip() if payload else msg_text.strip()

    state = user_states.get(user_id, {})

    logging.info(f"📩 Сообщение от {user_id} | msg: '{msg}' | payload: '{payload}' | state: {state}")

    # Команды
    if msg.lower() in ["/start", "./start", "start"]:
        start_handler(update)
        return
    elif msg.lower() in ["/idea", "idea", "идея", "придумал"]:
        idea_handler(update)
        return
    elif msg.lower() in ["/ai", "ai", "агент", "агентолог"]:
        agent_handler(update)
        return
    elif msg.lower() in ["/help", "help", "помощь"]:
        help_handler(update)
        return
    elif msg.lower() in ["/кто поможет?", "ai_agent", "агенты", "группа"]:
        group_handler(update)
        return

    # Режим выбора варианта
    if state.get("mode") == "choose":
        if msg in ["Давай шаблон!", "шаблон"]:
            user_states[user_id] = {
                "mode": "template",
                "step": 0,
                "data": {}
            }
            bot.messaging.send_message(peer, "🧾 Отлично! Заполняем шаблон.\nВведите следующий пункт:")
            bot.messaging.send_message(peer, f"1️⃣ {TEMPLATE_FIELDS[0]}:")
            return
        elif msg in ["Я могу и сам написать", "сам", "свободно"]:
            user_states[user_id] = {
                "mode": "freeform",
                "awaiting_text": True
            }
            bot.messaging.send_message(peer, "✍️ Введите свою идею в свободной форме:")
            return
        else:
            bot.messaging.send_message(peer, "⚠️ Пожалуйста, выберите один из предложенных вариантов:")
            idea_handler(update)
            return

    # Обработка свободной формы
    if state.get("mode") == "freeform" and state.get("awaiting_text"):
        user_data = {"Описание в свободной форме": msg}
        bot.messaging.send_message(peer, "🔍 Отправляю идею в GigaChat...")

        response, is_unique, parsed_data = check_idea_with_gigachat_local(msg, user_data, is_free_form=True)
        bot.messaging.send_message(peer, f"🤖 Ответ GigaChat:\n\n{response}")

        if is_unique and parsed_data:
            word_path, excel_path = generate_files(parsed_data)
            bot.messaging.send_file(peer, open(word_path, "rb"), filename=os.path.basename(word_path))
            bot.messaging.send_file(peer, open(excel_path, "rb"), filename=os.path.basename(excel_path))

        user_states.pop(user_id)
        return

    # Обработка шаблона
    if state.get("mode") == "template":
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
                bot.messaging.send_file(peer, open(word_path, "rb"), filename=os.path.basename(word_path))
                bot.messaging.send_file(peer, open(excel_path, "rb"), filename=os.path.basename(excel_path))
            user_states.pop(user_id)
        return

def start_handler(update: UpdateMessage) -> None:
    bot.messaging.send_message(update.peer, """
👋 Привет!
Меня зовут *Агентолог*, я помогу тебе с идеями для AI-агентов.

Вот что я могу сделать:
1. *У меня есть идея!*💡
2. *АИ-агенты?*📍
3. *Кто поможет?*💬
4. *Поддержка📝*
""")

def idea_handler(update: UpdateMessage) -> None:
    peer = update.peer
    user_id = peer.id
    user_states[user_id] = {"mode": "choose"}

    bot.messaging.send_message(peer, "📋 Как вы хотите описать свою идею?\n\nВыберите один из вариантов ниже:")

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

    bot.messaging.send_message(peer, "👇 Выберите способ:", [media_group])

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
    bot.messaging.send_message(peer, "🔍 Выполняю поиск в файле с агентами через GigaChat...")
    response, is_unique, parsed_data = check_idea_with_gigachat_local(query_text, user_data, is_free_form=True)
    bot.messaging.send_message(peer, f"🤖 Результат поиска:\n\n{response}")

def help_handler(update: UpdateMessage) -> None:
    bot.messaging.send_message(update.peer, """
📝 Поддержка:
📬 @sigma.sbrf.ru@22754707
📧 sigma.sbrf.ru@22754707
""")

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": "epbotsift.sberchat.sberbank.ru",
        "token": BOT_TOKEN,
        "is_secure": True,
    })

    bot.messaging.command_handler([
        CommandHandler(start_handler, "start", description="Поздороваться"),
        CommandHandler(idea_handler, "idea", description="Идея!"),
        CommandHandler(agent_handler, "ai_agent", description="Аи-агенты!"),
        CommandHandler(group_handler, "group", description="Группа разработки"),
        CommandHandler(help_handler, "help", description="Помощь"),
    ])

    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)
    ])

    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()
