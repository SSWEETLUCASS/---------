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

import logging
import json
from collections import defaultdict, deque
import matplotlib.pyplot as plt
import numpy as np

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("gigachat.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

gigachat_memory = defaultdict(lambda: deque(maxlen=10))  # user_id -> deque([...])

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
    
    # Убираем служебные JSON команды
    text = re.sub(r'ACTION:\s*\{[^}]+\}', '', text)
    
    # Декодируем UTF-8 если нужно
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        
        # Исправляем поврежденную кодировку (как в примере ÐÐ¾ÑÐ¾Ð¶Ðµ)
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
    
    # Обработка -- и ##
    text = re.sub(r'\s*--\s*', ' – ', text)
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

def create_agent_utility_chart(agents_data: list[dict]) -> str:
    """Создание диаграммы полезности агентов"""
    try:
        if not agents_data:
            return None
            
        # Анализируем агентов с помощью GigaChat
        prompt = f"""
        Проанализируй следующих AI-агентов и оцени их по критериям полезности от 1 до 10:

        {chr(10).join([f"- {agent['name']}: {agent['description']}" for agent in agents_data[:10]])}
        
        Для каждого агента дай оценку по критериям:
        1. Экономия времени (1-10)
        2. Качество результата (1-10)  
        3. Простота внедрения (1-10)
        4. Масштабируемость (1-10)
        5. ROI потенциал (1-10)
        
        Ответь СТРОГО в формате:
        Название агента|оценка1|оценка2|оценка3|оценка4|оценка5
        
        Например:
        Агент документооборота|8|7|6|9|8
        """
        
        logging.info(f"[GigaChat Chart Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Chart Output] {raw_response}")
        
        response = clean_response_text(raw_response)
        
        # Парсим ответ
        agent_ratings = {}
        lines = response.split('\n')
        
        for line in lines:
            if '|' in line and line.count('|') >= 5:
                parts = line.split('|')
                if len(parts) >= 6:
                    name = parts[0].strip()
                    try:
                        ratings = [int(parts[i].strip()) for i in range(1, 6)]
                        agent_ratings[name] = ratings
                    except ValueError:
                        continue
        
        if not agent_ratings:
            # Fallback - создаем рандомные оценки для демонстрации
            for agent in agents_data[:5]:
                agent_ratings[agent['name']] = [
                    np.random.randint(6, 10),  # Экономия времени
                    np.random.randint(6, 9),   # Качество результата
                    np.random.randint(4, 8),   # Простота внедрения
                    np.random.randint(5, 9),   # Масштабируемость
                    np.random.randint(6, 10)   # ROI потенциал
                ]
        
        # Создаем диаграмму
        fig, ax = plt.subplots(figsize=(14, 8))
        
        criteria = ['Экономия\nвремени', 'Качество\nрезультата', 'Простота\nвнедрения', 
                   'Масштаби-\nруемость', 'ROI\nпотенциал']
        
        # Цвета для каждого критерия
        colors = ['#2E8B57', '#4169E1', '#FF6347', '#32CD32', '#FF8C00']
        
        x = np.arange(len(criteria))
        width = 0.15
        
        agents_list = list(agent_ratings.items())[:5]  # Топ 5 агентов
        
        for i, (agent_name, ratings) in enumerate(agents_list):
            offset = width * (i - len(agents_list)/2 + 0.5)
            bars = ax.bar(x + offset, ratings, width, 
                         label=agent_name[:20] + ('...' if len(agent_name) > 20 else ''),
                         alpha=0.8)
            
            # Добавляем значения на столбцы
            for j, bar in enumerate(bars):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{ratings[j]}', ha='center', va='bottom', fontsize=9, fontweight='bold')
        
        ax.set_xlabel('Критерии оценки', fontsize=12, fontweight='bold')
        ax.set_ylabel('Оценка (1-10)', fontsize=12, fontweight='bold')
        ax.set_title('Сравнительная оценка полезности AI-агентов', fontsize=14, fontweight='bold', pad=20)
        ax.set_xticks(x)
        ax.set_xticklabels(criteria)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.set_ylim(0, 11)
        ax.grid(True, alpha=0.3)
        
        # Улучшаем внешний вид
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        plt.tight_layout()
        
        # Сохраняем диаграмму
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chart_path = f"agent_utility_chart_{timestamp}.png"
        plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        return chart_path
        
    except Exception as e:
        logging.error(f"Ошибка при создании диаграммы: {e}")
        return None

def check_general_message_with_gigachat(msg: str, user_id: int = None) -> tuple[str, str | None, dict | None]:
    """
    Проверка общего сообщения с помощью GigaChat для естественного диалога.
    Возвращает: (ответ_для_пользователя, предложенное_действие, контекст_данные)
    """
    try:
        # Получаем историю предыдущих сообщений пользователя для контекста
        user_history = ""
        if user_id and user_id in gigachat_memory:
            recent_messages = list(gigachat_memory[user_id])[-3:]  # Последние 3 сообщения
            if recent_messages:
                user_history = "Контекст предыдущих сообщений:\n" + "\n".join([
                    f"Пользователь: {msg_data['input'][:100]}...\nОтвет: {msg_data['output'][:100]}..." 
                    for msg_data in recent_messages
                ]) + "\n\n"

        prompt = f"""
        {user_history}Текущее сообщение пользователя:
        \"\"\"{msg}\"\"\"

        Ты - дружелюбный помощник по AI-агентам. Веди естественный диалог с пользователем.

        ВАЖНО: В конце каждого ответа, если видишь возможность помочь конкретным действием, добавляй JSON-команду в формате:
        ACTION: {{"action": "название_действия", "context": {{"ключ": "значение"}}}}

        Доступные действия:
        1. show_agents - показать список агентов (когда просят показать/посмотреть агентов)
        2. process_idea_template - заполнить идею по шаблону (когда хотят структурированно оформить идею)
        3. process_idea_free - обработать идею свободно (когда уже описали идею)
        4. search_owners - найти владельцев (когда ищут кого-то конкретного)
        5. generate_ideas - сгенерировать идеи (когда просят предложить идеи)
        6. consultation - консультация и ссылки (когда нужна консультация)

        Примеры диалогов:

        Пользователь: "Привет!"
        Ответ: "Привет! 👋 Я Агентолог, помогаю с AI-агентами. Расскажите, чем могу быть полезен? Может быть, у вас есть идея для автоматизации или хотите посмотреть, какие агенты уже существуют?"

        Пользователь: "У меня есть идея!"
        Ответ: "Отлично! 🌟 Идеи - это здорово! Расскажите о ней подробнее. Хотите описать свободно, или лучше заполним структурированный шаблон по пунктам? ACTION: {{"action": "process_idea_template", "context": {{}}}}"

        Пользователь: "Хочу посмотреть что у вас есть"
        Ответ: "Конечно! 📋 Сейчас покажу весь список наших AI-агентов и аналитику по ним. ACTION: {{"action": "show_agents", "context": {{}}}}"

        Пользователь: "Кто занимается аналитикой?"
        Ответ: "🔍 Отлично, найду кто из владельцев агентов занимается аналитикой! ACTION: {{"action": "search_owners", "context": {{"search_query": "аналитика"}}}}"

        Пользователь: "У нас процесс закупок долгий и неэффективный, хочется автоматизировать"
        Ответ: "Понимаю! 🤔 Процесс закупок действительно часто можно значительно оптимизировать с помощью AI. Давайте проанализируем вашу идею! ACTION: {{"action": "process_idea_free", "context": {{"idea_text": "автоматизация процесса закупок"}}}}"

        Правила:
        - Веди дружелюбный диалог
        - Используй эмодзи
        - Предлагай конкретную помощь
        - Не дублируй команды без необходимости
        - Если действие не нужно, не добавляй ACTION
        - Понимай намерения по смыслу, а не только по ключевым словам

        Отвечай естественно, как консультант-человек!
        """

        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")

        response = clean_response_text(raw_response)

        # Сохраняем в память для пользователя
        if user_id:
            gigachat_memory[user_id].append({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "input": msg.strip(),
                "output": response.strip()
            })

        # Извлекаем ACTION если есть
        action_match = re.search(r'ACTION:\s*(\{[^}]+\})', response)
        suggested_action = None
        context_data = None
        
        if action_match:
            try:
                action_json = json.loads(action_match.group(1))
                suggested_action = action_json.get("action")
                context_data = action_json.get("context", {})
                # Убираем ACTION из текста ответа
                response = re.sub(r'\s*ACTION:\s*\{[^}]+\}', '', response).strip()
            except json.JSONDecodeError:
                logging.warning("Не удалось распарсить ACTION JSON")
        
        return response, suggested_action, context_data

    except Exception as e:
        return f"⚠️ Ошибка при обращении к GigaChat: {e}", None, None

def check_idea_with_gigachat_local(user_input: str, user_data: dict, is_free_form: bool = False) -> tuple[str, bool, dict, bool, str]:
    """
    Проверка идеи с помощью GigaChat
    Возвращает: (ответ, уникальность, распарсенные_данные, предложить_обработку, похожая_идея_описание)
    """
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
        - Если идея похожа на существующую — напиши "НЕ уникальна" и ОБЯЗАТЕЛЬНО укажи:
          * Название похожей инициативы
          * Владелец и контакт
          * Краткое описание похожей идеи (2-3 предложения)
          * В чем сходство
        - Если идея новая — напиши "Уникальна" и предложи рекомендации по улучшению.
        - Если текст непонятный — напиши "Извините, не могу понять описание".

        3. Дай конструктивные рекомендации по развитию идеи.

        Отвечай ТОЛЬКО на русском языке, без дополнительной технической информации.

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
        - Если идея похожа на существующую — напиши "НЕ уникальна" и ОБЯЗАТЕЛЬНО укажи:
          * Название похожей инициативы
          * Владелец и контакт
          * Краткое описание похожей идеи (2-3 предложения)
          * В чем сходство
        - Если идея новая — напиши "Уникальна" и предложи рекомендации по улучшению.
        
        3. Дай детальную оценку инициативы и советы по её развитию.

        Отвечай ТОЛЬКО на русском языке, без дополнительной технической информации.
        """

    try:
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")

        response_text = clean_response_text(raw_response)

        # Сохраняем в память для пользователя (если user_id известен)
        user_id = user_data.get("user_id")
        if user_id:
            gigachat_memory[user_id].append({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "input": prompt.strip(),
                "output": response_text.strip()
            })

        is_unique = "уникальна" in response_text.lower() and "не уникальна" not in response_text.lower()
        
        # Извлекаем информацию о похожей идее если она не уникальна
        similar_idea_description = ""
        if not is_unique:
            # Ищем описание похожей идеи в ответе
            lines = response_text.split('\n')
            for i, line in enumerate(lines):
                if 'не уникальна' in line.lower():
                    # Собираем следующие несколько строк как описание похожей идеи
                    similar_lines = []
                    for j in range(i+1, min(i+8, len(lines))):  # Берем до 7 следующих строк
                        if lines[j].strip() and not lines[j].startswith('Рекомендации'):
                            similar_lines.append(lines[j].strip())
                        if len(similar_lines) >= 4:  # Ограничиваем количество строк
                            break
                    similar_idea_description = '\n'.join(similar_lines)
                    break

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
                cost = calculate_work_cost(parsed_data)
                response_text += f"\n\n💰 Примерная стоимость работы: {cost}"
            except Exception as e:
                logging.error(f"Ошибка при расчете стоимости: {e}")

        suggest_processing = "похоже на идею" in response_text.lower() or "возможно, вы описали идею" in response_text.lower()

        return response_text, is_unique, parsed_data, suggest_processing, similar_idea_description
        
    except Exception as e:
        return f"⚠️ Ошибка при обращении к GigaChat: {e}", False, {}, False, ""
    
def generate_idea_suggestions(query: str = "") -> str:
    """Генерация предложений идей для AI-агентов"""
    try:
        agents_data = load_agents_data()
        existing_types = set()
        for agent in agents_data:
            if agent['type']:
                existing_types.add(agent['type'])
        
        existing_types_str = ", ".join(existing_types) if existing_types else "данные не загружены"
        
        prompt = f"""
        Пользователь просит помощи с идеей для AI-агента.
        Запрос: "{query}"
        
        Уже существующие типы агентов: {existing_types_str}
        
        Предложи 3-5 интересных и практических идей для AI-агентов, которые могли бы быть полезны.
        Учитывай:
        - Актуальные бизнес-процессы
        - Возможности современных AI-технологий
        - Практическую применимость
        - Избегай дублирования с существующими типами
        
        Для каждой идеи кратко опиши:
        - Название
        - Область применения  
        - Основную функцию
        - Ожидаемую пользу
        
        В конце предложи заполнить подробный шаблон для выбранной идеи.
        
        Отвечай ТОЛЬКО на русском языке, структурированно и понятно.
        """
        
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")

        response = clean_response_text(raw_response)
        
        return response if response else "💡 Вот несколько идей для AI-агентов:\n\n• Автоматизация обработки документов\n• Анализ клиентских запросов\n• Управление задачами и планирование\n• Мониторинг и аналитика процессов\n\n🔹 Выберите интересную идею, и я помогу детально её проработать!"
        
    except Exception as e:
        return f"⚠️ Ошибка при генерации идей: {e}"

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
        
        Найди агентов, которые наиболее соответствуют запросу пользователя.
        Учитывай название, описание, тип и область применения.
        
        Для каждого подходящего агента выведи:
        - Название
        - Краткое описание
        - Владелец и контакты
        - Почему этот агент подходит под запрос
        
        Если подходящих агентов нет, предложи альтернативы или советы.
        
        Отвечай ТОЛЬКО на русском языке, без дополнительной технической информации.
        """
        
        logging.info(f"[GigaChat Input] {prompt}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output] {raw_response}")
        
        response = clean_response_text(raw_response)
        
        return response if response else "🤖 Не удалось найти подходящих агентов по вашему запросу."
        
    except Exception as e:
        return f"⚠️ Ошибка при поиске владельцев: {e}"

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
        if key == "user_id":  # Пропускаем служебное поле
            continue
            
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
    
    # Добавляем информацию о стоимости если есть
    if cost_info:
        cost_heading = doc.add_heading("💰 Информация о стоимости", level=2)
        doc.add_paragraph(cost_info)
    
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
        if key == "user_id":  # Пропускаем служебное поле
            continue
        ws.append([key, str(value)])
        for cell in ws[ws.max_row]:
            cell.border = thin_border
            cell.alignment = wrap_alignment
    
    # Добавляем информацию о стоимости если есть
    if cost_info:
        ws.append(["", ""])  # Пустая строка
        ws.append(["Информация о стоимости", cost_info])
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