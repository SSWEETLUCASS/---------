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

gigachat_memory = defaultdict(lambda: deque(maxlen=15))  # Увеличен размер памяти

def clean_response_text(text: str) -> str:
    """Улучшенная очистка текста ответа от служебных символов и кодировок"""
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
    """Загрузка данных об агентах из файла с улучшенной обработкой ошибок"""
    try:
        agents_file = "agents.xlsx"
        
        if not os.path.exists(agents_file):
            logging.warning(f"⚠️ Файл {agents_file} не найден")
            return []
            
        wb = load_workbook(agents_file, data_only=True)
        ws = wb.active
        agents_data = []

        # Получаем заголовки
        headers = [cell.value for cell in ws[1] if cell.value]
        if len(headers) < 8:
            logging.error(f"❌ Недостаточно столбцов в файле агентов. Найдено: {len(headers)}")
            return []

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or not any(row):  # Пропускаем полностью пустые строки
                continue
                
            # Проверяем, что есть хотя бы название
            if not row[4]:  # Индекс 4 - это "Название"
                logging.debug(f"Пропуск строки {row_num}: нет названия агента")
                continue
            
            try:
                # Безопасно извлекаем значения с проверкой индексов
                values = list(row) + [None] * (8 - len(row))  # Дополняем до 8 элементов
                
                block, ssp, owner, contact, name, short_name, desc, typ = values[:8]
                
                agent_info = {
                    "block": str(block) if block else "",
                    "ssp": str(ssp) if ssp else "",
                    "owner": str(owner) if owner else "",
                    "contact": str(contact) if contact else "",
                    "name": str(name) if name else "",
                    "short_name": str(short_name) if short_name else "",
                    "description": str(desc) if desc else "",
                    "type": str(typ) if typ else ""
                }
                agents_data.append(agent_info)
                
            except Exception as e:
                logging.warning(f"⚠️ Ошибка обработки строки {row_num}: {e}")
                continue

        logging.info(f"✅ Загружено агентов: {len(agents_data)}")
        return agents_data
        
    except Exception as e:
        logging.error(f"❌ Ошибка при загрузке agents.xlsx: {e}")
        return []

def create_agent_utility_chart(agents_data: list[dict]) -> str:
    """Создание диаграммы полезности агентов с улучшенной аналитикой"""
    try:
        if not agents_data:
            logging.warning("⚠️ Нет данных для создания диаграммы")
            return None
            
        # Ограничиваем количество агентов для анализа (первые 8)
        agents_sample = agents_data[:8]
        
        # Анализируем агентов с помощью GigaChat
        agents_descriptions = []
        for agent in agents_sample:
            agents_descriptions.append(f"- {agent['name']}: {agent['description'][:200]}...")
            
        prompt = f"""
        Проанализируй следующих AI-агентов и оцени их по критериям полезности от 1 до 10:

        {chr(10).join(agents_descriptions)}
        
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
        
        logging.info(f"[GigaChat Chart] Запрос аналитики для {len(agents_sample)} агентов")
        raw_response = get_llm().invoke(prompt)
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
                        # Проверяем корректность оценок
                        if all(1 <= rating <= 10 for rating in ratings):
                            agent_ratings[name] = ratings
                    except (ValueError, IndexError):
                        continue
        
        # Fallback - создаем оценки на основе анализа описаний
        if not agent_ratings:
            logging.info("📊 Создание fallback оценок для диаграммы")
            for agent in agents_sample:
                # Анализируем описание для генерации реалистичных оценок
                desc_lower = agent['description'].lower()
                
                # Базовые оценки
                time_saving = 7
                quality = 6
                implementation = 5
                scalability = 6
                roi = 6
                
                # Корректируем на основе ключевых слов
                if any(word in desc_lower for word in ['автомат', 'быстр', 'мгновенн']):
                    time_saving += 2
                if any(word in desc_lower for word in ['точн', 'качеств', 'надежн']):
                    quality += 2
                if any(word in desc_lower for word in ['прост', 'легк', 'интуитивн']):
                    implementation += 2
                if any(word in desc_lower for word in ['масштаб', 'расшир', 'универсальн']):
                    scalability += 2
                if any(word in desc_lower for word in ['эконом', 'прибыл', 'эффективн']):
                    roi += 2
                
                # Ограничиваем значения
                ratings = [min(10, max(4, rating)) for rating in [time_saving, quality, implementation, scalability, roi]]
                agent_ratings[agent['name']] = ratings
        
        if not agent_ratings:
            logging.error("❌ Не удалось создать оценки для диаграммы")
            return None
        
        # Создаем диаграмму
        plt.style.use('default')
        fig, ax = plt.subplots(figsize=(16, 10))
        
        criteria = ['Экономия\nвремени', 'Качество\nрезультата', 'Простота\nвнедрения', 
                   'Масштаби-\nруемость', 'ROI\nпотенциал']
        
        # Улучшенная цветовая палитра
        colors = ['#2E8B57', '#4169E1', '#FF6347', '#32CD32', '#FF8C00']
        
        x = np.arange(len(criteria))
        width = 0.12
        
        agents_list = list(agent_ratings.items())[:6]  # Топ 6 агентов
        
        for i, (agent_name, ratings) in enumerate(agents_list):
            offset = width * (i - len(agents_list)/2 + 0.5)
            # Используем градиентные цвета для каждого агента
            color = plt.cm.Set3(i / len(agents_list))
            
            bars = ax.bar(x + offset, ratings, width, 
                         label=agent_name[:25] + ('...' if len(agent_name) > 25 else ''),
                         alpha=0.8, color=color, edgecolor='black', linewidth=0.5)
            
            # Добавляем значения на столбцы
            for j, bar in enumerate(bars):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                       f'{ratings[j]}', ha='center', va='bottom', 
                       fontsize=10, fontweight='bold')
        
        # Стилизация графика
        ax.set_xlabel('Критерии оценки', fontsize=14, fontweight='bold', pad=15)
        ax.set_ylabel('Оценка (1-10)', fontsize=14, fontweight='bold', pad=15)
        ax.set_title('Сравнительная оценка полезности AI-агентов', 
                     fontsize=16, fontweight='bold', pad=25)
        ax.set_xticks(x)
        ax.set_xticklabels(criteria, fontsize=11)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=10)
        ax.set_ylim(0, 11)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # Улучшаем внешний вид
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_linewidth(1.5)
        ax.spines['bottom'].set_linewidth(1.5)
        
        # Добавляем подпись с датой
        fig.text(0.99, 0.01, f'Создано: {datetime.now().strftime("%d.%m.%Y %H:%M")}', 
                ha='right', va='bottom', fontsize=9, style='italic', color='gray')
        
        plt.tight_layout()
        
        # Сохраняем диаграмму
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chart_path = f"agent_utility_chart_{timestamp}.png"
        plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        logging.info(f"✅ Диаграмма сохранена: {chart_path}")
        return chart_path
        
    except Exception as e:
        logging.error(f"❌ Ошибка при создании диаграммы: {e}")
        return None

def check_general_message_with_gigachat(msg: str, user_id: int = None) -> tuple[str, str | None, dict | None]:
    """
    Улучшенная проверка общего сообщения с помощью GigaChat для естественного диалога.
    """
    try:
        # Получаем историю предыдущих сообщений пользователя для контекста
        user_history = ""
        if user_id and user_id in gigachat_memory:
            recent_messages = list(gigachat_memory[user_id])[-4:]  # Последние 4 сообщения
            if recent_messages:
                user_history = "Контекст предыдущих сообщений:\n" + "\n".join([
                    f"👤: {msg_data['input'][:80]}...\n🤖: {msg_data['output'][:80]}..." 
                    for msg_data in recent_messages
                ]) + "\n\n"

        # Улучшенный промпт с более детальными инструкциями
        prompt = f"""
        {user_history}Текущее сообщение пользователя:
        \"\"\"{msg}\"\"\"

        Ты — дружелюбный и умный консультант по AI-агентам и бизнес-идеям. Твоя задача:
        1. Веди естественный диалог
        2. Помогай с конкретными действиями
        3. Используй эмодзи для дружелюбности
        4. Предлагай решения проблем пользователя

        ВАЖНО: В конце ответа, если видишь возможность помочь конкретным действием, добавляй JSON-команду:
        ACTION: {{"action": "название_действия", "context": {{"ключ": "значение"}}}}

        Доступные действия:
        - start: приветствие и знакомство
        - process_idea_template: заполнение идеи по шаблону  
        - process_idea_free: обработка описанной идеи
        - show_agents: показать список агентов
        - search_owners: поиск владельцев по запросу
        - consultation: консультация и контакты
        - help: справочная информация
        - generate_ideas: генерация новых идей

        Примеры правильного поведения:

        Пользователь: "Привет! Что ты умеешь?"
        Ты: Привет! 👋 Я помогаю с AI-агентами и бизнес-идеями! Могу показать существующих агентов, помочь проанализировать твою идею или найти нужных специалистов. С чего начнем? ACTION: {{"action": "start", "context": {{}}}}

        Пользователь: "У меня идея автоматизировать HR процессы"
        Ты: Отличная идея! 🚀 HR-процессы действительно можно здорово оптимизировать с помощью AI. Давайте детально проанализируем вашу идею и посчитаем потенциал! ACTION: {{"action": "process_idea_free", "context": {{"idea_text": "автоматизация HR процессов"}}}}

        Пользователь: "Кто занимается аналитикой данных?"
        Ты: Отлично! 📊 Найду для вас специалистов по аналитике данных среди владельцев наших AI-агентов. ACTION: {{"action": "search_owners", "context": {{"search_query": "аналитика данных"}}}}

        Правила:
        - Максимум 3000 символов в ответе
        - Всегда дружелюбный тон
        - Конкретные предложения помощи
        - ACTION только когда реально нужно действие
        - Понимай контекст и намерения пользователя
        - Если не понимаешь - переспрашивай
        """

        logging.info(f"[GigaChat Input User {user_id}] {msg}")
        raw_response = get_llm().invoke(prompt)
        logging.info(f"[GigaChat Output User {user_id}] {raw_response}")

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
                logging.info(f"🎯 Извлечено действие: {suggested_action} с контекстом: {context_data}")
            except json.JSONDecodeError as e:
                logging.warning(f"⚠️ Не удалось распарсить ACTION JSON: {e}")
        
        return response, suggested_action, context_data

    except Exception as e:
        logging.error(f"❌ Ошибка при обращении к GigaChat: {e}")
        return f"⚠️ Произошла ошибка при обработке запроса: {e}", None, None

def check_idea_with_gigachat_local(user_input: str, user_data: dict, is_free_form: bool = False) -> tuple[str, bool, dict, bool, str]:
    """
    Улучшенная проверка идеи с помощью GigaChat
    """
    try:
        agents_data = load_agents_data()
        
        # Формируем компактное описание агентов для анализа
        if agents_data:
            agents_summary = []
            for agent in agents_data[:20]:  # Ограничиваем количество для экономии токенов
                agents_summary.append(
                    f"• {agent['name']} ({agent['type']}): {agent['description'][:100]}... "
                    f"[Владелец: {agent['owner']}, Контакт: {agent['contact']}]"
                )
            joined_data = "\n".join(agents_summary)
        else:
            joined_data = "(список инициатив пуст)"
            
    except Exception as e:
        logging.error(f"❌ Ошибка при загрузке agents.xlsx: {e}")
        joined_data = "(не удалось загрузить данные об инициативах)"

    if is_free_form:
        prompt = f"""
        СУЩЕСТВУЮЩИЕ AI-АГЕНТЫ И ИНИЦИАТИВЫ:
        {joined_data}

        ЗАДАЧА: Проанализируй текст пользователя и выполни следующее:

        1. СТРУКТУРИРОВАНИЕ ИДЕИ:
        Собери информацию по шаблону (если информация есть в тексте):
        - "Название": [краткое название идеи]
        - "Что хотим улучшить?": [описание проблемы]
        - "Какие данные поступают агенту на вход?": [входные данные]
        - "Как процесс выглядит сейчас? (as-is)": [текущее состояние]
        - "Какой результат нужен от агента?": [ожидаемый выход]
        - "Достижимый идеал (to-be)": [желаемое состояние]
        - "Масштаб процесса": [оцени: малый/средний/большой/крупный]

        2. АНАЛИЗ УНИКАЛЬНОСТИ:
        Сравни с существующими агентами:
        - Если похожая идея ЕСТЬ → напиши "НЕ уникальна" и укажи:
          * Название похожего агента
          * Владелец и контакт  
          * В чем сходство
        - Если идея НОВАЯ → напиши "Уникальна"

        3. РЕКОМЕНДАЦИИ:
        Дай практические советы по развитию идеи.

        ВАЖНО: Отвечай ТОЛЬКО на русском языке, структурированно, до 3500 символов.

        ТЕКСТ ПОЛЬЗОВАТЕЛЯ:
        \"\"\"{user_data.get('Описание в свободной форме', '')}\"\"\"
        """
    else:
        user_initiative = "\n".join([f"• {key}: {value}" for key, value in user_data.items() if key != "user_id"])
        
        prompt = f"""
        ИНИЦИАТИВА ПОЛЬЗОВАТЕЛЯ:
        {user_initiative}

        СУЩЕСТВУЮЩИЕ АГЕНТЫ:
        {joined_data}

        ЗАДАЧА:
        1. Внимательно сравни инициативу с существующими агентами
        2. Определи уникальность:
           - НЕ уникальна: укажи похожий агент, владельца, контакт, сходство
           - Уникальна: дай рекомендации по улучшению
        3. Оцени перспективы и дай советы

        Ответ на русском языке, до 3000 символов.
        """

    try:
        logging.info(f"[GigaChat Idea Analysis] Анализ идеи пользователя {user_data.get('user_id', 'unknown')}")
        raw_response = get_llm().invoke(prompt)
        response_text = clean_response_text(raw_response)

        # Сохраняем в память для пользователя
        user_id = user_data.get("user_id")
        if user_id:
            gigachat_memory[user_id].append({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "input": f"Анализ идеи: {user_input[:100]}...",
                "output": response_text[:200] + "..."
            })

        # Определяем уникальность
        response_lower = response_text.lower()
        is_unique = ("уникальна" in response_lower and 
                    "не уникальна" not in response_lower and
                    "неуникальна" not in response_lower)
        
        # Извлекаем информацию о похожей идее
        similar_idea_description = ""
        if not is_unique:
            # Ищем блок с информацией о похожей идее
            lines = response_text.split('\n')
            collecting = False
            similar_lines = []
            
            for line in lines:
                line_lower = line.lower()
                if any(phrase in line_lower for phrase in ['не уникальна', 'неуникальна', 'похожий агент', 'существующий агент']):
                    collecting = True
                elif collecting and (line_lower.startswith('рекомендации') or 
                                   line_lower.startswith('советы') or
                                   line_lower.startswith('выводы')):
                    break
                
                if collecting and line.strip():
                    similar_lines.append(line.strip())
                    
            similar_idea_description = '\n'.join(similar_lines[:6])  # Ограничиваем длину

        # Парсинг данных из свободной формы
        parsed_data = {}
        if is_free_form:
            fields = [
                "Название", "Что хотим улучшить?", "Какие данные поступают агенту на вход?",
                "Как процесс выглядит сейчас? (as-is)", "Какой результат нужен от агента?",
                "Достижимый идеал (to-be)", "Масштаб процесса"
            ]
            
            for field in fields:
                # Ищем поле в тексте ответа
                patterns = [
                    rf'["\']?{re.escape(field)}["\']?\s*[:\-–]\s*(.+?)(?=\n["\']?\w+["\']?\s*[:\-–]|$)',
                    rf'{re.escape(field.lower())}\s*[:\-–]\s*(.+?)(?=\n\w+\s*[:\-–]|$)',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, response_text, re.IGNORECASE | re.DOTALL)
                    if match:
                        value = match.group(1).strip()
                        # Очищаем от лишних символов
                        value = re.sub(r'^\[|\], '', value)
                        value = value.strip()
                        if value and len(value) > 5:  # Минимальная длина для значимого ответа
                            parsed_data[field] = value
                        break
        
        # Добавляем стоимость если идея уникальна
        if is_unique and (parsed_data or not is_free_form):
            try:
                data_for_cost = parsed_data if parsed_data else user_data
                cost = calculate_work_cost(data_for_cost, is_unique)
                response_text += f"\n\n{cost}"
            except Exception as e:
                logging.error(f"❌ Ошибка при расчете стоимости: {e}")

        suggest_processing = any(phrase in response_text.lower() for phrase in 
                               ["похоже на идею", "возможно, вы описали идею", "это идея"])

        logging.info(f"✅ Анализ завершен. Уникальность: {is_unique}, Данные извлечены: {len(parsed_data)} полей")
        return response_text, is_unique, parsed_data, suggest_processing, similar_idea_description
        
    except Exception as e:
        logging.error(f"❌ Ошибка при обращении к GigaChat для анализа идеи: {e}")
        return f"⚠️ Ошибка при анализе идеи: {e}", False, {}, False, ""
    
def generate_idea_suggestions(query: str = "") -> str:
    """Улучшенная генерация предложений идей для AI-агентов"""
    try:
        agents_data = load_agents_data()
        
        # Анализируем существующие типы и области
        existing_types = set()
        existing_areas = set()
        
        for agent in agents_data:
            if agent['type']:
                existing_types.add(agent['type'].lower())
            if agent['block']:
                existing_areas.add(agent['block'].lower())
        
        existing_types_str = ", ".join(sorted(existing_types)) if existing_types else "не определены"
        existing_areas_str = ", ".join(sorted(existing_areas)) if existing_areas else "не определены"
        
        # Улучшенный промпт для генерации идей
        prompt = f"""
        ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{query}"
        
        КОНТЕКСТ:
        • Существующие типы агентов: {existing_types_str}
        • Существующие области: {existing_areas_str}
        • Всего агентов в базе: {len(agents_data)}
        
        ЗАДАЧА: Сгенерируй 4-6 практических и инновационных идей для AI-агентов.
        
        ТРЕБОВАНИЯ:
        1. Учитывай запрос пользователя
        2. Избегай дублирования с существующими типами
        3. Фокусируйся на реальных бизнес-потребностях
        4. Учитывай современные возможности AI
        
        ДЛЯ КАЖДОЙ ИДЕИ укажи:
        📌 **Название агента**
        🎯 **Область применения**: [конкретная сфера]
        ⚙️ **Основная функция**: [что делает агент]
        💰 **Ожидаемая польза**: [экономический эффект]
        🔧 **Сложность внедрения**: [простая/средняя/высокая]
        📊 **Потенциальная экономия**: [в часах/деньгах]
        
        ПРИМЕРЫ АКТУАЛЬНЫХ НАПРАВЛЕНИЙ:
        • Автоматизация рутинных процессов
        • Анализ и обработка документов
        • Прогнозирование и планирование
        • Персонализация клиентского опыта
        • Контроль качества и мониторинг
        • Оптимизация ресурсов
        
        В КОНЦЕ добавь: "🚀 Выберите интересную идею, и я помогу детально её проработать с расчетом стоимости!"
        
        Ответ на русском языке, структурированно, до 4000 символов.
        """
        
        logging.info(f"[GigaChat Ideas] Генерация идей по запросу: {query}")
        raw_response = get_llm().invoke(prompt)
        response = clean_response_text(raw_response)
        
        if not response or len(response.strip()) < 100:
            # Fallback ответ
            fallback_ideas = [
                "📌 **Агент умной аналитики продаж**\n🎯 Область: Коммерция\n⚙️ Функция: Прогнозирование спроса и оптимизация цен\n💰 Польза: +15-30% к выручке",
                "📌 **Агент автоматизации HR-процессов**\n🎯 Область: Управление персоналом\n⚙️ Функция: Скрининг резюме и планирование собеседований\n💰 Польза: 70% экономии времени HR",
                "📌 **Агент контроля качества документов**\n🎯 Область: Документооборот\n⚙️ Функция: Проверка соответствия стандартам и поиск ошибок\n💰 Польза: Снижение брака на 80%"
            ]
            
            response = "💡 **Идеи для AI-агентов:**\n\n" + "\n\n".join(fallback_ideas)
            response += "\n\n🚀 Выберите интересную идею, и я помогу детально её проработать с расчетом стоимости!"
        
        logging.info(f"✅ Сгенерировано идей для пользователя")
        return

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