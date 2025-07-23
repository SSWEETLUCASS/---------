import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from gigachat_wrapper import check_idea_with_gigachat

def check_idea_with_gigachat_local(user_input: str) -> tuple[str, str]:
    try:
        wb = load_workbook("agents.xlsx")
        ws = wb.active
        all_agents_data = []
        contact = None
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0]:
                continue
            name, team, contact_cell, desc = row
            full_info = f"Название: {name}, Команда: {team}, Контакт: {contact_cell}, Описание: {desc}"
            all_agents_data.append(full_info)
            if name and user_input.lower() in name.lower():
                contact = contact_cell
        joined_data = "\n".join(all_agents_data)
    except Exception as e:
        joined_data = "(не удалось загрузить данные об агентах)"
        contact = None

    summary = check_idea_with_gigachat(user_input, joined_data)
    return summary, contact

def generate_files(data: dict):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    word_path = f"agent_{timestamp}.docx"
    excel_path = f"agent_{timestamp}.xlsx"

    doc = Document()
    title = doc.add_heading("AI-агент — шаблон", 0)
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
    ws.title = "Агент"

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
        idea = input("Введите идею агента (или 'выход'): ").strip()
        if idea.lower() in ("выход", "exit", "quit"):
            break

        print("Проверка идеи через GigaChat...")
        result, contact = check_idea_with_gigachat_local(idea)

        print("\n🧠 Ответ GigaChat:")
        print(result)

        if contact:
            print(f"\n📞 Контакт найден: {contact}")

        create_files = input("\nСохранить идею в шаблон (Word/Excel)? (y/n): ").lower()
        if create_files == 'y':
            data = {
                "Название": idea,
                "Описание": result,
                "Контакт лидера": contact or "не найден",
            }
            word_path, excel_path = generate_files(data)
            print(f"\n✅ Файлы сохранены:\n - {word_path}\n - {excel_path}")
