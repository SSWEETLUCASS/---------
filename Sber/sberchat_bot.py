from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.handle_updates import AbstractHandler
from dialog_bot_sdk.entities.peers import PeerType
from dialog_bot_sdk.utils import AsyncTask
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from dotenv import load_dotenv
import logging
import os
import re
import requests
from datetime import datetime
from ai_agent import check_idea_with_gigachat,generate_files

load_dotenv()

BOT_TOKEN = os.getenv("DIALOG_BOT_TOKEN")

TEMPLATE_FIELDS = [
    "Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
    "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
    "Достижимый идеал(to-be)", "Масштаб процесса"
]

user_states = {}
agent_query_state = {}

class BotHandler(AbstractHandler):
    def __init__(self, bot):
        self.bot = bot

    def on_message(self, peer, sender, message_text):
        user_id = sender.uid
        msg = message_text.strip()

        if msg == "У меня есть идея!💌":
            user_states[user_id] = {"giga_mode": True}
            self.bot.messaging.send_message(peer, "💬 Опиши свою идею свободно, я проверю её уникальность:")
            return

        if user_id in user_states and user_states[user_id].get("giga_mode"):
            idea_text = msg
            self.bot.messaging.send_message(peer, "🔍 Отправляю идею в Gigachat...")
            result, contact = check_idea_with_gigachat(idea_text)
            self.bot.messaging.send_message(peer, f"🤖 Ответ GigaChat:\n\n{result}")
            return

        if msg == "АИ-агенты?📍":
            self.bot.messaging.send_message(peer, "📋 Что хотите сделать? Напишите: Все агенты или Искать по названию")
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
            self.bot.messaging.send_message(peer, "✉️ Напиши нам в Telegram: @your_support_bot")
            return

        if user_id in user_states:
            state = user_states[user_id]
            step = state.get("step")

            if step is not None and step < len(TEMPLATE_FIELDS):
                field = TEMPLATE_FIELDS[step]
                state["data"][field] = msg
                state["step"] += 1

                if state["step"] < len(TEMPLATE_FIELDS):
                    next_field = TEMPLATE_FIELDS[state["step"]]
                    self.bot.messaging.send_message(peer, f"{state['step'] + 1}⃣ {next_field}:")
                else:
                    self.bot.messaging.send_message(peer, "✅ Формирую файлы...")
                    word_path, excel_path = generate_files(state["data"])

                    with open(word_path, "rb") as doc_file:
                        self.bot.messaging.send_file(peer, doc_file.read(), word_path)
                    with open(excel_path, "rb") as excel_file:
                        self.bot.messaging.send_file(peer, excel_file.read(), excel_path)

                    os.remove(word_path)
                    os.remove(excel_path)
                    user_states.pop(user_id)
                    self.bot.messaging.send_message(peer, "📁 Шаблоны готовы. Выбирай следующее действие:")
                return

        self.bot.messaging.send_message(peer, "🤖 Я вас не понял. Пожалуйста, выбери действие из меню!")


def main():
    bot = DialogBot.get_secure_bot(
        host='your.sber.chat:443',
        token=BOT_TOKEN,
        port=443,
        cert='path_to_cert.pem',  # если нужен SSL
    )
    handler = BotHandler(bot)
    bot.updates.set_update_handler(handler)
    print("✅ Бот запущен")
    while True:
        pass

if __name__ == "__main__":
    main()