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

def send_file(message: UpdateMessage,file_path) -> None:
    """Синхронная отправка файла в чат через правильный API"""
    try:
        logging.info(f"🔄 Отправляем файл: {file_path}")
        
        bot.messaging.send_file_sync(message.peer,file_path)

        logging.info(f"✅ Файл успешно отправлен: {file_path}")

    except Exception as e:
        logging.error(f"❌ Ошибка отправки файла: {e}")
        return None

def start_handler(update: UpdateMessage) -> None:
    """Обработчик команды /start"""
    user_id = update.peer.id
    user_states[user_id] = {"mode": config['states']['main_menu']}
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['start']['response'])

def idea_handler(update: UpdateMessage) -> None:
    """Обработчик для работы с идеями"""
    peer = update.peer
    user_id = peer.id
    
    if user_id in user_states and user_states[user_id].get("mode", "").startswith("idea_"):
        bot.messaging.send_message(peer, config['error_messages']['already_in_process'])
        return
    
    user_states[user_id] = {
        "mode": config['states']['idea_choose_format'],
        "current_field": 0,
        "idea_data": {}
    }
    bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['initial'])

def agent_handler(update: UpdateMessage) -> None:
    """Обработчик для получения списка AI-агентов"""
    peer = update.peer
    
    try:
        agents_file_path = config['file_settings']['agents_file']
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_not_found'])
            wb = Workbook()
            ws = wb.active
            ws.append(["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"])
            wb.save(agents_file_path)
        
        summary_file = generate_agents_summary_file(agents_file_path)
        
        bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['initial'])
        
        # Отправляем основной файл
        result1 = send_file(peer, path="agents.xlsx")
        if not result1:
            bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_error'].format(file_type="основной"))
        
        # Отправляем аналитический файл если он создан
        if summary_file and os.path.exists(summary_file):
            result2 = send_file(peer, summary_file, text="📊 Аналитический отчет", name=os.path.basename(summary_file))
            if not result2:
                bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_error'].format(file_type="аналитический"))
            
            # Удаляем временный файл
            try:
                os.remove(summary_file)
            except Exception as e:
                logging.warning(f"Не удалось удалить временный файл: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error=e))

def search_owners_handler(update: UpdateMessage) -> None:
    """Обработчик для поиска владельцев агентов по локальному файлу agents.xlsx"""
    peer = update.peer
    user_id = peer.id

    try:
        agents_file_path = config['file_settings']['agents_file']

        # Проверка наличия файла
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, config['error_messages']['file_not_found'])
            return

        # Загружаем Excel
        wb = load_workbook(agents_file_path)
        sheet = wb.active

        # Читаем заголовки
        headers = [cell.value for cell in sheet[1]]

        # Читаем строки в список словарей
        agents_data = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            row_dict = dict(zip(headers, row))
            agents_data.append(row_dict)

        # Сохраняем состояние пользователя
        user_states[user_id] = {
            "mode": config['states']['search_owners'],
            "agents_data": agents_data
        }

        # Сообщаем пользователю, что данные загружены
        bot.messaging.send_message(
            peer,
            f"✅ Файл {os.path.basename(agents_file_path)} успешно загружен!\n\n"
            "💬 Теперь опишите свободно, что вас интересует:\n"
            "• Кто занимается аналитикой?\n"
            "• Найти агента для автоматизации документов\n"
            "• Покажи всех владельцев\n"
            "• И любые другие вопросы..."
        )

    except Exception as e:
        logging.error(f"Ошибка в search_owners_handler: {e}")
        bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))

def help_idea_handler(update: UpdateMessage) -> None:
    """Обработчик для помощи с генерацией идей"""
    peer = update.peer
    user_id = peer.id
    
    user_states[user_id] = {"mode": config['states']['help_with_ideas']}
    bot.messaging.send_message(peer, config['bot_settings']['commands']['help_idea']['responses']['initial'])

def consultation_handler(update: UpdateMessage) -> None:
    """Обработчик для консультации и полезных ссылок"""
    peer = update.peer
    user_id = peer.id
    
    user_states[user_id] = {"mode": config['states']['main_menu']}
    bot.messaging.send_message(peer, config['bot_settings']['commands']['consultation']['response'])

def help_handler(update: UpdateMessage) -> None:
    """Обработчик команды помощи"""
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['help']['response'])

def process_template_idea(update: UpdateMessage, user_id: int) -> None:
    """Обработка идеи по шаблону (поэтапно)"""
    peer = update.peer
    text = update.message.text_message.text.strip()
    
    state = user_states[user_id]
    current_field = state["current_field"]
    
    if current_field > 0:
        field_name = config['template_fields'][current_field - 1]
        state["idea_data"][field_name] = text
    
    if current_field < len(config['template_fields']):
        field_name = config['template_fields'][current_field]
        bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['template_field'].format(field=field_name))
        state["current_field"] += 1
    else:
        bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['complete'])
        
        try:
            # Добавляем user_id в данные для отслеживания истории
            state["idea_data"]["user_id"] = user_id
            
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, state["idea_data"], is_free_form=False
            )
            
            cost_info = calculate_work_cost(state["idea_data"], is_unique)
            full_response = f"🧠 **Результат анализа:**\n\n{response}\n\n{cost_info}"
            bot.messaging.send_message(peer, full_response)
            
            if state["idea_data"]:
                word_path, excel_path = generate_files(state["idea_data"], cost_info)
                bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['files_ready'])
                
                # Отправляем Word файл
                result1 = send_file_sync(peer, word_path, text="📄 Техническое описание", name=os.path.basename(word_path))
                if not result1:
                    bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Word"))
                
                # Отправляем Excel файл
                result2 = send_file_sync(peer, excel_path, text="📊 Структурированные данные", name=os.path.basename(excel_path))
                if not result2:
                    bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Excel"))
                
                # Удаляем временные файлы
                try:
                    os.remove(word_path)
                    os.remove(excel_path)
                except Exception as e:
                    logging.warning(f"Не удалось удалить временные файлы: {e}")
            
            user_states[user_id] = {"mode": config['states']['main_menu']}
            bot.messaging.send_message(peer, "\n🔄 Для новой проверки напишите `/start`")
            
        except Exception as e:
            logging.error(f"Ошибка при обработке шаблонной идеи: {e}")
            bot.messaging.send_message(peer, config['error_messages']['analysis_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}

def text_handler(update: UpdateMessage, widget=None):
    """Основной обработчик текстовых сообщений"""
    if not update.message or not update.message.text_message:
        return

    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer
    state = user_states.get(user_id, {"mode": config['states']['main_menu']})
    
    logging.info(f"📩 Пользователь {user_id}: {text}")
    logging.info(f"📊 Состояние: {state}")

    # Обработка специальных состояний ПЕРВЫМ ПРИОРИТЕТОМ
    if state["mode"] == config['states']['idea_choose_format']:
        if "шаблон" in text.lower():
            state["mode"] = config['states']['idea_template']
            state["current_field"] = 0
            state["idea_data"] = {}
            process_template_idea(update, user_id)
            return
        elif "сам" in text.lower():
            state["mode"] = config['states']['idea_free_form']
            bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['free_form_prompt'])
            return
        else:
            bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['template_choice_error'])
            return
    
    elif state["mode"] == config['states']['idea_template']:
        process_template_idea(update, user_id)
        return
    
    elif state["mode"] == config['states']['idea_free_form']:
        bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['processing'])
        
        try:
            user_data = {"Описание в свободной форме": text, "user_id": user_id}
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, user_data, is_free_form=True
            )
            
            cost_info = calculate_work_cost(parsed_data or user_data, is_unique)
            full_response = f"🧠 **Результат анализа:**\n\n{response}\n\n{cost_info}"
            bot.messaging.send_message(peer, full_response)
            
            if parsed_data:
                word_path, excel_path = generate_files(parsed_data, cost_info)
                bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['files_ready'])
                
                # Отправляем Word файл
                result1 = send_file_sync(peer, word_path, text="📄 Техническое описание", name=os.path.basename(word_path))
                if not result1:
                    bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Word"))
                
                # Отправляем Excel файл
                result2 = send_file_sync(peer, excel_path, text="📊 Структурированные данные", name=os.path.basename(excel_path))
                if not result2:
                    bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Excel"))
                
                # Удаляем временные файлы
                try:
                    os.remove(word_path)
                    os.remove(excel_path)
                except Exception as e:
                    logging.warning(f"Не удалось удалить временные файлы: {e}")
            
            user_states[user_id] = {"mode": config['states']['main_menu']}
            bot.messaging.send_message(peer, "\n🔄 Для новой проверки напишите `/start`")
            
        except Exception as e:
            logging.error(f"Ошибка при обработке свободной идеи: {e}")
            bot.messaging.send_message(peer, config['error_messages']['analysis_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}
        return
    
    elif state["mode"] == config['states']['search_owners']:
        bot.messaging.send_message(peer, "🔍 Ищу подходящих владельцев...")
        
        try:
            owners_info = find_agent_owners(text)
            bot.messaging.send_message(peer, owners_info)
            
            user_states[user_id] = {"mode": config['states']['main_menu']}
            bot.messaging.send_message(peer, "\n💬 Есть еще вопросы? Спрашивайте свободно или используйте `/help` для списка команд!")
            
        except Exception as e:
            logging.error(f"Ошибка при поиске владельцев: {e}")
            bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}
        return

    elif state["mode"] == config['states']['help_with_ideas']:
        bot.messaging.send_message(peer, "💡 Генерирую идеи специально для вас...")
        
        try:
            ideas_response = generate_idea_suggestions(text)
            bot.messaging.send_message(peer, f"🎯 **Вот идеи для вас:**\n\n{ideas_response}")
            bot.messaging.send_message(peer, "\n🔹 Понравилась какая-то идея? Напишите `/idea` чтобы детально её проработать!")
            
            user_states[user_id] = {"mode": config['states']['main_menu']}
            
        except Exception as e:
            logging.error(f"Ошибка при генерации идей: {e}")
            bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}
        return

    # Обработка команд
    if text.startswith('/'):
        command = text[1:].lower()
        
        if command == "start":
            start_handler(update)
        elif command == "idea":
            idea_handler(update)
        elif command == "ai_agent":
            agent_handler(update)
        elif command in ["group", "search_owners"]:
            search_owners_handler(update)
        elif command == "help_idea":
            help_idea_handler(update)
        elif command == "consultation":
            consultation_handler(update)
        elif command == "help":
            help_handler(update)
        else:
            bot.messaging.send_message(peer, config['error_messages']['unknown_command'])
        return
    
    # Обработка обычных сообщений через GigaChat
    try:
        logging.info(f"🤖 Отправляем сообщение в GigaChat: {text}")
        gpt_response, detected_command = check_general_message_with_gigachat(text, user_id)
        logging.info(f"🔎 Ответ GigaChat: '{gpt_response}', Обнаружена команда: {detected_command}")

        # Если GigaChat обнаружил намерение выполнить команду
        if detected_command:
            logging.info(f"✅ Выполняем автоматически обнаруженную команду: {detected_command}")
            
            # Сначала отправляем ответ от GigaChat (если он не пустой)
            if gpt_response and gpt_response.strip():
                bot.messaging.send_message(peer, gpt_response)
            
            # Затем выполняем соответствующую команду
            if detected_command == "start":
                start_handler(update)
            elif detected_command == "ai_agent":
                agent_handler(update)
            elif detected_command == "search_owners":
                search_owners_handler(update)
            elif detected_command == "idea":
                idea_handler(update)
            elif detected_command == "help_idea":
                help_idea_handler(update)
            elif detected_command == "consultation":
                consultation_handler(update)
            elif detected_command == "help":
                help_handler(update)
        else:
            # Просто ведем обычный диалог
            if gpt_response and gpt_response.strip():
                logging.info("💬 Отправляем диалоговый ответ")
                bot.messaging.send_message(peer, gpt_response)
            else:
                logging.warning("⚠️ Пустой ответ от GigaChat")
                bot.messaging.send_message(peer, "🤔 Извините, не совсем понял ваш вопрос. Попробуйте переформулировать или используйте `/help` для списка команд.")
    
    except Exception as e:
        logging.error(f"❌ Ошибка в text_handler: {e}")
        bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при обработке сообщения. Попробуйте еще раз или обратитесь за помощью через `/help`")

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": config['bot_settings']['endpoint'],
        "token": BOT_TOKEN,
        "is_secure": config['bot_settings']['is_secure'],
    })

    # Регистрация команд из конфига
    handlers = []
    for cmd, cmd_data in config['bot_settings']['commands'].items():
        handler_func = globals()[cmd_data['handler']]
        handlers.append(CommandHandler(handler_func, cmd))
        if 'aliases' in cmd_data:
            for alias in cmd_data['aliases']:
                handlers.append(CommandHandler(handler_func, alias))
    
    bot.messaging.command_handler(handlers)
    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)
    ])

    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()