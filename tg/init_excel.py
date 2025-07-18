from openpyxl import Workbook
from datetime import datetime

def generate_initiatives_excel(initiatives):
    """
    Генерация Excel-файла с инициативами.

    :param initiatives: Список словарей с полями:
                        'Название', 'Команда', 'Контакт', 'Описание'
    :return: Путь к созданному Excel-файлу
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"initiatives_{timestamp}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Инициативы"

    # Заголовки таблицы
    ws.append(["Название", "Команда разработки", "Контакт лидера", "Суть агента"])

    # Заполнение таблицы
    for item in initiatives:
        ws.append([
            item.get("Название", ""),
            item.get("Команда", ""),
            item.get("Контакт", ""),
            item.get("Описание", "")
        ])

    wb.save(filename)
    return filename
