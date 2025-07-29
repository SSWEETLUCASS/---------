import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage
from dialog_bot_sdk.entities.messaging import MessageContentType, MessageHandler, CommandHandler
from dialog_bot_sdk.entities.users import User

from ai_agent import check_idea_with_gigachat_local, generate_files

load_dotenv()

# Установка переменных среды для сертификации SSL
os.environ["REQUESTS_CA_BUNDLE"] = '/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/SberCA.pem'
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = '/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/russiantrustedca.pem'

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
    user_id = message.sender_uid
    msg = message.text_message.text.strip()
    peer = update.peer

    state = user_states.get(user_id, {})

    logging.info(f"📩 Получено сообщение: {msg} от пользователя {user_id}")

    if msg.lower() in ["/start", "./start", "start"]:
        start_handler(update)
        return
    elif msg.lower() in ["/idea", "idea","идея","придумал"]:
        idea_handler(update)
        return
    elif msg.lower() in ["/ai", "ai","агент","агентолог"]:
        agent_handler(update)
        return
    elif msg.lower() in ["/help","help","помощь"]:
        help_handler(update)
        return
    elif msg.lower() in ["/Кто поможет?", "ai_agent","агенты","агентолог"]:
        group_handler(update)
        return

    # Обработка идеи в свободной форме
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

    # Обработка идеи по шаблону
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

    # Инициация шаблона
    if msg == "Давай шаблон!":
        user_states[user_id] = {
            "mode": "template",
            "step": 0,
            "data": {}
        }
        bot.messaging.send_message(peer, f"1️⃣ {TEMPLATE_FIELDS[0]}:")
        return

    # Инициация свободной формы
    if msg == "Я могу и сам написать":
        user_states[user_id] = {"mode": "freeform"}
        bot.messaging.send_message(peer, "✍️ Введите вашу идею в свободной форме:")
        return

def start_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, """
👋 Привет, @user_name!
    Меня зовут *Агентолог*, я помогу тебе с идеями для AI-агентов.

    Вот что я могу сделать:
    1. *У меня есть идея!*💡
       Я помогу тебе узнать, твоя идея уникальна!
    2. *АИ-агенты?*📍
      АИ-агенты разрабатываются каждый день, здесь мы собрали самый свежий список агентов!
    3. *Кто поможет?*💬
       Агентов очень много и не всегда можно найти, кто их разрабатывает. Давай подскажем, кто эти люди!
    4. *Поддержка📝*
      Остались вопросы или предложения по работе чат-бота? Пиши нам!
    Скорее выбирай, что мы будем делать, просто напиши текстом!
""")

def idea_handler(message: UpdateMessage) -> None:
    peer = message.peer
    bot.messaging.send_message(peer, "💬 Опиши свою идею свободно, я проверю её уникальность:")
    user_states[message.message.sender_uid] = {"mode": "freeform"}

def agent_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, "📍 Отправялю тебе список самых свежих агентов:")

def help_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, """
📝 Поддержка:
📬 Пишите нам: @sigma.sbrf.ru@22754707
📞 Пишите нам: 
📧 Пишите нам: sigma.sbrf.ru@22754707
""")

def group_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, "Давай поищем, кто это!")

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

    bot.messaging.message_handler([MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)])
    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()
