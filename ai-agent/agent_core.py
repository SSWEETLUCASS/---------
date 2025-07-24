import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from gigachat_wrapper import get_llm
import re

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

        joined_data = "\n\n".join(all_agents_data) if all_agents_data else "(список инициатив пуст)"
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке agents.xlsx: {e}")
        joined_data = "(не удалось загрузить данные об инициативах)"

    if is_free_form:
        prompt = f"""
Инициативы:
{joined_data}

1. Проанализируй данный тебе текст и собери его по шаблону:
"Название", 
"Что хотим улучшить?", 
"Какие данные поступают агенту на выход?",
"Как процесс выглядит сейчас? as-is", 
"Какой результат нужен от агента?",
"Достижимый идеал(to-be)", 
"Масштаб процесса"

Если пользователь что-то не написал, скажи об этом прямо.

Текст пользователя:
\"\"\"{user_data['Описание в свободной форме']}`\"\"\"

2. Сравни инициативу пользователя с известными инициативами:
- Если идея похожа — напиши "НЕ уникальна + название и владелец".
- Если идея новая — напиши "Уникальна" и предложи улучшения.
- Если текст непонятный — напиши "Извините, но я вас не понимаю".
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

Сравни инициативу с существующими.
"""

    raw_response = get_llm().invoke(prompt)
    response_text = str(raw_response).strip()

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


if __name__ == "__main__":
    while True:
        print("\nВведите данные инициативы (или 'выход'):")
        title = input("Название инициативы: ").strip()
        if title.lower() in ("выход", "exit", "quit"):
            break

        choice = input("❓Заполнить по шаблону или описать в свободной форме? (шаблон / свободно): ").strip().lower()

        if choice.startswith("шаб"):
            user_data = {
                "Название инициативы": title,
                "Что хотим улучшить?": input("Что хотим улучшить?: ").strip(),
                "Какие данные поступают агенту на выход?": input("Какие данные поступают агенту на выход?: ").strip(),
                "Как процесс выглядит сейчас? as-is": input("Как процесс выглядит сейчас? as-is: ").strip(),
                "Какой результат нужен от агента?": input("Какой результат нужен от агента?: ").strip(),
                "Достижимый идеал(to-be)": input("Достижимый идеал(to-be): ").strip(),
                "Масштаб процесса": input("Масштаб процесса: ").strip()
            }

            print("\n🔍 Проверка уникальности через GigaChat...")
            result, is_unique, parsed_data = check_idea_with_gigachat_local(title, user_data)

        else:
            free_text = input("📝 Опишите инициативу в свободной форме: ").strip()
            user_data = {"Описание в свободной форме": free_text}

            print("\n🔍 Проверка и структурирование через GigaChat...")
            result, is_unique, parsed_data = check_idea_with_gigachat_local(title, user_data, is_free_form=True)

        print("\n🧠 Ответ GigaChat:")
        match = re.search(r"content\s*=\s*['\"](.+?)['\"]", result)
        if match:
            print(match.group(1))
        else:
            print(result)

        if is_unique:
            print("\n✅ Идея уникальна!")

            if parsed_data:
                choice = input("📄 Сгенерировать шаблоны документов на основе распознанной информации? (да/нет): ").strip().lower()
                if choice in ("да", "д", "yes", "y"):
                    word_path, excel_path = generate_files(parsed_data)
                    print(f"\n📄 Файлы созданы:\n - {word_path}\n - {excel_path}")
                else:
                    print("🚫 Генерация отменена.")
            else:
                print("⚠️ Не удалось автоматически разобрать текст. Шаблоны не созданы.")

        else:
            print("\n⚠️ Идея не уникальна или неполна.")
