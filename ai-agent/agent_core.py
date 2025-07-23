import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from gigachat_wrapper import get_llm
import re

def check_idea_with_gigachat_local(user_input: str, user_data: dict) -> tuple[str, bool]:
    try:
        wb = load_workbook("agents.xlsm", data_only=True)
        ws = wb.active
        all_agents_data = []

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[4]:  # Проверка на пустые строки
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

        if not all_agents_data:
            joined_data = "(список инициатив пуст)"
        else:
            joined_data = "\n\n".join(all_agents_data)

    except Exception as e:
        print(f"⚠️ Ошибка при загрузке agents.xlsm: {e}")
        joined_data = "(не удалось загрузить данные об инициативах)"

    print("\n📋 Загружено инициатив для сравнения:", len(all_agents_data))

    prompt = f"""
    Вот инициатива от пользователя:
    Название: {user_data['Название инициативы']}
    Краткое название: {user_data['Краткое название']}
    Описание: {user_data['Описание инициативы']}
    Тип: {user_data['Тип инициативы']}

    Инициативы:
    {joined_data}

    Сравни инициативу пользователя с известными инициативами в таблице и ответь:
    - Если идея похожа на существующие — напиши "НЕ уникальна + название похожей инцииативы и ее владельца,данные берем из таблицы".
    - Если идея действительно новая — напиши "Уникальна" и предложи улучшения по ней.
    - Если я пишу неразребериху - напиши "Извините, но я вас не понимаю".

    """

    raw_response = get_llm().invoke(prompt)

    response_text = str(raw_response).strip().lower()

    is_unique = "уникальна" in response_text and "не уникальна" not in response_text

    return response_text, is_unique

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


if __name__ == "__main__":
    while True:
        print("\nВведите данные инициативы (или 'выход'):")
        title = input("Название инициативы: ").strip()
        if title.lower() in ("выход", "exit", "quit"):
            break

        short = input("Краткое название: ").strip()
        desc = input("Описание инициативы: ").strip()
        type_ = input("Тип инициативы: ").strip()

        user_data = {
            "Название инициативы": title,
            "Краткое название": short,
            "Описание инициативы": desc,
            "Тип инициативы": type_,
        }

        print("\n🔍 Проверка уникальности через GigaChat...")
        result, is_unique = check_idea_with_gigachat_local(title, user_data)

        print("\n🧠 Ответ GigaChat:")

        # Попытка вытащить содержимое content='...'
        match = re.search(r"content\s*=\s*['\"](.+?)['\"]", result)
        if match:
            print(match.group(1))
        else:
            print(result)

        if is_unique:
            print("\n✅ Идея уникальна!")

            choice = input("❓ Хотите сгенерировать шаблоны документов? (да/нет): ").strip().lower()
            if choice in ("да", "д", "y", "yes"):
                print("📦 Генерация файлов...")
                word_path, excel_path = generate_files(user_data)
                print(f"\n📄 Файлы созданы:\n - {word_path}\n - {excel_path}")
            else:
                print("🚫 Генерация шаблонов отменена пользователем.")
        else:
            print("\n⚠️ Идея не является уникальной. Шаблоны не созданы.")