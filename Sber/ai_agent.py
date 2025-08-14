import re
import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
from openpyxl.chart import BarChart, Reference
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import RGBColor
from gigachat_wrapper import get_llm

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import io
from datetime import datetime
import logging
from collections import defaultdict, deque

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("gigachat.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Память для диалогов с пользователями (user_id -> история последних 10 сообщений)
gigachat_memory = defaultdict(lambda: deque(maxlen=10))

def add_to_memory(user_id: int, user_message: str, bot_response: str):
    """Добавляет обмен сообщениями в память пользователя"""
    if user_id:
        gigachat_memory[user_id].append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "user": user_message.strip(),
            "bot": bot_response.strip()
        })

def get_conversation_context(user_id: int) -> str:
    """Получает контекст предыдущих сообщений пользователя"""
    if not user_id or user_id not in gigachat_memory:
        return ""
    
    history = list(gigachat_memory[user_id])
    if not history:
        return ""
    
    # Формируем контекст из последних сообщений
    context_parts = []
    for i, exchange in enumerate(history, 1):
        context_parts.append(f"Сообщение {i}:")
        context_parts.append(f"Пользователь: {exchange['user']}")
        context_parts.append(f"Бот: {exchange['bot']}")
        context_parts.append("")
    
    return "\n".join(context_parts)

def clean_response_text(text: str) -> str:
    """Улучшенная очистка текста ответа от служебных символов и кодировок"""
    # Преобразуем в строку если это не строка
    if not isinstance(text, str):
        text = str(text)
    
    # Убираем все что идет после 'content=' до первой кавычки
    if 'content=' in text:
        match = re.search(r"content=['\"]([^'\"]*)['\"]", text)
        if match:
            text = match.group(1)
        else:
            # Если кавычки не найдены, берем все после content=
            text = re.sub(r".*content=", "", text)
            text = re.sub(r"\s+additional_kwargs=.*$", "", text, flags=re.DOTALL)
    
    # Убираем дополнительные метаданные
    text = re.sub(r"\s*additional_kwargs=.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\s*response_metadata=.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\s*id=.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\s*usage_metadata=.*$", "", text, flags=re.DOTALL)
    
    # Декодируем UTF-8 если нужно
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        
        # Исправляем поврежденную кодировку (как в примере ÐÐ¾ÑÐ¾Ð¶Ðµ)
        # Пробуем декодировать как latin-1 и перекодировать в UTF-8
        try:
            if 'Ð' in text or 'Ñ' in text:
                text = text.encode('latin-1').decode('utf-8')
        except:
            pass
            
    except Exception:
        pass
    
    # Преобразуем литералы \n в настоящие переносы
    text = text.replace('\\n', '\n')
    text = text.replace('\\t', '\t')
    text = text.replace('\\"', '"')
    text = text.replace("\\'", "'")
    
    # Удаляем лишние слеши
    text = re.sub(r'\\(?![nrt"\'])', '', text)
    
    # Очищаем от служебных команд в начале
    text = re.sub(r'^CMD:\w+\s*[•\-]*\s*', '', text)
    
    # Обработка -- и ##
    # Заменяем двойные дефисы на тире (с пробелами по краям)
    text = re.sub(r'\s*--\s*', ' – ', text)
    # Заменяем ## на подзаголовки (убираем символы и делаем новую строку)
    text = re.sub(r'\s*##\s*', '\n\n', text)
    
    # Убираем лишние символы и форматирование
    text = text.strip()
    
    # Убираем множественные переносы строк
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    
    return text

def load_agents_data() -> list[dict]:
    """Загрузка данных об агентах из файла"""
    try:
        wb = load_workbook("agents.xlsx", data_only=True)
        ws = wb.active
        agents_data = []

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[4]:  # Пропускаем пустые строки
                continue
            
            block, ssp, owner, contact, name, short_name, desc, typ = row
            agent_info = {
                "block": block or "",
                "ssp": ssp or "",
                "owner": owner or "",
                "contact": contact or "",
                "name": name or "",
                "short_name": short_name or "",
                "description": desc or "",
                "type": typ or ""
            }
            agents_data.append(agent_info)

        return agents_data
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке agents.xlsx: {e}")
        return []

def check_idea_with_gigachat_local(user_input: str, user_data: dict, is_free_form: bool = False) -> tuple[str, bool, dict, bool]:
    """Проверка идеи с помощью GigaChat"""
    try:
        agents_data = load_agents_data()
        
        if agents_data:
            joined_data = "\n\n".join([
                f"""Блок: {agent['block']}
ССП: {agent['ssp']}
Владелец: {agent['owner']}
Контакт: {agent['contact']}
Название инициативы: {agent['name']}
Краткое название: {agent['short_name']}
Описание: {agent['description']}
Тип: {agent['type']}"""
                for agent in agents_data
            ])
        else:
            joined_data = "(список инициатив пуст)"
            
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке agents.xlsx: {e}")
        joined_data = "(не удалось загрузить данные об инициативах)"

    if is_free_form:
        prompt = f"""
        Существующие инициативы:
        {joined_data}

        1. Проанализируй данный тебе текст пользователя и собери его по шаблону:
        - "Название"
        - "Что хотим улучшить?" 
        - "Какие данные поступают агенту на выход?"
        - "Как процесс выглядит сейчас? as-is"
        - "Какой результат нужен от агента?"
        - "Достижимый идеал(to-be)"
        - "Масштаб процесса"

        Если пользователь что-то не написал, укажи это и предложи уточнить.

        2. Сравни инициативу пользователя с существующими:
        - Если идея похожа на существующую — напиши "НЕ уникальна" и укажи название похожей инициативы и владельца.
        - Если идея новая — напиши "Уникальна" и предложи рекомендации по улучшению.
        - Если текст непонятный — напиши "Извините, не могу понять описание".

        3. Дай конструктивные рекомендации по развитию идеи.

        Отвечай ТОЛЬКО на русском языке, без дополнительной технической информации. и не забудь смайлики.

        Текст пользователя:
        \"\"\"{user_data.get('Описание в свободной форме', '')}\"\"\"
        """
    else:
        user_initiative = "\n".join([f"{key}: {value}" for key, value in user_data.items()])
        
        prompt = f"""
        Инициатива пользователя:
        {user_initiative}

        Существующие инициативы:
        {joined_data}

        Задачи:
        1. Внимательно сравни инициативу пользователя с существующими инициативами.
        
        2. Определи уникальность:
        - Если идея похожа на существующую — напиши "НЕ уникальна" и укажи название похожей инициативы и владельца.
        - Если идея новая — напиши "Уникальна" и предложи рекомендации по улучшению.
        
        3. Дай детальную оценку инициативы и советы по её развитию.

        4. Если идея кажется не ясной или глупой, пишем, как: Извините, но давайте еще подумаем.

        Отвечай ТОЛЬКО на русском языке, без дополнительной технической информации.и не забудь смайлики.
        """

    try:
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")

        response_text = clean_response_text(raw_response)

        # Проверка на "неясную" или "глупую" идею
        unclear_idea = any(
            phrase in response_text.lower()
            for phrase in [
                "Извините",
                "извините",
                "идея кажется не ясной",
                "идея не ясна",
                "идея глупая",
                "не очень хорошая идея"
            ]
        )

        # Если идея неясна — просто возвращаем
        if unclear_idea:
            return response_text, False, {}, False

        # Сохраняем в память для пользователя (если user_id известен)
        user_id = user_data.get("user_id")
        if user_id:
            add_to_memory(user_id, user_input, response_text)

        is_unique = "уникальна" in response_text.lower() and "не уникальна" not in response_text.lower()

        # Парсинг данных из свободной формы
        parsed_data = {}
        if is_free_form:
            fields = [
                "Название", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
                "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
                "Достижимый идеал(to-be)", "Масштаб процесса"
            ]
            for field in fields:
                patterns = [
                    rf"{re.escape(field)}[:\-–]\s*(.+?)(?=\n\w+[:\-–]|$)",
                    rf"{re.escape(field.lower())}[:\-–]\s*(.+?)(?=\n\w+[:\-–]|$)",
                ]
                for pattern in patterns:
                    match = re.search(pattern, response_text, re.IGNORECASE | re.DOTALL)
                    if match:
                        parsed_data[field] = match.group(1).strip()
                        break
            if is_unique and parsed_data:
                try:
                    cost = calculate_work_cost_interactive(parsed_data)
                    response_text += f"\n\n💰 Примерная стоимость работы: {cost:,.0f} ₽"
                except Exception as e:
                    logging.error(f"Ошибка при расчете стоимости: {e}")

        suggest_processing = (
            "похоже на идею" in response_text.lower()
            or "возможно, вы описали идею" in response_text.lower()
        )

        return response_text, is_unique, parsed_data, suggest_processing

    except Exception as e:
        return f"⚠️ Ошибка при обращении к GigaChat: {e}", False, {}, False

def check_general_message_with_gigachat(msg: str, user_id: int = None) -> tuple[str, str | None]:
    """Проверка общего сообщения с помощью GigaChat с учетом истории диалога"""
    try:
        # Получаем контекст предыдущих сообщений
        conversation_context = get_conversation_context(user_id) if user_id else ""
        
        context_section = ""
        if conversation_context:
            context_section = f"""
История нашего диалога:
{conversation_context}

Текущее сообщение пользователя:
"""

        prompt = f"""{context_section}
Пользователь написал:
\"\"\"{msg}\"\"\"

Контекст: Ты - помощник по разработке AI-агентов. Учитывай предыдущие сообщения пользователя для более конструктивного диалога.

Твоя задача — понять смысл сообщения (оно может быть в свободной форме) и определить подходящую команду для бота.

Правила выбора команды:
1. Если это приветствие или начало общения (привет, здравствуй, что умеешь, начнем и т.д.), то возвращай CMD:start

2. Если пользователь описывает идею для AI-агента или при диалоге с развитием идеи говорит, что хочет ее оформить, то возвращай CMD:idea

3. Если пользователь просит придумать или развить идею (помоги с идеей, предложи идею, что можно автоматизировать), то дай предложение по шаблону:
    - "Название"
    - "Что хотим улучшить?" 
    - "Какие данные поступают агенту на выход?"
    - "Как процесс выглядит сейчас? as-is"
    - "Какой результат нужен от агента?"
    - "Достижимый идеал(to-be)"
    - "Масштаб процесса"
    И дай конструктивную оценку идеи.

4. Если пользователь жалуется на проблему с ботом или просит помощь в использовании,то возвращай CMD:help

5. Если хочет список всех AI-агентов,то возвращай CMD:ai_agent

6. Если хочет консультацию (советы, рекомендации, что выбрать или вопрос как создать), то возвращай CMD:consultation

7. Если спрашивает про владельцев или информацию об агенте, то возвращай CMD:search_owners

8. Если ничего не подходит, но есть смысл ответа — дай полезный ответ без команды.

Особенности ответа с учетом контекста:
- Если пользователь уже что-то обсуждал ранее, ссылайся на это
- Если он задает уточняющие вопросы, отвечай в контексте предыдущих тем
- Поддерживай непрерывность диалога
- Если пользователь возвращается к предыдущей теме, напомни ему детали
- Если пользователь попадает на команды с CMD, то формат ответа: [Текст ответа пользователю] [CMD:команда]

Формат ответа:
- Дружелюбный и естественный тон, можно использовать смайлики.

Отвечай ТОЛЬКО на русском языке. Не более 4000 символов.
"""

        
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")

        response = clean_response_text(raw_response)
        
        # Извлекаем команду из ответа
        cmd_match = re.search(r'CMD:(\w+)', response)
        detected_command = cmd_match.group(1) if cmd_match else None
        
        # Убираем команду из текста ответа
        if cmd_match:
            response = re.sub(r'\s*CMD:\w+\s*', '', response).strip()
        
        # Сохраняем в память диалога
        if user_id and response:
            add_to_memory(user_id, msg, response)
        
        return response, detected_command
        
    except Exception as e:
        return f"⚠️ Ошибка при генерации ответа: {e}", None

def find_agent_owners(query: str) -> str:
    """Поиск владельцев агентов по запросу"""
    try:
        agents_data = load_agents_data()
        
        if not agents_data:
            return "⚠️ Файл с агентами пуст или не найден."
        
        # Формируем данные для анализа
        agents_info = "\n\n".join([
            f"Название: {agent['name']}\n"
            f"Описание: {agent['description']}\n"
            f"Тип: {agent['type']}\n"
            f"Блок: {agent['block']}\n"
            f"Владелец: {agent['owner']}\n"
            f"Контакт: {agent['contact']}"
            for agent in agents_data
        ])
        
        prompt = f"""
        Запрос пользователя: "{query}"
        
        Доступные AI-агенты:
        {agents_info}
        
        Найди агента, которые наиболее соответствуют запросу пользователя.
        Учитывай название, описание, тип и область применения.
        
        Для каждого подходящего агента выведи:
        - Название
        - Краткое описание
        - Владелец и контакты
        
        Отвечай ТОЛЬКО на русском языке, без дополнительной технической информации. и не забудь смайлики.
        """
        
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")
        
        response = clean_response_text(raw_response)
        
        return response if response else "🤖 Не удалось найти подходящих агентов по вашему запросу."
        
    except Exception as e:
        return f"⚠️ Ошибка при поиске владельцев: {e}"

def generate_idea_suggestions(user_request: str) -> str:
    """Генерация предложений идей на основе запроса пользователя"""
    try:
        agents_data = load_agents_data()
        
        # Формируем контекст существующих агентов
        existing_agents_context = ""
        if agents_data:
            agent_types = set(agent['type'] for agent in agents_data if agent['type'])
            existing_agents_context = f"Существующие типы агентов: {', '.join(agent_types)}"

        prompt = f"""
        Запрос пользователя: "{user_request}"
        {existing_agents_context}

        Сгенерируй 3-4 конкретные идеи для AI-агентов, которые могли бы помочь пользователю.
        
        Для каждой идеи предложи:
        - Название агента
        - Краткое описание (1-2 предложения)
        - Основные функции
        - Примерные преимущества
        
        Старайся предлагать разнообразные решения и избегай повторения существующих агентов.
        
        Отвечай ТОЛЬКО на русском языке, используй смайлики для наглядности. 
        """
        
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")
        
        response = clean_response_text(raw_response)
        
        return response if response else "💡 Не удалось сгенерировать идеи. Попробуйте переформулировать запрос."
        
    except Exception as e:
        return f"⚠️ Ошибка при генерации идей: {e}"

def generate_agents_summary_file(agents_file_path: str) -> str:
    """Генерация аналитического файла с агентами"""
    try:
        agents_data = load_agents_data()
        
        if not agents_data:
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_file = f"agents_summary_{timestamp}.xlsx"
        
        wb = Workbook()
        
        # Лист 1: Исходные данные с улучшенным форматированием
        ws1 = wb.active
        ws1.title = "Список агентов"
        
        # Заголовки
        headers = ["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"]
        ws1.append(headers)
        
        # Стили для заголовков
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin")
        )
        
        for cell in ws1[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center")
        
        # Добавляем данные
        for agent in agents_data:
            ws1.append([
                agent['block'], agent['ssp'], agent['owner'], agent['contact'],
                agent['name'], agent['short_name'], agent['description'], agent['type']
            ])
        
        # Форматирование данных
        for row in ws1.iter_rows(min_row=2, max_row=ws1.max_row):
            for cell in row:
                cell.border = thin_border
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        
        # Автоширина колонок
        for column in ws1.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws1.column_dimensions[column_letter].width = adjusted_width
        
        # Лист 2: Аналитика
        ws2 = wb.create_sheet("Аналитика")
        
        # Статистика по типам
        type_stats = {}
        block_stats = {}
        
        for agent in agents_data:
            agent_type = agent['type'] or "Не указан"
            agent_block = agent['block'] or "Не указан"
            
            type_stats[agent_type] = type_stats.get(agent_type, 0) + 1
            block_stats[agent_block] = block_stats.get(agent_block, 0) + 1
        
        # Заголовки аналитики
        ws2['A1'] = "Аналитический отчет по AI-агентам"
        ws2['A1'].font = Font(size=16, bold=True)
        ws2['A1'].alignment = Alignment(horizontal="center")
        ws2.merge_cells('A1:D1')
        
        # Общая статистика
        ws2['A3'] = "Общая статистика:"
        ws2['A3'].font = Font(bold=True, size=12)
        ws2['A4'] = f"Всего агентов: {len(agents_data)}"
        ws2['A5'] = f"Уникальных типов: {len(type_stats)}"
        ws2['A6'] = f"Уникальных блоков: {len(block_stats)}"
        
        # Статистика по типам
        ws2['A8'] = "Распределение по типам:"
        ws2['A8'].font = Font(bold=True, size=12)
        row = 9
        for agent_type, count in sorted(type_stats.items(), key=lambda x: x[1], reverse=True):
            ws2[f'A{row}'] = agent_type
            ws2[f'B{row}'] = count
            row += 1
        
        # Статистика по блокам
        ws2['D8'] = "Распределение по блокам:"
        ws2['D8'].font = Font(bold=True, size=12)
        row = 9
        for block, count in sorted(block_stats.items(), key=lambda x: x[1], reverse=True):
            ws2[f'D{row}'] = block
            ws2[f'E{row}'] = count
            row += 1
        
        # Лист 3: Контакты
        ws3 = wb.create_sheet("Контакты владельцев")
        ws3.append(["Владелец", "Контакт", "Количество агентов", "Названия агентов"])
        
        # Группируем по владельцам
        owner_agents = {}
        for agent in agents_data:
            owner = agent['owner'] or "Не указан"
            if owner not in owner_agents:
                owner_agents[owner] = []
            owner_agents[owner].append(agent['name'])
        
        for owner, agent_names in owner_agents.items():
            contact = next((agent['contact'] for agent in agents_data if agent['owner'] == owner), "")
            ws3.append([owner, contact, len(agent_names), "; ".join(agent_names)])
        
        # Форматирование листа контактов
        for cell in ws3[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")
            cell.font = Font(bold=True, color="FFFFFF")
        
        wb.save(summary_file)
        return summary_file
        
    except Exception as e:
        print(f"⚠️ Ошибка при создании аналитического файла: {e}")
        return None

def generate_files(data: dict, cost_info: str = "") -> tuple[str, str]:
    """Генерация Word и Excel файлов с данными инициативы"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    word_path = f"initiative_{timestamp}.docx"
    excel_path = f"initiative_{timestamp}.xlsx"

    # Создание Word документа
    doc = Document()
    
    # Заголовок
    title = doc.add_heading("Описание AI-инициативы", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Дата создания
    date_para = doc.add_paragraph(f"Дата создания: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    date_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_run = date_para.runs[0]
    date_run.font.size = Pt(10)
    date_run.font.color.rgb = RGBColor(128, 128, 128)
    
    doc.add_paragraph()  # Пустая строка
    
    # Основной контент
    for key, value in data.items():
        # Заголовок поля
        heading_para = doc.add_paragraph()
        heading_run = heading_para.add_run(f"📋 {key}")
        heading_run.bold = True
        heading_run.font.size = Pt(14)
        heading_run.font.color.rgb = RGBColor(0, 70, 132)
        
        # Разделительная линия
        line_para = doc.add_paragraph("─" * 50)
        line_run = line_para.runs[0]
        line_run.font.color.rgb = RGBColor(200, 200, 200)
        
        # Содержимое поля
        content_para = doc.add_paragraph(str(value))
        content_run = content_para.runs[0]
        content_run.font.size = Pt(12)
        
        doc.add_paragraph()  # Пустая строка между разделами
    
    # Добавляем информацию о стоимости, если есть
    if cost_info:
        cost_heading = doc.add_heading("💰 Расчет стоимости", level=1)
        cost_para = doc.add_paragraph(cost_info)
        cost_run = cost_para.runs[0]
        cost_run.font.size = Pt(11)
    
    # Футер
    footer_para = doc.add_paragraph()
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer_para.add_run("Создано с помощью Агентолога 🤖")
    footer_run.font.size = Pt(10)
    footer_run.font.color.rgb = RGBColor(128, 128, 128)
    
    doc.save(word_path)

    # Создание Excel файла
    wb = Workbook()
    ws = wb.active
    ws.title = "Инициатива"

    # Стили
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )
    wrap_alignment = Alignment(wrap_text=True, vertical="top")
    
    # Заголовки
    ws.append(["Поле", "Значение"])
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    # Данные
    for key, value in data.items():
        ws.append([key, str(value)])
        for cell in ws[ws.max_row]:
            cell.border = thin_border
            cell.alignment = wrap_alignment
    
    # Добавляем информацию о стоимости в Excel
    if cost_info:
        ws.append(["", ""])  # Пустая строка
        ws.append(["Расчет стоимости", cost_info])
        for cell in ws[ws.max_row]:
            cell.border = thin_border
            cell.alignment = wrap_alignment
    
    # Форматирование колонок
    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 70
    
    # Информационная строка
    ws.append(["", ""])  # Пустая строка
    info_row = ws.max_row + 1
    ws[f"A{info_row}"] = "Создано"
    ws[f"B{info_row}"] = datetime.now().strftime('%d.%m.%Y %H:%M')
    
    for cell in [ws[f"A{info_row}"], ws[f"B{info_row}"]]:
        cell.font = Font(italic=True, color="808080")
        cell.border = thin_border
    
    wb.save(excel_path)

    return word_path, excel_path

def calculate_work_cost(parsed_data: dict, is_unique: bool = True) -> str:
    """
    Расчет примерной стоимости работы по инициативе в чел./час и рублях.
    """
    # Базовые параметры
    hourly_rate = 3500  # ставка в час (рублях)
    base_hours = 40  # базовое количество часов
    
    # Карта масштаба к коэффициенту часов
    scale_map = {
        "малый": 1,
        "мал": 1,
        "небольшой": 1,
        "средний": 1.8,
        "средн": 1.8,  
        "большой": 2.5,
        "больш": 2.5,
        "крупный": 3.2,
        "крупн": 3.2,
        "глобальный": 4,
        "глобальн": 4,
        "масштабный": 4
    }

    # Получаем масштаб из данных
    scale_value = parsed_data.get("Масштаб процесса", "").strip().lower()
    
    # Если это число, используем его напрямую
    if scale_value.replace('.', '').replace(',', '').isdigit():
        hours_coefficient = float(scale_value.replace(',', '.'))
    else:
        # Ищем ключевые слова в описании масштаба
        hours_coefficient = 1.0  # по умолчанию
        for key, value in scale_map.items():
            if key in scale_value:
                hours_coefficient = value
                break
    
    # Дополнительные коэффициенты
    complexity_bonus = 0
    
    # Анализируем сложность по описанию
    description_text = (
        parsed_data.get("Описание", "") + " " +
        parsed_data.get("Как процесс выглядит сейчас? as-is", "") + " " +
        parsed_data.get("Какой результат нужен от агента?", "")
    ).lower()
    
    # Ключевые слова для определения сложности
    complex_keywords = [
        "интеграция", "апи", "api", "машинное обучение", "ml", "ai", 
        "нейронн", "алгоритм", "распознавание", "nlp", "компьютерное зрение",
        "большие данные", "реальное время", "безопасность", "криптография"
    ]
    
    simple_keywords = [
        "простой", "базовый", "стандартн", "типовой", "шаблон"
    ]
    
    for keyword in complex_keywords:
        if keyword in description_text:
            complexity_bonus += 0.3
            
    for keyword in simple_keywords:
        if keyword in description_text:
            complexity_bonus -= 0.2
    
    # Ограничиваем бонус сложности
    complexity_bonus = max(-0.5, min(complexity_bonus, 1.5))
    
    # Если идея не уникальна, снижаем трудозатраты (есть готовые решения для изучения)
    uniqueness_coefficient = 1.0 if is_unique else 0.7
    
    # Итоговый расчет часов
    total_hours = base_hours * hours_coefficient * (1 + complexity_bonus) * uniqueness_coefficient
    total_hours = max(20, total_hours)  # Минимум 20 часов
    
    # Разбивка по этапам (примерное распределение)
    analysis_hours = total_hours * 0.15  # 15% на анализ
    development_hours = total_hours * 0.60  # 60% на разработку
    testing_hours = total_hours * 0.15  # 15% на тестирование
    deployment_hours = total_hours * 0.10  # 10% на внедрение
    
    # Расчет стоимости
    total_cost = total_hours * hourly_rate
    
    # Формируем описание стоимости
    cost_description = f"""
📊 **Детальный расчет стоимости разработки:**

🔢 **Трудозатраты:**
• Анализ и проектирование: {analysis_hours:.0f} ч.
• Разработка и программирование: {development_hours:.0f} ч.
• Тестирование и отладка: {testing_hours:.0f} ч.
• Внедрение и документация: {deployment_hours:.0f} ч.
**Всего часов: {total_hours:.0f} ч.**

💰 **Финансовые расчеты:**
• Ставка разработчика: {hourly_rate:,} ₽/час
• Коэффициент масштаба: {hours_coefficient}x
• Коэффициент сложности: {(1 + complexity_bonus):.2f}x
• Коэффициент уникальности: {uniqueness_coefficient}x
• Уникальность идеи: {'Да' if is_unique else 'Нет (есть аналоги)'}

💸 **ИТОГОВАЯ СТОИМОСТЬ: {total_cost:,.0f} ₽**
💼 **({total_hours:.0f} чел./час)**

📈 **Диапазон стоимости:** {total_cost*0.8:,.0f} - {total_cost*1.3:,.0f} ₽
(в зависимости от детальных требований)

📝 **Примечание:** Стоимость может изменяться в зависимости от:
- Сложности интеграций с существующими системами
- Требований к производительности и масштабируемости  
- Объема тестирования и качества
- Дополнительных функций и требований заказчика
"""
    
    return cost_description


def calculate_work_cost_interactive(answers: dict, return_next=False):
    questions = [
        ("Название", "Как называется ваша инициатива?"),
        ("Что хотим улучшить?", "Что именно вы хотите улучшить с помощью агента?"),
        ("Какие данные поступают агенту на выход?", "Какие данные агент будет выдавать на выходе?"),
        ("Масштаб процесса", "Каков масштаб процесса (малый, средний, большой)?"),
    ]

    # Поиск следующего вопроса
    for key, question in questions:
        if key not in answers or answers[key] is None:
            if return_next:
                return {"question": question, "key": key}
            answers[key] = None

    # Если все ответы есть — считаем стоимость
    cost = calculate_work_cost(answers)
    if return_next:
        return {"done": True, "result": f"Примерная стоимость: {cost:,.0f} ₽"}
    return cost


def generate_cost_questions(parsed_data: dict) -> tuple[str, dict]:
    """Генерирует уточняющие вопросы для точного расчета стоимости"""
    try:
        # Анализируем данные инициативы с помощью GigaChat
        initiative_context = "\n".join([f"{key}: {value}" for key, value in parsed_data.items()])
        
        prompt = f"""
        Проанализируй следующую AI-инициативу и сформируй 7-8 конкретных вопросов для точного расчета стоимости разработки:

        ИНИЦИАТИВА:
        {initiative_context}

        Сформируй вопросы по следующим аспектам:
        1. Команда разработки (сколько человек, какие роли)
        2. Временные рамки (дедлайны, этапы)
        3. Техническая сложность (интеграции, технологии)
        4. Объем данных и нагрузка
        5. Требования к качеству и безопасности
        6. Инфраструктура и развертывание
        7. Сопровождение и поддержка
        8. Дополнительные требования

        ВАЖНО: Каждый вопрос должен быть:
        - Конкретным и понятным
        - С вариантами ответов или единицами измерения
        - Влияющим на итоговую стоимость

        Формат ответа:
        ВОПРОС 1: [текст вопроса]
        Варианты: [варианты ответов]

        ВОПРОС 2: [текст вопроса]
        Варианты: [варианты ответов]

        И так далее...

        Отвечай ТОЛЬКО на русском языке, добавь эмодзи для наглядности.
        """
        
        logging.info(f"[GigaChat Input - Questions] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output - Questions] {raw_response}")
        
        questions_text = clean_response_text(raw_response)
        
        # Парсим вопросы из ответа
        questions_dict = parse_questions_from_text(questions_text)
        
        response_text = f"""
🎯 **Для точного расчета стоимости мне нужно уточнить несколько деталей:**

{questions_text}

📝 **Как отвечать:**
Просто напишите номер вопроса и ваш ответ, например:
"1. 3 человека" или "2. 2 месяца"

Можно отвечать по несколько вопросов сразу или по одному.
        """
        
        return response_text, questions_dict
        
    except Exception as e:
        logging.error(f"Ошибка при генерации вопросов: {e}")
        return f"⚠️ Ошибка при генерации вопросов: {e}", None

def parse_questions_from_text(text: str) -> dict:
    """Парсит вопросы из текста GigaChat в структурированный словарь"""
    questions = {}
    
    # Ищем паттерны вопросов
    question_pattern = r'ВОПРОС\s*(\d+):\s*(.+?)(?=\n|Варианты:|$)'
    variants_pattern = r'Варианты:\s*(.+?)(?=\n\s*ВОПРОС|\n\s*$|$)'
    
    question_matches = re.findall(question_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for match in question_matches:
        question_num = match[0]
        question_text = match[1].strip()
        
        # Ищем варианты для этого вопроса
        question_block = re.search(
            rf'ВОПРОС\s*{question_num}:.*?(?=ВОПРОС\s*\d+:|$)', 
            text, 
            re.DOTALL | re.IGNORECASE
        )
        
        variants = []
        if question_block:
            variants_match = re.search(variants_pattern, question_block.group(), re.DOTALL | re.IGNORECASE)
            if variants_match:
                variants_text = variants_match.group(1).strip()
                variants = [v.strip() for v in variants_text.split(',') if v.strip()]
        
        questions[question_num] = {
            'question': question_text,
            'variants': variants,
            'answered': False,
            'answer': None
        }
    
    return questions

def calculate_final_cost(parsed_data: dict, answers: dict, user_id: int = None) -> tuple[str, dict]:
    """Делает финальный расчет стоимости на основе ответов пользователя"""
    try:
        # Подготавливаем контекст для GigaChat
        initiative_context = "\n".join([f"{key}: {value}" for key, value in parsed_data.items()])
        answers_context = "\n".join([f"Вопрос {k}: {v}" for k, v in answers.items()])
        
        prompt = f"""
        Сделай детальный расчет стоимости разработки AI-агента на основе данных:

        ИНИЦИАТИВА:
        {initiative_context}

        ОТВЕТЫ НА УТОЧНЯЮЩИЕ ВОПРОСЫ:
        {answers_context}

        ЗАДАЧА: Рассчитай реалистичную стоимость с учетом всех факторов:

        1. **Определи состав команды и роли:**
        - Аналитик/Product Owner
        - Backend разработчик
        - Frontend разработчик (если нужен UI)
        - Data Scientist/ML Engineer (если нужно ML)
        - DevOps инженер
        - QA инженер
        - Проект-менеджер

        2. **Рассчитай трудозатраты по этапам:**
        - Анализ и проектирование (% от общего времени)
        - Разработка MVP (% от общего времени) 
        - Тестирование и отладка (% от общего времени)
        - Интеграция и развертывание (% от общего времени)
        - Документация и обучение (% от общего времени)

        3. **Учти дополнительные расходы:**
        - Инфраструктура (серверы, облако)
        - Лицензии на ПО
        - Сторонние API/сервисы
        - Непредвиденные расходы (10-20%)

        4. **Используй реалистичные ставки (₽/час):**
        - Junior: 2000-3000
        - Middle: 3500-5000  
        - Senior: 5500-7500
        - Lead/Architect: 7000-10000

        **ФОРМАТ ОТВЕТА:**

        👥 **СОСТАВ КОМАНДЫ:**
        [Роль] - [количество человек] - [уровень] - [ставка ₽/час]

        ⏱️ **ВРЕМЕННЫЕ ЗАТРАТЫ:**
        [Этап] - [количество часов] - [стоимость ₽]

        💰 **ИТОГОВАЯ СМЕТА:**
        Разработка: [сумма] ₽
        Инфраструктура: [сумма] ₽
        Дополнительные расходы: [сумма] ₽
        **ОБЩАЯ СТОИМОСТЬ: [итоговая сумма] ₽**

        📊 **ВРЕМЕННЫЕ РАМКИ:**
        Общее время: [X] месяцев
        Человеко-часов: [X] часов

        📝 **ОБОСНОВАНИЕ:**
        [Объяснение ключевых факторов, влияющих на стоимость]

        Будь максимально конкретным и реалистичным в расчетах!
        """
        
        logging.info(f"[GigaChat Input - Final Cost] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output - Final Cost] {raw_response}")
        
        cost_calculation = clean_response_text(raw_response)
        
        # Сохраняем расчет в память пользователя
        if user_id:
            add_to_memory(user_id, f"Расчет стоимости для: {parsed_data.get('Название', 'инициативы')}", cost_calculation)
        
        return cost_calculation, None
        
    except Exception as e:
        logging.error(f"Ошибка при финальном расчете: {e}")
        return f"⚠️ Ошибка при расчете стоимости: {e}", None

def process_cost_answers(questions: dict, user_input: str) -> tuple[dict, bool, str]:
    """
    Обрабатывает ответы пользователя на вопросы о стоимости
    
    Returns:
        tuple: (обновленные_вопросы, все_ли_отвечено, статус_сообщение)
    """
    try:
        # Парсим ответы из сообщения пользователя
        answer_pattern = r'(\d+)\.?\s*(.+?)(?=\n\d+\.|\n|$)'
        matches = re.findall(answer_pattern, user_input, re.MULTILINE)
        
        answered_count = 0
        total_questions = len(questions)
        
        for match in matches:
            question_num = match[0]
            answer = match[1].strip()
            
            if question_num in questions:
                questions[question_num]['answered'] = True
                questions[question_num]['answer'] = answer
                answered_count += 1
        
        # Проверяем, все ли вопросы отвечены
        all_answered = all(q['answered'] for q in questions.values())
        
        if answered_count == 0:
            status_msg = "❌ Не удалось распознать ответы. Используйте формат: '1. ваш ответ'"
        elif all_answered:
            status_msg = f"✅ Все {total_questions} вопросов отвечены! Делаю расчет..."
        else:
            answered_nums = [k for k, v in questions.items() if v['answered']]
            unanswered_nums = [k for k, v in questions.items() if not v['answered']]
            status_msg = f"📝 Получил ответы на вопросы: {', '.join(answered_nums)}\n" \
                        f"🔄 Остались вопросы: {', '.join(unanswered_nums)}\n\n" \
                        f"Можете продолжить отвечать или написать 'рассчитать' для расчета с текущими данными."
        
        return questions, all_answered, status_msg
        
    except Exception as e:
        logging.error(f"Ошибка при обработке ответов: {e}")
        return questions, False, f"⚠️ Ошибка при обработке ответов: {e}"

# Дополнительная функция для работы с интерактивным расчетом в основном боте
def handle_cost_calculation_flow(user_input: str, user_data: dict, user_id: int = None) -> tuple[str, dict]:
    """
    Обрабатывает весь флоу интерактивного расчета стоимости
    
    Args:
        user_input: Сообщение пользователя
        user_data: Данные об инициативе
        user_id: ID пользователя
        
    Returns:
        tuple: (ответ_пользователю, состояние_расчета)
    """
    
    # Состояние расчета можно хранить в памяти пользователя или передавать отдельно
    # Здесь упрощенная версия - предполагаем, что состояние передается в user_data
    
    cost_state = user_data.get('cost_calculation_state', {})
    
    # Если это первый запрос на расчет
    if not cost_state:
        response, questions = calculate_work_cost_interactive(user_data, user_id)
        cost_state = {
            'stage': 'questions',
            'questions': questions,
            'start_time': datetime.now().isoformat()
        }
        return response, cost_state
    
    # Если пользователь отвечает на вопросы
    if cost_state.get('stage') == 'questions':
        questions = cost_state.get('questions', {})
        
        # Проверяем, хочет ли пользователь принудительно рассчитать
        if 'рассчитать' in user_input.lower() or 'посчитать' in user_input.lower():
            # Собираем уже данные ответы
            answers = {k: v['answer'] for k, v in questions.items() if v['answered']}
            if answers:
                final_cost, _ = calculate_final_cost(user_data, answers, user_id)
                cost_state = {'stage': 'completed'}
                return final_cost, cost_state
            else:
                return "❌ Нет ни одного ответа для расчета. Пожалуйста, ответьте хотя бы на несколько вопросов.", cost_state
        
        # Обрабатываем ответы
        updated_questions, all_answered, status_msg = process_cost_answers(questions, user_input)
        cost_state['questions'] = updated_questions
        
        if all_answered:
            # Все ответы получены, делаем финальный расчет
            answers = {k: v['answer'] for k, v in updated_questions.items()}
            final_cost, _ = calculate_final_cost(user_data, answers, user_id)
            cost_state = {'stage': 'completed'}
            return final_cost, cost_state
        else:
            return status_msg, cost_state
    
    # Если расчет уже завершен
    if cost_state.get('stage') == 'completed':
        return "✅ Расчет стоимости уже завершен. Если нужен новый расчет, создайте новую инициативу.", cost_state
    
    return "⚠️ Неизвестное состояние расчета.", cost_state

# Функции для внутренней работы с памятью (не показываем пользователю)
def _get_memory_summary(user_id: int) -> str:
    """Внутренняя функция для получения сводки по памяти пользователя"""
    if not user_id or user_id not in gigachat_memory:
        return "Память пуста"
    
    history = list(gigachat_memory[user_id])
    if not history:
        return "История диалога пуста"
    
    return f"В памяти {len(history)} обменов сообщениями. Последнее: {history[-1]['timestamp']}"

def _clear_user_memory(user_id: int) -> bool:
    """Внутренняя функция для очистки памяти пользователя"""
    if user_id in gigachat_memory:
        gigachat_memory[user_id].clear()
        return True
    return False

def generate_idea_evaluation_diagram(idea_data: dict, is_unique: bool, parsed_data: dict = None) -> str:
    """
    Генерация паутинчатой диаграммы оценки идеи
    Возвращает путь к сохраненному изображению
    """
    try:
        from gigachat_wrapper import get_llm

        # Подготавливаем текст для анализа
        analysis_text = "\n".join([f"{k}: {v}" for k, v in (parsed_data or idea_data).items()])

        # Промпт для оценки
        evaluation_prompt = f"""
        Проанализируй следующую идею AI-агента и оцени её по 6 критериям от 1 до 10:

        Идея:
        {analysis_text}

        Критерии оценки:
        1. Актуальность (насколько проблема востребована сейчас)
        2. Сложность реализации (10 - очень сложно, 1 - очень просто)
        3. ROI потенциал (возврат инвестиций, экономический эффект)
        4. Инновационность (насколько идея новаторская)
        5. Масштабируемость (возможность расширения и тиражирования)
        6. Техническая осуществимость (реально ли это сделать с текущими технологиями)

        Отвечай СТРОГО в формате:
        Актуальность: X
        Сложность: X
        ROI: X
        Инновационность: X
        Масштабируемость: X
        Осуществимость: X
        """
        # Получаем оценки
        raw_response = get_llm().invoke(evaluation_prompt)
        evaluation_text = clean_response_text(raw_response)

        # Парсим
        criteria = {
            'Актуальность': 7,
            'Сложность': 6,
            'ROI': 6,
            'Инновационность': 5,
            'Масштабируемость': 6,
            'Осуществимость': 7
        }
        scores = {}
        for key in criteria.keys():
            match = re.search(rf"{key}[:\-–]\s*(\d+)", evaluation_text, re.IGNORECASE)
            scores[key] = min(max(int(match.group(1)), 1), 10) if match else criteria[key]

        # Настройка шрифтов для кириллицы
        plt.rcParams['font.family'] = ['DejaVu Sans', 'Arial', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False

        # === Построение паутинки ===
        categories = list(scores.keys())
        values = list(scores.values())
        values += values[:1]  # замкнуть график

        angles = [n / float(len(categories)) * 2 * np.pi for n in range(len(categories))]
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        fig.suptitle(f'📊 Оценка AI-инициативы: {parsed_data.get("Название", "Новая идея")}', 
                     fontsize=16, fontweight='bold', y=0.98)

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)

        ax.plot(angles, values, 'o-', linewidth=2, label='Оценка', color='#2E86C1')
        ax.fill(angles, values, alpha=0.25, color='#2E86C1')

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=10)
        ax.set_ylim(0, 10)
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_yticklabels(['2', '4', '6', '8', '10'], fontsize=8)
        ax.grid(True)

        # Средняя оценка и статус
        avg_score = sum(scores.values()) / len(scores)
        if avg_score >= 7:
            status = "🟢 РЕКОМЕНДУЕТСЯ"
            status_color = '#27AE60'
        elif avg_score >= 5:
            status = "🟡 ДОРАБОТАТЬ"
            status_color = '#F39C12'
        else:
            status = "🔴 РИСКИ"
            status_color = '#E74C3C'

        uniqueness_text = "✅ Уникальная" if is_unique else "⚠️ Есть аналоги"
        info_text = f"Общая: {avg_score:.1f}/10  •  {status}  •  {uniqueness_text}"

        fig.text(0.5, 0.05, info_text, ha='center', fontsize=11,
                 bbox=dict(boxstyle="round,pad=0.5", facecolor=status_color, alpha=0.2))

        # Сохранение
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"idea_radar_{timestamp}.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()

        return filename

    except Exception as e:
        logging.error(f"⚠️ Ошибка при создании диаграммы: {e}")
        return None
