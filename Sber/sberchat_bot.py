import os
import json
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, MessageContentType
from dialog_bot_sdk.entities.messaging import MessageHandler, CommandHandler
from dialog_bot_sdk.entities.messaging import UpdateMessage

from openpyxl import load_workbook, Workbook

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
    level=config['logging']['level'],
    format=config['logging']['format'],
    filename=config['logging']['file']
)

# Глобальные переменные
user_states = {}
bot = None

def send_file_sync(peer, file_path, text=None, name=None):
    """Синхронная отправка файла в чат через правильный API"""
    try:
        logging.info(f"🔄 Отправляем файл: {name or file_path}")
        
        # Проверяем размер файла
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            logging.info(f"📊 Размер файла: {file_size} байт")
            
            if file_size == 0:
                logging.warning("⚠️ Файл пуст!")
                return None
        
        # Читаем файл в байты
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        
        # Используем правильный метод отправки
        result = bot.messaging.send_file_sync(
            peer=peer,
            file=file_bytes,
            text=text,
            name=name or os.path.basename(file_path),
            is_forward_ban=True
        )
        
        logging.info(f"✅ Файл успешно отправлен: {result}")
        return result
        
    except Exception as e:
        logging.error(f"❌ Ошибка отправки файла: {e}")
        return None

def start_handler(update: UpdateMessage) -> None:
    """Обработчик команды /start - переводит в режим свободного диалога"""
    user_id = update.peer.id
    user_states[user_id] = {"mode": "free_dialog"}
    bot.messaging.send_message(update.peer, 
        "👋 Привет! Я Агентолог - ваш помощник по AI-агентам.\n\n"
        "💬 Просто общайтесь со мной свободно! Расскажите:\n"
        "• Есть ли у вас идеи для автоматизации?\n"
        "• Интересуют ли вас существующие AI-агенты?\n"
        "• Нужна ли помощь с чем-то еще?\n\n"
        "Я понимаю естественную речь и помогу вам! 🤖"
    )

def help_handler(update: UpdateMessage) -> None:
    """Обработчик команды помощи"""
    bot.messaging.send_message(update.peer, 
        "🆘 **Помощь по работе с ботом**\n\n"
        "Я работаю в режиме свободного диалога! Просто пишите мне как обычному собеседнику.\n\n"
        "🔹 **Что я умею:**\n"
        "• Помогаю с идеями для AI-агентов\n"
        "• Показываю существующие агенты\n"
        "• Ищу подходящих владельцев агентов\n"
        "• Генерирую предложения для автоматизации\n"
        "• Веду обычный диалог и консультирую\n\n"
        "💬 **Примеры фраз:**\n"
        "• \"Привет! У меня есть идея для автоматизации\"\n"
        "• \"Покажи что у вас есть из агентов\"\n"
        "• \"Кто занимается аналитикой?\"\n"
        "• \"Помоги придумать идею\"\n"
        "• \"Нужна консультация\"\n\n"
        "Просто говорите со мной естественно! 😊"
    )

def execute_action_from_dialog(action: str, update: UpdateMessage, context_data: dict = None):
    """Выполнение действия, предложенного в диалоге"""
    peer = update.peer
    user_id = peer.id
    
    try:
        if action == "show_agents":
            # Показать список агентов
            agents_file_path = config['file_settings']['agents_file']
            if not os.path.exists(agents_file_path):
                bot.messaging.send_message(peer, "📋 Создаю файл с агентами...")
                wb = Workbook()
                ws = wb.active
                ws.append(["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"])
                wb.save(agents_file_path)
            
            summary_file = generate_agents_summary_file(agents_file_path)
            
            # Отправляем основной файл
            result1 = send_file_sync(peer, agents_file_path, text="📋 Вот список всех наших агентов!", name="agents.xlsx")
            if not result1:
                bot.messaging.send_message(peer, "⚠️ Не удалось отправить основной файл")
            
            # Отправляем аналитический файл если он создан
            if summary_file and os.path.exists(summary_file):
                result2 = send_file_sync(peer, summary_file, text="📊 И аналитический отчет", name=os.path.basename(summary_file))
                if result2:
                    try:
                        os.remove(summary_file)
                    except Exception as e:
                        logging.warning(f"Не удалось удалить временный файл: {e}")
                        
        elif action == "process_idea_template":
            # Начать заполнение шаблона идеи
            user_states[user_id] = {
                "mode": "idea_template",
                "current_field": 0,
                "idea_data": context_data or {}
            }
            process_template_idea(update, user_id)
            
        elif action == "process_idea_free":
            # Обработать идею в свободной форме
            if context_data and "idea_text" in context_data:
                process_free_form_idea(update, context_data["idea_text"], user_id)
            else:
                user_states[user_id] = {"mode": "idea_free_form"}
                bot.messaging.send_message(peer, "💡 Отлично! Опишите вашу идею подробно - я её проанализирую!")
                
        elif action == "search_owners":
            # Поиск владельцев
            if context_data and "search_query" in context_data:
                search_result = find_agent_owners(context_data["search_query"])
                bot.messaging.send_message(peer, search_result)
            else:
                user_states[user_id] = {"mode": "search_owners_dialog"}
                bot.messaging.send_message(peer, "🔍 Конечно! Опишите, что именно вас интересует - я найду подходящих владельцев агентов.")
                
        elif action == "generate_ideas":
            # Генерация идей
            if context_data and "domain" in context_data:
                ideas = generate_idea_suggestions(context_data["domain"])
                bot.messaging.send_message(peer, f"💡 **Вот идеи специально для вас:**\n\n{ideas}")
            else:
                user_states[user_id] = {"mode": "generate_ideas_dialog"}
                bot.messaging.send_message(peer, "🌟 Конечно! В какой области вы хотели бы получить идеи для автоматизации?")
                
        elif action == "consultation":
            # Консультация
            bot.messaging.send_message(peer, config['bot_settings']['commands']['consultation']['response'])
            
    except Exception as e:
        logging.error(f"Ошибка при выполнении действия {action}: {e}")
        bot.messaging.send_message(peer, f"⚠️ Произошла ошибка: {e}")

def process_template_idea(update: UpdateMessage, user_id: int) -> None:
    """Обработка идеи по шаблону (поэтапно)"""
    peer = update.peer
    text = update.message.text_message.text.strip() if update.message and update.message.text_message else ""
    
    state = user_states[user_id]
    current_field = state["current_field"]
    
    if current_field > 0 and text:
        field_name = config['template_fields'][current_field - 1]
        state["idea_data"][field_name] = text
    
    if current_field < len(config['template_fields']):
        field_name = config['template_fields'][current_field]
        bot.messaging.send_message(peer, f"📝 **{field_name}**\n\nОпишите этот аспект вашей идеи:")
        state["current_field"] += 1
    else:
        # Завершаем заполнение шаблона
        bot.messaging.send_message(peer, "✅ Отлично! Анализирую вашу идею...")
        
        try:
            state["idea_data"]["user_id"] = user_id
            
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, state["idea_data"], is_free_form=False
            )
            
            cost_info = calculate_work_cost(state["idea_data"], is_unique)
            full_response = f"🧠 **Результат анализа:**\n\n{response}\n\n{cost_info}"
            bot.messaging.send_message(peer, full_response)
            
            if state["idea_data"]:
                generate_and_send_files(peer, state["idea_data"], cost_info)
            
            user_states[user_id] = {"mode": "free_dialog"}
            bot.messaging.send_message(peer, "\n💬 Есть еще вопросы или идеи? Спрашивайте!")
            
        except Exception as e:
            logging.error(f"Ошибка при обработке шаблонной идеи: {e}")
            bot.messaging.send_message(peer, f"⚠️ Ошибка при анализе: {e}")
            user_states[user_id] = {"mode": "free_dialog"}

def process_free_form_idea(update: UpdateMessage, idea_text: str, user_id: int):
    """Обработка идеи в свободной форме"""
    peer = update.peer
    
    bot.messaging.send_message(peer, "🤖 Анализирую вашу идею...")
    
    try:
        user_data = {"Описание в свободной форме": idea_text, "user_id": user_id}
        response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
            idea_text, user_data, is_free_form=True
        )
        
        cost_info = calculate_work_cost(parsed_data or user_data, is_unique)
        full_response = f"🧠 **Результат анализа:**\n\n{response}\n\n{cost_info}"
        bot.messaging.send_message(peer, full_response)
        
        if parsed_data:
            generate_and_send_files(peer, parsed_data, cost_info)
        
        user_states[user_id] = {"mode": "free_dialog"}
        bot.messaging.send_message(peer, "\n💬 Как вам результат? Есть вопросы или другие идеи?")
        
    except Exception as e:
        logging.error(f"Ошибка при обработке свободной идеи: {e}")
        bot.messaging.send_message(peer, f"⚠️ Ошибка при анализе: {e}")
        user_states[user_id] = {"mode": "free_dialog"}

def generate_and_send_files(peer, data, cost_info):
    """Генерация и отправка файлов"""
    try:
        word_path, excel_path = generate_files(data, cost_info)
        bot.messaging.send_message(peer, "📄 Готовлю файлы для вас...")
        
        # Отправляем Word файл
        result1 = send_file_sync(peer, word_path, text="📄 Техническое описание", name=os.path.basename(word_path))
        if not result1:
            bot.messaging.send_message(peer, "⚠️ Не удалось отправить Word файл")
        
        # Отправляем Excel файл
        result2 = send_file_sync(peer, excel_path, text="📊 Структурированные данные", name=os.path.basename(excel_path))
        if not result2:
            bot.messaging.send_message(peer, "⚠️ Не удалось отправить Excel файл")
        
        # Удаляем временные файлы
        try:
            os.remove(word_path)
            os.remove(excel_path)
        except Exception as e:
            logging.warning(f"Не удалось удалить временные файлы: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка при генерации файлов: {e}")
        bot.messaging.send_message(peer, f"⚠️ Ошибка при создании файлов: {e}")

def text_handler(update: UpdateMessage, widget=None):
    """Основной обработчик текстовых сообщений - полностью диалоговый режим"""
    if not update.message or not update.message.text_message:
        return

    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer
    state = user_states.get(user_id, {"mode": "free_dialog"})
    
    logging.info(f"📩 Пользователь {user_id}: {text}")
    logging.info(f"📊 Состояние: {state}")

    # Обработка команд (только основные)
    if text.startswith('/'):
        command = text[1:].lower()
        if command == "start":
            start_handler(update)
            return
        elif command == "help":
            help_handler(update)
            return
        # Остальные команды убираем - все через диалог

    # Специальные состояния для поэтапной работы
    if state["mode"] == "idea_template":
        process_template_idea(update, user_id)
        return
    
    elif state["mode"] == "idea_free_form":
        process_free_form_idea(update, text, user_id)
        return
    
    elif state["mode"] == "search_owners_dialog":
        search_result = find_agent_owners(text)
        bot.messaging.send_message(peer, search_result)
        user_states[user_id] = {"mode": "free_dialog"}
        bot.messaging.send_message(peer, "\n💬 Нашли нужное? Есть еще вопросы?")
        return
        
    elif state["mode"] == "generate_ideas_dialog":
        ideas = generate_idea_suggestions(text)
        bot.messaging.send_message(peer, f"💡 **Вот идеи для вас:**\n\n{ideas}")
        user_states[user_id] = {"mode": "free_dialog"}
        bot.messaging.send_message(peer, "\n🔹 Понравилась какая-то идея? Расскажите больше!")
        return

    # Основной диалоговый режим
    try:
        logging.info(f"🤖 Отправляем в GigaChat для диалога: {text}")
        
        # Получаем ответ и возможные действия от GigaChat
        gpt_response, suggested_action, context_data = check_general_message_with_gigachat(text, user_id)
        
        logging.info(f"🔎 Ответ GigaChat: '{gpt_response}', Предложенное действие: {suggested_action}")

        # Всегда сначала отправляем диалоговый ответ
        if gpt_response and gpt_response.strip():
            bot.messaging.send_message(peer, gpt_response)
        
        # Если есть предложенное действие, выполняем его
        if suggested_action:
            execute_action_from_dialog(suggested_action, update, context_data)
        
    except Exception as e:
        logging.error(f"❌ Ошибка в text_handler: {e}")
        bot.messaging.send_message(peer, 
            "⚠️ Произошла ошибка при обработке сообщения.\n\n"
            "💬 Попробуйте переформулировать вопрос или напишите /help для получения помощи."
        )

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": config['bot_settings']['endpoint'],
        "token": BOT_TOKEN,
        "is_secure": config['bot_settings']['is_secure'],
    })

    # Регистрируем только основные команды
    bot.messaging.command_handler([
        CommandHandler(start_handler, "start"),
        CommandHandler(help_handler, "help"),
    ])
    
    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)
    ])

    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()