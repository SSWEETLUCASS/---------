import os
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.updates.update_handler import UpdateHandler
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

class BotHandler(UpdateHandler):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def on_message(self, peer, sender, message_text):
        user_id = sender.uid
        msg = message_text.strip()

        self.bot.messaging.send_message(
            peer,
            "👋 Привет, @lucas_no_way! Я помогу тебе с идеями для AI-агентов. Выбери, что мы будем делать:",
            [InteractiveMedia(
                actions=[
                    InteractiveButton("У меня есть идея!💌", "У меня есть идея!💌"),
                    InteractiveButton("АИ-агенты?📍", "АИ-агенты?📍"),
                    InteractiveButton("Кто поможет?💬", "Кто поможет?💬"),
                    InteractiveButton("Поддержка📝", "Поддержка📝"),
                ]
            )]
        )

        if msg == "У меня есть идея!💌":
            user_states[user_id] = {
                "mode": "choose",
                "step": None,
                "data": {},
                "giga_mode": False
            }
            self.bot.messaging.send_message(
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

        if user_id in user_states and user_states[user_id].get("mode") == "choose":
            if msg.lower() in ("шаблон", "по шаблону"):
                user_states[user_id]["mode"] = "template"
                user_states[user_id]["step"] = 0
                user_states[user_id]["data"] = {}
                self.bot.messaging.send_message(peer, f"1⃣ {TEMPLATE_FIELDS[0]}:")
            elif msg.lower() in ("свободно", "свободная форма"):
                user_states[user_id]["mode"] = "freeform"
                self.bot.messaging.send_message(peer, "📝 Опишите инициативу в свободной форме:")
            else:
                self.bot.messaging.send_message(peer, "❓ Пожалуйста, выберите: шаблон или свободно.")
            return

        if user_states.get(user_id, {}).get("mode") == "freeform":
            idea_text = msg
            self.bot.messaging.send_message(peer, "🔍 Проверяю через GigaChat...")
            result, is_unique, parsed_data = check_idea_with_gigachat_local(
                idea_text,
                {"Описание в свободной форме": idea_text},
                is_free_form=True
            )
            self.bot.messaging.send_message(peer, f"🤖 Ответ GigaChat:\n\n{result}")
            if is_unique:
                self.bot.messaging.send_message(peer, "✅ Идея уникальна!")
                if parsed_data:
                    word_path, excel_path = generate_files(parsed_data)
                    with open(word_path, "rb") as doc_file:
                        self.bot.messaging.send_file(peer, doc_file.read(), word_path)
                    with open(excel_path, "rb") as excel_file:
                        self.bot.messaging.send_file(peer, excel_file.read(), excel_path)
                    os.remove(word_path)
                    os.remove(excel_path)
                else:
                    self.bot.messaging.send_message(peer, "⚠️ Не удалось распознать поля для генерации шаблонов.")
            else:
                self.bot.messaging.send_message(peer, "⚠️ Идея не уникальна или неполна.")
            user_states.pop(user_id)
            return

        if user_states.get(user_id, {}).get("mode") == "template":
            state = user_states[user_id]
            step = state["step"]
            if step is not None and step < len(TEMPLATE_FIELDS):
                field = TEMPLATE_FIELDS[step]
                state["data"][field] = msg
                state["step"] += 1

                if state["step"] < len(TEMPLATE_FIELDS):
                    next_field = TEMPLATE_FIELDS[state["step"]]
                    self.bot.messaging.send_message(peer, f"{state['step'] + 1}⃣ {next_field}:")
                else:
                    self.bot.messaging.send_message(peer, "🔍 Проверяю через GigaChat...")
                    data = {
                        "Название инициативы": state["data"].get("Название", ""),
                        "Что хотим улучшить?": state["data"].get("Что хотим улучшить?", ""),
                        "Какие данные поступают агенту на выход?": state["data"].get("Какие данные поступают агенту на выход?", ""),
                        "Как процесс выглядит сейчас? as-is": state["data"].get("Как процесс выглядит сейчас? as-is", ""),
                        "Какой результат нужен от агента?": state["data"].get("Какой результат нужен от агента?", ""),
                        "Достижимый идеал(to-be)": state["data"].get("Достижимый идеал(to-be)", ""),
                        "Масштаб процесса": state["data"].get("Масштаб процесса", "")
                    }
                    result, is_unique, _ = check_idea_with_gigachat_local("", data)
                    self.bot.messaging.send_message(peer, f"🤖 Ответ GigaChat:\n\n{result}")
                    if is_unique:
                        self.bot.messaging.send_message(peer, "✅ Идея уникальна! Генерирую документы...")
                        word_path, excel_path = generate_files(data)
                        with open(word_path, "rb") as doc_file:
                            self.bot.messaging.send_file(peer, doc_file.read(), word_path)
                        with open(excel_path, "rb") as excel_file:
                            self.bot.messaging.send_file(peer, excel_file.read(), excel_path)
                        os.remove(word_path)
                        os.remove(excel_path)
            return

        if msg == "АИ-агенты?📍":
            self.bot.messaging.send_message(
                peer,
                "📋 Что хотите сделать?",
                [InteractiveMedia(
                    actions=[
                        InteractiveButton("Все агенты", "все агенты"),
                        InteractiveButton("Искать по названию", "искать по названию"),
                    ]
                )]
            )
            return

        if msg.lower() == "все агенты":
            try:
                with open("agents.xlsx", "rb") as f:
                    self.bot.messaging.send_file(peer, f.read(), "agents.xlsx")
            except Exception as e:
                self.bot.messaging.send_message(peer, f"❌ Не удалось отправить файл: {e}")
            return

        if msg.lower() == "искать по названию":
            agent_query_state[user_id] = True
            self.bot.messaging.send_message(peer, "🔍 Введи название агента:")
            return

        if agent_query_state.get(user_id):
            agent_query_state[user_id] = False
            term = msg.lower()
            try:
                wb = load_workbook("agents.xlsx")
                ws = wb.active
                results = [r for r in ws.iter_rows(min_row=2, values_only=True) if term in (r[0] or '').lower()]
                if not results:
                    self.bot.messaging.send_message(peer, "❌ Агент не найден.")
                else:
                    for r in results:
                        name, team, contact, desc = r
                        self.bot.messaging.send_message(
                            peer,
                            f"Название: {name}\nКоманда: {team}\nКонтакт: {contact}\nОписание: {desc}"
                        )
            except Exception as e:
                self.bot.messaging.send_message(peer, f"⚠️ Ошибка при поиске: {e}")
            return

        if msg == "Кто поможет?💬":
            self.bot.messaging.send_message(peer, "🧑‍💻 Пока эта функция в разработке.")
            return

        if msg == "Поддержка📝":
            self.bot.messaging.send_message(peer, "✉️ Напиши нам")
            return

        self.bot.messaging.send_message(peer, "🤖 Я вас не понял. Пожалуйста, выбери действие из меню!")

def text_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, f"🔁 Вы написали: {message.message.text_message.text}")

def start_handler(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, "👋 Привет! Я эхо-бот, готов помочь с идеями!")

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": "epbotsift.sberchat.sberbank.ru",
        "token": "58068397c86a2b216dadeb7d967965328b95278e",
        "is_secure": True,
    })

    handler = BotHandler(bot)
    bot.updates.set_update_handler(handler)

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
