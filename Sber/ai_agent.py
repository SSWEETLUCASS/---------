import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from gigachat_wrapper import get_llm

def check_idea_with_gigachat(user_input: str, user_data: dict) -> tuple[str, bool]:
    try:
        wb = load_workbook("agents.xlsm", data_only=True)
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
        print(f"⚠️ Ошибка при загрузке agents.xlsm: {e}")
        joined_data = "(не удалось загрузить данные об инициативах)"

    prompt = f"""
    Вот инициатива от пользователя:
    Название: {user_data['Название инициативы']}
    Краткое название: {user_data['Краткое название']}
    Описание: {user_data['Описание инициативы']}
    Тип: {user_data['Тип инициативы']}

    Инициативы:
    {joined_data}

    Сравни инициативу пользователя с известными инициативами и ответь:
    - Если идея похожа — напиши "НЕ уникальна + название похожей и владелец".
    - Если новая — напиши "Уникальна" и предложи улучшения.
    - Если текст неразборчив — напиши "Извините, не понимаю".
    """

    raw_response = get_llm().invoke(prompt)
    response_text = str(raw_response).strip()
    is_unique = "уникальна" in response_text.lower() and "не уникальна" not in response_text.lower()
    return response_text, is_unique

def generate_files(data: dict):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    word_path = f"initiative_{timestamp}.docx"
    excel_path = f"initiative_{timestamp}.xlsx"

    doc = Document()
    doc.add_heading("Инициатива — шаблон", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    for key, value in data.items():
        p = doc.add_paragraph()
        p.add_run(f"{key}:\n").bold = True
        p.add_run(f"{value}\n").font.size = Pt(12)
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
