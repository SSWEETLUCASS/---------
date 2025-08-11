import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Any
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, MessageContentType
from dialog_bot_sdk.entities.messaging import MessageHandler, CommandHandler

from ai_agent import (
    check_general_message_with_gigachat,
    check_idea_with_gigachat_local,
    generate_files,
    generate_agents_summary_file,
    find_agent_owners,
    generate_idea_suggestions,
    calculate_work_cost,
)

# Загрузка конфигурации
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Загрузка переменных окружения
load_dotenv()

# Установка путей к сертификатам
os.environ["REQUESTS_CA_BUNDLE"] = config['file_settings']['certificates']['requests_ca_bundle']
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = config['file_settings']['certificates']['grpc_roots']

BOT_TOKEN = os.getenv("DIALOG_BOT_TOKEN")

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config['logging']['level']),
    format=config['logging']['format'],
    filename=config['logging']['file']
)

class UserSession:
    """Класс для управления сессией пользователя"""
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.mode = config['states']['main_menu']
        self.context = {}
        self.message_history = deque(maxlen=10)  # Последние 10 сообщений
        self.last_activity = datetime.now()
        self.conversation_started = False
        self.preferred_communication_style = "friendly"  # friendly, formal, technical
        
    def add_message(self, message: str, is_user: bool = True):
        """Добавить сообщение в историю"""
        self.message_history.append({
            'text': message,
            'timestamp': datetime.now(),
            'is_user': is_user
        })
        self.last_activity = datetime.now()
    
    def get_context_for_ai(self) -> str:
        """Получить контекст для ИИ"""
        if not self.message_history:
            return ""
        
        context_messages = []
        for msg in list(self.message_history)[-5:]:  # Последние 5 сообщений
            sender = "Пользователь" if msg['is_user'] else "Бот"
            context_messages.append(f"{sender}: {msg['text']}")
        
        return "Контекст диалога:\n" + "\n".join(context_messages)
    
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """Проверить, истекла ли сессия"""
        return datetime.now() - self.last_activity > timedelta(minutes=timeout_minutes)

class ConversationManager:
    """Менеджер для управления диалогами"""
    def __init__(self):
        self.sessions: Dict[int, UserSession] = {}
        self.session_lock = threading.Lock()
        
        # Запуск фонового процесса очистки сессий
        self.cleanup_thread = threading.Thread(target=self._cleanup_expired_sessions, daemon=True)
        self.cleanup_thread.start()
    
    def get_session(self, user_id: int) -> UserSession:
        """Получить или создать сессию пользователя"""
        with self.session_lock:
            if user_id not in self.sessions or self.sessions[user_id].is_expired():
                self.sessions[user_id] = UserSession(user_id)
            return self.sessions[user_id]
    
    def _cleanup_expired_sessions(self):
        """Очистка истекших сессий"""
        while True:
            time.sleep(300)  # Проверка каждые 5 минут
            with self.session_lock:
                expired_sessions = [
                    user_id for user_id, session in self.sessions.items()
                    if session.is_expired()
                ]
                for user_id in expired_sessions:
                    del self.sessions[user_id]
                    logging.info(f"🗑️ Сессия пользователя {user_id} удалена (истекла)")

# Глобальные переменные
conversation_manager = ConversationManager()
bot = None

class FileManager:
    """Улучшенный менеджер файлов"""
    
    @staticmethod
    def send_file_with_retry(bot_instance, peer, file_path: str, name: str = None, text: str = None, max_retries: int = 3) -> bool:
        """Отправка файла с повторными попытками"""
        for attempt in range(max_retries):
            try:
                if not os.path.exists(file_path):
                    logging.error(f"❌ Файл не найден: {file_path}")
                    return False
                
                file_size = os.path.getsize(file_path)
                if file_size == 0:
                    logging.warning(f"⚠️ Файл пуст: {file_path}")
                    return False
                
                logging.info(f"🔄 Отправка файла (попытка {attempt + 1}): {name} ({file_size} байт)")
                
                with open(file_path, "rb") as f:
                    result = bot_instance.messaging.send_file(
                        peer=peer,
                        file=f,
                        message=text,
                        file_name=name or os.path.basename(file_path),
                    )
                
                logging.info(f"✅ Файл успешно отправлен: {name}")
                return True
                
            except Exception as e:
                logging.error(f"❌ Ошибка отправки файла (попытка {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    # Последняя попытка - пробуем альтернативный метод
                    try:
                        with open(file_path, "rb") as f:
                            result = bot_instance.messaging.send_filewrapped(
                                peer, f, None, text, name or os.path.basename(file_path)
                            )
                        logging.info(f"✅ Файл отправлен альтернативным методом: {name}")
                        return True
                    except Exception as e2:
                        logging.error(f"❌ Альтернативная отправка не удалась: {e2}")
                        return False
                time.sleep(1)  # Пауза перед повтором
        
        return False

class ResponseGenerator:
    """Генератор ответов с контекстом"""
    
    @staticmethod
    def generate_contextual_response(session: UserSession, text: str) -> Tuple[str, bool, Optional[str]]:
        """Генерация контекстного ответа"""
        try:
            # Получаем контекст диалога
            context = session.get_context_for_ai()
            
            # Формируем запрос с контекстом
            if context:
                full_prompt = f"{context}\n\nТекущее сообщение пользователя: {text}"
            else:
                full_prompt = text
            
            # Вызываем ИИ с контекстом
            response, is_idea, command = check_general_message_with_gigachat(full_prompt)
            
            # Адаптируем ответ под стиль общения пользователя
            if session.preferred_communication_style == "friendly":
                response = ResponseGenerator._make_response_friendly(response)
            elif session.preferred_communication_style == "formal":
                response = ResponseGenerator._make_response_formal(response)
            
            return response, is_idea, command
            
        except Exception as e:
            logging.error(f"Ошибка при генерации контекстного ответа: {e}")
            return "Извините, произошла ошибка при обработке вашего сообщения. Попробуйте еще раз.", False, None
    
    @staticmethod
    def _make_response_friendly(response: str) -> str:
        """Делает ответ более дружелюбным"""
        if response and not any(emoji in response for emoji in ['😊', '👍', '🤝', '💡', '🔥']):
            # Добавляем дружелюбности, если её нет
            friendly_starters = ["Отлично! ", "Понятно! ", "Интересно! ", "Хорошо! "]
            import random
            return random.choice(friendly_starters) + response
        return response
    
    @staticmethod
    def _make_response_formal(response: str) -> str:
        """Делает ответ более формальным"""
        # Убираем излишнюю эмоциональность
        formal_replacements = {
            '!': '.',
            'отлично': 'хорошо',
            'круто': 'интересно',
            'супер': 'отлично'
        }
        
        for informal, formal in formal_replacements.items():
            response = response.replace(informal, formal)
        
        return response

def detect_communication_style(text: str) -> str:
    """Определение стиля общения пользователя"""
    formal_indicators = ['пожалуйста', 'благодарю', 'извините', 'будьте добры']
    friendly_indicators = ['привет', 'спасибо', 'круто', 'супер', '!']
    
    text_lower = text.lower()
    
    formal_count = sum(1 for indicator in formal_indicators if indicator in text_lower)
    friendly_count = sum(1 for indicator in friendly_indicators if indicator in text_lower)
    
    if formal_count > friendly_count:
        return "formal"
    elif friendly_count > 0:
        return "friendly"
    else:
        return "neutral"

# Улучшенные обработчики команд
def start_handler(update: UpdateMessage) -> None:
    """Улучшенный обработчик команды /start"""
    user_id = update.peer.id
    session = conversation_manager.get_session(user_id)
    
    session.mode = config['states']['main_menu']
    session.conversation_started = True
    session.add_message("/start")
    
    welcome_message = config['bot_settings']['commands']['start']['response']
    
    # Персонализируем приветствие
    if len(session.message_history) > 1:
        welcome_message = "С возвращением! 👋\n\n" + welcome_message
    
    bot.messaging.send_message(update.peer, welcome_message)
    session.add_message(welcome_message, is_user=False)

def smart_idea_handler(update: UpdateMessage) -> None:
    """Умный обработчик для работы с идеями"""
    peer = update.peer
    user_id = peer.id
    session = conversation_manager.get_session(user_id)
    
    # Проверяем, не находится ли пользователь уже в процессе
    if session.mode.startswith("idea_"):
        bot.messaging.send_message(peer, 
            "Вы уже работаете с идеей! 😊\n"
            "Завершите текущий процесс или напишите /start для начала сначала.")
        return
    
    session.mode = config['states']['idea_choose_format']
    session.context = {"current_field": 0, "idea_data": {}}
    session.add_message("/idea")
    
    # Более естественное предложение выбора
    response = (
        "Отлично! Давайте проработаем вашу идею! 💡\n\n"
        "Как удобнее:\n"
        "🔹 **По шаблону** - я задам вам несколько вопросов, чтобы структурированно собрать всю информацию\n"
        "🔹 **Свободно** - расскажите об идее своими словами, а я сам выделю ключевые моменты\n\n"
        "Просто напишите \"шаблон\" или \"свободно\", или опишите свою идею - я пойму! 😉"
    )
    
    bot.messaging.send_message(peer, response)
    session.add_message(response, is_user=False)

def enhanced_text_handler(update: UpdateMessage, widget=None):
    """Улучшенный обработчик текстовых сообщений"""
    if not update.message or not update.message.text_message:
        return

    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer
    session = conversation_manager.get_session(user_id)
    
    # Добавляем сообщение в историю
    session.add_message(text)
    
    # Определяем стиль общения
    detected_style = detect_communication_style(text)
    if detected_style != "neutral":
        session.preferred_communication_style = detected_style
    
    logging.info(f"📩 Пользователь {user_id} ({session.mode}): {text}")

    try:
        # Обработка в зависимости от режима
        if session.mode == config['states']['idea_choose_format']:
            handle_idea_format_choice(update, session, text)
            
        elif session.mode == config['states']['idea_template']:
            handle_template_idea(update, session, text)
            
        elif session.mode == config['states']['idea_free_form']:
            handle_free_form_idea(update, session, text)
            
        elif session.mode == config['states']['search_owners']:
            handle_owner_search(update, session, text)
            
        elif session.mode == config['states']['help_with_ideas']:
            handle_idea_generation(update, session, text)
            
        else:
            # Обработка команд и общего диалога
            handle_general_conversation(update, session, text)
    
    except Exception as e:
        logging.error(f"Критическая ошибка в enhanced_text_handler: {e}")
        error_response = (
            "Извините, произошла непредвиденная ошибка 😔\n"
            "Попробуйте написать /start для сброса состояния."
        )
        bot.messaging.send_message(peer, error_response)
        session.add_message(error_response, is_user=False)
        session.mode = config['states']['main_menu']

def handle_idea_format_choice(update: UpdateMessage, session: UserSession, text: str):
    """Обработка выбора формата идеи"""
    peer = update.peer
    text_lower = text.lower()
    
    if any(word in text_lower for word in ["шаблон", "вопрос", "структур"]):
        session.mode = config['states']['idea_template']
        session.context["current_field"] = 0
        session.context["idea_data"] = {}
        
        response = "Отлично! Пройдемся по шаблону 📝\n\n"
        response += f"**{config['template_fields'][0]}**\n"
        response += "Расскажите подробно об этом аспекте:"
        
    elif any(word in text_lower for word in ["свобод", "сам", "своими словами"]):
        session.mode = config['states']['idea_free_form']
        response = (
            "Понял! Рассказывайте свободно 💭\n\n"
            "Опишите вашу идею так, как удобно вам. "
            "Я проанализирую текст и выделю все важные моменты!"
        )
        
    else:
        # Пользователь сразу начал описывать идею
        if len(text.split()) > 10:  # Если сообщение достаточно длинное
            session.mode = config['states']['idea_free_form']
            # Обрабатываем как свободную форму
            handle_free_form_idea(update, session, text)
            return
        else:
            response = (
                "Не совсем понял ваш выбор 🤔\n\n"
                "Напишите:\n"
                "• \"шаблон\" - для пошаговых вопросов\n"
                "• \"свободно\" - для описания своими словами\n"
                "Или просто начните рассказывать об идее!"
            )
    
    bot.messaging.send_message(peer, response)
    session.add_message(response, is_user=False)

def handle_template_idea(update: UpdateMessage, session: UserSession, text: str):
    """Улучшенная обработка идеи по шаблону"""
    peer = update.peer
    current_field = session.context["current_field"]
    
    # Сохраняем ответ на текущий вопрос
    if current_field > 0:
        field_name = config['template_fields'][current_field - 1]
        session.context["idea_data"][field_name] = text
        
        # Подтверждаем получение ответа
        confirmation = f"✅ Записал: **{field_name}**\n\n"
    else:
        confirmation = ""
    
    # Переходим к следующему вопросу
    if current_field < len(config['template_fields']):
        field_name = config['template_fields'][current_field]
        response = f"{confirmation}**{field_name}**\nРасскажите об этом аспекте:"
        session.context["current_field"] += 1
        
    else:
        # Все поля заполнены, начинаем анализ
        response = confirmation + "Отлично! Все данные собраны 🎉\n\nАнализирую вашу идею..."
        
        try:
            analyze_and_respond_idea(peer, session, text, is_template=True)
            return
            
        except Exception as e:
            logging.error(f"Ошибка при анализе шаблонной идеи: {e}")
            response = f"Произошла ошибка при анализе: {e}\nПопробуйте еще раз или напишите /start"
            session.mode = config['states']['main_menu']
    
    bot.messaging.send_message(peer, response)
    session.add_message(response, is_user=False)

def handle_free_form_idea(update: UpdateMessage, session: UserSession, text: str):
    """Обработка идеи в свободной форме"""
    peer = update.peer
    
    bot.messaging.send_message(peer, "Анализирую вашу идею... 🔍")
    
    try:
        analyze_and_respond_idea(peer, session, text, is_template=False)
        
    except Exception as e:
        logging.error(f"Ошибка при обработке свободной идеи: {e}")
        error_response = f"Произошла ошибка при анализе: {e}\nПопробуйте еще раз или напишите /start"
        bot.messaging.send_message(peer, error_response)
        session.add_message(error_response, is_user=False)
        session.mode = config['states']['main_menu']

def analyze_and_respond_idea(peer, session: UserSession, text: str, is_template: bool):
    """Анализ идеи и отправка результатов"""
    try:
        if is_template:
            user_data = session.context["idea_data"]
        else:
            user_data = {"Описание в свободной форме": text}
        
        response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
            text, user_data, is_free_form=not is_template
        )
        
        cost_info = calculate_work_cost(parsed_data or user_data)
        
        # Формируем красивый ответ
        full_response = (
            f"🧠 **Результат анализа идеи:**\n\n{response}\n\n"
            f"💰 **Оценка стоимости реализации:**\n{cost_info}"
        )
        
        bot.messaging.send_message(peer, full_response)
        session.add_message(full_response, is_user=False)
        
        # Генерируем и отправляем файлы
        if parsed_data or user_data:
            generate_and_send_files(peer, session, parsed_data or user_data, cost_info)
        
        # Возвращаемся в главное меню
        session.mode = config['states']['main_menu']
        
        final_message = (
            "\n🎯 **Анализ завершен!**\n\n"
            "Хотите проработать еще одну идею? Напишите `/idea`\n"
            "Или задайте любой вопрос - я всегда готов помочь! 😊"
        )
        bot.messaging.send_message(peer, final_message)
        session.add_message(final_message, is_user=False)
        
    except Exception as e:
        logging.error(f"Ошибка в analyze_and_respond_idea: {e}")
        raise

def generate_and_send_files(peer, session: UserSession, data: dict, cost_info: str):
    """Генерация и отправка файлов"""
    try:
        word_path, excel_path = generate_files(data, cost_info)
        
        bot.messaging.send_message(peer, "📎 Подготавливаю файлы...")
        
        # Отправляем Word файл
        if FileManager.send_file_with_retry(bot, peer, word_path, 
                                          name=os.path.basename(word_path), 
                                          text="📄 Техническое описание проекта"):
            logging.info("✅ Word файл отправлен успешно")
        else:
            bot.messaging.send_message(peer, "❌ Не удалось отправить Word файл")
        
        # Отправляем Excel файл
        if FileManager.send_file_with_retry(bot, peer, excel_path, 
                                          name=os.path.basename(excel_path), 
                                          text="📊 Структурированные данные"):
            logging.info("✅ Excel файл отправлен успешно")
        else:
            bot.messaging.send_message(peer, "❌ Не удалось отправить Excel файл")
        
        # Удаляем временные файлы
        try:
            os.remove(word_path)
            os.remove(excel_path)
        except Exception as e:
            logging.warning(f"Не удалось удалить временные файлы: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка при генерации файлов: {e}")
        bot.messaging.send_message(peer, "❌ Произошла ошибка при создании файлов")

def handle_owner_search(update: UpdateMessage, session: UserSession, text: str):
    """Обработка поиска владельцев"""
    peer = update.peer
    
    bot.messaging.send_message(peer, f"🔍 Ищу информацию по запросу: \"{text}\"...")
    
    try:
        owners_info = find_agent_owners(text)
        bot.messaging.send_message(peer, owners_info)
        session.add_message(owners_info, is_user=False)
        
        session.mode = config['states']['main_menu']
        
        follow_up = (
            "\n💡 **Нужен еще поиск?**\n"
            "Напишите `/search_owners` или просто задайте новый вопрос!"
        )
        bot.messaging.send_message(peer, follow_up)
        session.add_message(follow_up, is_user=False)
        
    except Exception as e:
        logging.error(f"Ошибка при поиске владельцев: {e}")
        error_response = f"Произошла ошибка при поиске: {e}"
        bot.messaging.send_message(peer, error_response)
        session.add_message(error_response, is_user=False)
        session.mode = config['states']['main_menu']

def handle_idea_generation(update: UpdateMessage, session: UserSession, text: str):
    """Обработка генерации идей"""
    peer = update.peer
    
    bot.messaging.send_message(peer, "🧠 Генерирую идеи на основе вашего запроса...")
    
    try:
        ideas_response = generate_idea_suggestions(text)
        
        full_response = (
            f"💡 **Идеи по теме \"{text}\":**\n\n{ideas_response}\n\n"
            "🔹 Понравилась какая-то идея? Напишите `/idea` для детальной проработки!\n"
            "🔹 Хотите еще идеи? Просто опишите другую область!"
        )
        
        bot.messaging.send_message(peer, full_response)
        session.add_message(full_response, is_user=False)
        
        session.mode = config['states']['main_menu']
        
    except Exception as e:
        logging.error(f"Ошибка при генерации идей: {e}")
        error_response = f"Произошла ошибка при генерации идей: {e}"
        bot.messaging.send_message(peer, error_response)
        session.add_message(error_response, is_user=False)
        session.mode = config['states']['main_menu']

def handle_general_conversation(update: UpdateMessage, session: UserSession, text: str):
    """Обработка обычного диалога"""
    peer = update.peer
    
    # Проверяем команды
    if text.startswith('/'):
        handle_command(update, session, text)
        return
    
    # Генерируем контекстный ответ
    try:
        gpt_response, is_maybe_idea, command = ResponseGenerator.generate_contextual_response(session, text)
        logging.info(f"🔎 ИИ ответ: {gpt_response[:100]}..., Идея: {is_maybe_idea}, Команда: {command}")
        
        if command:
            # ИИ предлагает выполнить команду
            handle_ai_suggested_command(update, session, command)
            
        elif is_maybe_idea:
            # ИИ определил потенциальную идею
            response = (
                f"{gpt_response}\n\n"
                "💡 **Это похоже на интересную идею!**\n"
                "Хотите проверить её на уникальность и получить детальный анализ? "
                "Напишите `/idea` и мы её проработаем!"
            )
            bot.messaging.send_message(peer, response)
            session.add_message(response, is_user=False)
            
        else:
            # Обычный диалог
            response = gpt_response or "Интересно! Расскажите больше 🤔"
            bot.messaging.send_message(peer, response)
            session.add_message(response, is_user=False)
            
    except Exception as e:
        logging.error(f"Ошибка в handle_general_conversation: {e}")
        fallback_response = (
            "Извините, не совсем понял 🤔\n"
            "Попробуйте переформулировать или воспользуйтесь командой `/help`"
        )
        bot.messaging.send_message(peer, fallback_response)
        session.add_message(fallback_response, is_user=False)

def handle_command(update: UpdateMessage, session: UserSession, text: str):
    """Обработка команд"""
    command = text[1:].lower()
    
    command_handlers = {
        "start": start_handler,
        "idea": smart_idea_handler,
        "ai_agent": agent_handler,
        "group": search_owners_handler,
        "search_owners": search_owners_handler,
        "help_idea": help_idea_handler,
        "consultation": consultation_handler,
        "help": help_handler,
    }
    
    if command in command_handlers:
        command_handlers[command](update)
    else:
        help_text = (
        "❓ Доступные команды:\n\n"
        "• `/start` — главное меню\n"
        "• `/idea` — проработать идею (шаблон / свободно)\n"
        "• `/ai_agent` — список доступных ИИ-агентов\n"
        "• `/search_owners` — поиск владельцев по запросу\n"
        "• `/help_idea` — сгенерировать идеи по теме\n"
        "• `/consultation` — заказать консультацию\n"
        "• `/help` — это сообщение\n\n"
        "Просто отправьте текст — я постараюсь ответить или предложить следующее действие."
    )
    bot.messaging.send_message(peer, help_text)
    session.add_message(help_text, is_user=False)
    session.mode = config['states']['main_menu']


def handle_ai_suggested_command(update: UpdateMessage, session: UserSession, command: str):
    """
    Выполнение команды, предложенной ИИ.
    Ожидается, что команда приходит в формате '/command' или просто 'command'.
    """
    peer = update.peer
    cmd = command.strip()
    if cmd.startswith('/'):
        cmd = cmd[1:]

    # Поддерживаем только безопасные команды из нашего списка
    safe_commands = {
        "start": start_handler,
        "idea": smart_idea_handler,
        "ai_agent": agent_handler,
        "search_owners": search_owners_handler,
        "help_idea": help_idea_handler,
        "consultation": consultation_handler,
        "help": help_handler,
    }

    if cmd in safe_commands:
        logging.info(f"Выполнение команды, предложенной ИИ: /{cmd}")
        safe_commands[cmd](update)
    else:
        bot.messaging.send_message(peer, f"ИИ предложил выполнить `{command}`, но такая команда не поддерживается.")


# --- Регистрация обработчиков и запуск бота ---

def register_handlers(bot_instance: DialogBot):
    """
    Пример регистрации обработчиков.
    В зависимости от версии dialog_bot_sdk может быть другой API — замените этот блок при необходимости.
    """
    try:
        # Регистрация текстовых сообщений
        # Если у вас есть способ регистрировать MessageHandler — используйте его.
        bot_instance.add_message_handler(MessageHandler(enhanced_text_handler, MessageContentType.TEXT_MESSAGE))

        # Регистрация команд (на случай, если SDK поддерживает CommandHandler)
        bot_instance.add_command_handler(CommandHandler(start_handler, 'start'))
        bot_instance.add_command_handler(CommandHandler(smart_idea_handler, 'idea'))
        bot_instance.add_command_handler(CommandHandler(agent_handler, 'ai_agent'))
        bot_instance.add_command_handler(CommandHandler(search_owners_handler, 'search_owners'))
        bot_instance.add_command_handler(CommandHandler(help_idea_handler, 'help_idea'))
        bot_instance.add_command_handler(CommandHandler(consultation_handler, 'consultation'))
        bot_instance.add_command_handler(CommandHandler(help_handler, 'help'))

        logging.info("✅ Обработчики зарегистрированы")
    except Exception as e:
        # Если API регистрации другое — логируем, но продолжаем
        logging.warning(f"Не удалось автоматически зарегистрировать обработчики: {e}")
        logging.info("Если ваш SDK использует другой способ регистрации — замените вызов register_handlers соответствующим кодом.")


def main():
    global bot
    if not BOT_TOKEN:
        logging.critical("DIALOG_BOT_TOKEN не найден в окружении. Останов.")
        raise RuntimeError("DIALOG_BOT_TOKEN не задан")

    bot = DialogBot(BOT_TOKEN)
    register_handlers(bot)

    logging.info("Бот запущен. Ожидание сообщений...")
    try:
        # В зависимости от SDK — возможно есть метод run(), start_polling() или что-то подобное.
        # Попробуйте заменить на нужный вызов. Здесь общий пример:
        bot.run_forever()  # <- замените на bot.run() / bot.polling_loop() / bot.start() в зависимости от SDK
    except AttributeError:
        # Если у объекта нет run_forever — используем альтернативу
        try:
            bot.run()
        except Exception as e:
            logging.error(f"Не удалось запустить бота: {e}")
            raise

if __name__ == "__main__":
    main()