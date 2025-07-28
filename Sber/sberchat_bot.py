import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, CommandHandler, MessageHandler, MessageContentType
from gigachat_wrapper import get_llm

# 🔐 Настройка SSL-пути (обязательно для SberChat)
os.environ["REQUESTS_CA_BUNDLE"] = '/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/SberCA.pem'
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = '/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/russiantrustedca.pem'

TEMPLATE_FIELDS = [
    "Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
    "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
    "Достижимый идеал(to-be)", "Масштаб процесса"
]


def retrieve_similar_ideas(user_input: str, agents_data: list[str], threshold: float = 0.3) -> list[str]:
    similar = []
    for idea in agents_data:
        ratio = SequenceMatcher(None, user_input.lower(), idea.lower()).ratio()
        if ratio > threshold:
            similar.append(idea)
    return similar


def check_idea_with_gigachat_local(user_input: str, user_data: dict, is_free_form: bool = False) -> tuple[str, bool, dict]:
    try:
        wb = load_workbook("agents.xlsx", data_only=True)
        ws = wb.active
        all_agents_data = []

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[4]:
                continue

            block, ssp, owner, contact, name, short_name, desc, typ = row
            full_info = f"""Блок: {block}
ССП: {ssp}
Владелец: {owner}
Контакт: {contact}
Название инициативы: {name}
Краткое название: {short_name}
Описание: {desc}
Тип: {typ}"""
            all_agents_data.append(full_info)

    except Exception as e:
        print(f"⚠️ Ошибка при загрузке agents.xlsx: {e}")
        all_agents_data = []

    rag_context = retrieve_similar_ideas(user_input, all_agents_data)
    rag_context_text = "\n\n".join(rag_context) if rag_context else "Ничего похожего не найдено."

    if is_free_form:
        prompt = f"""
Вот список похожих инициатив (RAG):
{rag_context_text}

1. Проанализируй текст и заполни шаблон:
"Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
"Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
"Достижимый идеал(to-be)", "Масштаб процесса"

Если что-то не указано — скажи об этом.

Текст пользователя:
\"\"\"{user_data['Описание в свободной форме']}`\"\"\" 

2. Сравни инициативу с найденными:
- Если идея похожа — "НЕ уникальна + название и владелец"
- Если новая — "Уникальна", предложи улучшения
- Если непонятно — "Извините, но я вас не понимаю"
"""
    else:
        prompt = f"""
Вот инициатива от пользователя:
Название: {user_data['Название инициативы']}
Что хотим улучшить?: {user_data['Что хотим улучшить?']}
Какие данные поступают агенту на выход?: {user_data['Какие данные поступают агенту на выход?']}
Как процесс выглядит сейчас? as-is: {user_data['Как процесс выглядит сейчас? as-is']}
Какой результат нужен от агента?: {user_data['Какой результат нужен от агента?']}
Достижимый идеал(to-be): {user_data['Достижимый идеал(to-be)']}
Масштаб процесса: {user_data['Масштаб процесса']}

Похожие инициативы (RAG):
{rag_context_text}

Сравни инициативу с ними и прими решение: уникальна или нет?
"""

    raw_response = get_llm().invoke(prompt)
    response_text = str(raw_response).strip()

    is_unique = "уникальна" in response_text.lower() and "не уникальна" not in response_text.lower()

    parsed_data = {}
    if is_free_form:
        for field in TEMPLATE_FIELDS:
            match = re.search(rf"{field}[:\-–]\s*(.+)", response_text, re.IGNORECASE)
            if match:
                parsed_data[field] = match.group(1).strip()

    return response_text, is_unique, parsed_data


def generate_files(data: dict):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    word_path = f"initiative_{timestamp}.docx"
    excel_path = f"initiative_{timestamp}.xlsx"

    doc = Document()
    title = doc.add_heading("Инициатива — шаблон", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for key, value in data.items():
        p = doc.add_paragraph()
        run = p.add_run(f"{key}:\n")
        run.bold = True
        run.font.size = Pt(14)
        run2 = p.add_run(f"{value}\n")
        run2.font.size = Pt(12)
        p.space_after = Pt(12)

    doc.save(word_path)

    wb = Workbook()
    ws = wb.active
    ws.title = "Инициатива"

    bold_font = Font(bold=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )
    alignment = Alignment(wrap_text=True, vertical="top")

    ws.append(["Поле", "Значение"])
    for cell in ws[1]:
        cell.font = bold_font
        cell.border = thin_border
        cell.alignment = alignment

    for key, value in data.items():
        ws.append([key, value])
        for cell in ws[ws.max_row]:
            cell.border = thin_border
            cell.alignment = alignment

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 60
    wb.save(excel_path)

    return word_path, excel_path


# 🧠 Эхо и старт-команда
def text(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, f'Reply to: {message.message.text_message.text}')


def start(message: UpdateMessage) -> None:
    bot.messaging.send_message(message.peer, 'Я простой эхо-бот. Готов помочь с инициативами!')


# 🚀 Запуск бота
if __name__ == '__main__':
    bot = DialogBot.create_bot({
        "endpoint": "epbotsift.sberchat.sberbank.ru",
        "token": "58068397c86a2b216dadeb7d967965328b95278e",
        "is_secure": True,
    })

    # Подключаем обработчики команд и сообщений
    bot.messaging.command_handler([CommandHandler(start, "start", description="Расскажу о себе")])
    bot.messaging.message_handler([MessageHandler(text, MessageContentType.TEXT_MESSAGE)])

    # Стартуем цикл получения сообщений
    bot.updates.on_updates(do_read_message=True, do_register_commands=True)
    print("✅ Бот запущен и ждёт сообщений.")
