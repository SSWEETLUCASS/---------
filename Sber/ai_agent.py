import re
import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from gigachat_wrapper import get_llm

def clean_response_text(response_text: str) -> str:
    # Удаление префикса content='...'
    content_match = re.search(r"content\s*=\s*['\"](.*?)['\"]\s*(,|\}|$)", response_text, re.DOTALL)
    if content_match:
        response_text = content_match.group(1)

    # Удаление экранированных символов \n, \" и двойных слэшей
    response_text = response_text.encode().decode('unicode_escape')

    # Удаление множественных пробелов
    response_text = re.sub(r'\s{2,}', ' ', response_text)

    # Удаление Markdown заголовков, если не нужен markdown
    response_text = re.sub(r'^#+\s*', '', response_text, flags=re.MULTILINE)

    # Удаление маркеров списков (*, -) с пробелом
    response_text = re.sub(r'^[\*\-]\s+', '', response_text, flags=re.MULTILINE)

    # Удаление лишних пустых строк
    response_text = re.sub(r'\n{2,}', '\n\n', response_text.strip())

    return response_text



def check_idea_with_gigachat_local(user_input: str, user_data: dict, is_free_form: bool = False) -> tuple[str, bool, dict, bool]:
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

        joined_data = "\n\n".join(all_agents_data) if all_agents_data else "(список инициатив пуст)"
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке agents.xlsx: {e}")
        joined_data = "(не удалось загрузить данные об инициативах)"

    if is_free_form:
        prompt = f"""
        Инициативы:
        {joined_data}

        1. Проанализируй текст пользователя и собери его по шаблону:
        "Название", 
        "Что хотим улучшить?", 
        "Какие данные поступают агенту на выход?",
        "Как процесс выглядит сейчас? as-is", 
        "Какой результат нужен от агента?",
        "Достижимый идеал(to-be)", 
        "Масштаб процесса"

        Если что-то не указано — скажи об этом прямо.

        Текст пользователя:
        \"\"\"{user_data['Описание в свободной форме']}\"\"\"

        2. Сравни инициативу пользователя с известными инициативами:
        - Если идея похожа — напиши "НЕ уникальна + название и владелец".
        - Если идея новая — напиши "Уникальна" и предложи улучшения.
        - Если текст непонятный — напиши "Извините, но я вас не понимаю".

        3. Если это похоже на идею, но пользователь не указал, что хочет её проверить — предложи ему это сделать.
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

        Инициативы:
        {joined_data}

        1. Сравни инициативу с существующими.
        2. Проверь уникальность: 
        - Если идея похожа — напиши "НЕ уникальна + название и владелец".
        - Если новая — напиши "Уникальна" и предложи улучшения.
        """
    raw_response = get_llm().invoke(prompt)
    response_text = clean_response_text(str(raw_response).strip())

    is_unique = "уникальна" in response_text.lower() and "не уникальна" not in response_text.lower()

    parsed_data = {}
    if is_free_form:
        fields = [
            "Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
            "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
            "Достижимый идеал(to-be)", "Масштаб процесса"
        ]
        for field in fields:
            match = re.search(rf"{field}[:\-–]\s*(.+)", response_text, re.IGNORECASE)
            if match:
                parsed_data[field] = match.group(1).strip()

    suggest_processing = "похоже на идею" in response_text.lower() or "возможно, вы описали идею" in response_text.lower()

    return response_text, is_unique, parsed_data, suggest_processing


def check_general_message_with_gigachat_enhanced(msg: str) -> tuple[str, str]:
    try:
        prompt = f"""
        Пользователь написал:
        \"\"\"{msg}\"\"\"

        Проанализируй сообщение. Ответь двумя строками:
        1. Краткий ответ на сообщение.
        2. Категория действия (одно слово): идея / шаблон / аналитика / агент / не_по_теме

        Примеры:
        • "Похоже, вы описали идею. Хотите её оформить?"\nидея
        • "Вы можете использовать шаблон для инициатив."\nшаблон
        • "Это похоже на аналитический запрос, хотите построить отчёт?"\nаналитика
        • "Это задание для агента. Хотите, я создам помощника?"\nагент
        • "Извините, я помогаю только с инициативами, шаблонами и аналитикой."\nне_по_теме
        """
        raw_response = get_llm().invoke(prompt)
        text = clean_response_text(str(raw_response).strip())

        if "\n" in text:
            reply, intent = text.split("\n", 1)
        else:
            reply, intent = text, "не_по_теме"

        return reply.strip(), intent.strip()
    except Exception as e:
        return f"⚠️ Ошибка при обращении к GigaChat: {e}", "ошибка"


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
