import os
import json
import logging
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
    level=config['logging']['level'],
    format=config['logging']['format'],
    filename=config['logging']['file']
)

# Глобальные переменные
user_states = {}
bot = None

def send_file_sync(
    bot_instance,
    peer,
    file,
    text: str = None,
    uid: int = None,
    name: str = None,
    verify: bool = None,
    is_forward_ban: bool = False,
    reply: list = None,
    forward: list = None,
    interactive_media_groups: list = None,
):
    """Синхронная отправка файла в чат"""
    try:
        logging.info(f"🔄 Отправляем файл: {name}")
        
        if hasattr(file, 'name') and os.path.exists(file.name):
            file_size = os.path.getsize(file.name)
            logging.info(f"📊 Размер файла: {file_size} байт")
            
            if file_size == 0:
                logging.warning("⚠️ Файл пуст!")
                return None
        
        result = bot_instance.messaging.send_file(
            peer=peer,
            file=file,
            message=text,
            file_name=name,
        )
        
        logging.info(f"✅ Файл успешно отправлен: {result}")
        return result
        
    except Exception as e:
        logging.error(f"❌ Ошибка отправки файла: {e}")
        try:
            result = bot_instance.messaging.send_filewrapped(
                peer,
                file,
                uid,
                text,
                name,
                verify,
                is_forward_ban,
                reply,
                forward,
                interactive_media_groups
            )
            logging.info(f"✅ Файл отправлен альтернативным методом: {result}")
            return result
        except Exception as e2:
            logging.error(f"❌ Ошибка альтернативной отправки: {e2}")
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
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"])
            wb.save(agents_file_path)
        
        summary_file = generate_agents_summary_file(agents_file_path)
        
        bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['initial'])
        
        with open(agents_file_path, "rb") as f:
            result1 = send_file_sync(bot, peer, f, name="agents.xlsx", text="📋 Основной файл с агентами")
            if not result1:
                bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_error'].format(file_type="основной"))
        
        if summary_file and os.path.exists(summary_file):
            with open(summary_file, "rb") as f:
                result2 = send_file_sync(bot, peer, f, name=os.path.basename(summary_file), text="📊 Аналитический отчет")
                if not result2:
                    bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_error'].format(file_type="аналитический"))
            
            try:
                os.remove(summary_file)
            except Exception as e:
                logging.warning(f"Не удалось удалить временный файл: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error=e))

def search_owners_handler(update: UpdateMessage) -> None:
    """Обработчик для поиска владельцев агентов"""
    peer = update.peer
    user_id = peer.id
    
    try:
        agents_file_path = config['file_settings']['agents_file']
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, config['error_messages']['file_not_found'])
            return
        
        user_states[user_id] = {"mode": config['states']['search_owners']}
        bot.messaging.send_message(peer, config['bot_settings']['commands']['search_owners']['responses']['initial'])
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
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, state["idea_data"], is_free_form=False
            )
            
            cost_info = calculate_work_cost(state["idea_data"], is_unique)
            full_response = f"🧠 **Результат анализа:**\n\n{response}\n\n💰 **Оценка стоимости:**\n{cost_info}"
            bot.messaging.send_message(peer, full_response)
            
            if state["idea_data"]:
                word_path, excel_path = generate_files(state["idea_data"], cost_info)
                bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['files_ready'])
                
                with open(word_path, "rb") as f_docx:
                    result1 = send_file_sync(bot, peer, f_docx, name=os.path.basename(word_path), text="📄 Техническое описание")
                    if not result1:
                        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Word"))
                
                with open(excel_path, "rb") as f_xlsx:
                    result2 = send_file_sync(bot, peer, f_xlsx, name=os.path.basename(excel_path), text="📊 Структурированные данные")
                    if not result2:
                        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Excel"))
                
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
            user_data = {"Описание в свободной форме": text}
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, user_data, is_free_form=True
            )
            
            cost_info = calculate_work_cost(parsed_data or user_data, is_unique)
            full_response = f"🧠 **Результат анализа:**\n\n{response}\n\n💰 **Оценка стоимости:**\n{cost_info}"
            bot.messaging.send_message(peer, full_response)
            
            if parsed_data:
                word_path, excel_path = generate_files(parsed_data, cost_info)
                bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['files_ready'])
                
                with open(word_path, "rb") as f_docx:
                    result1 = send_file_sync(bot, peer, f_docx, name=os.path.basename(word_path), text="📄 Техническое описание")
                    if not result1:
                        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Word"))
                
                with open(excel_path, "rb") as f_xlsx:
                    result2 = send_file_sync(bot, peer, f_xlsx, name=os.path.basename(excel_path), text="📊 Структурированные данные")
                    if not result2:
                        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error="Excel"))
                
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
        bot.messaging.send_message(peer, config['bot_settings']['commands']['search_owners']['responses']['searching'])
        
        try:
            owners_info = find_agent_owners(text)
            bot.messaging.send_message(peer, owners_info)
            
            user_states[user_id] = {"mode": config['states']['main_menu']}
            bot.messaging.send_message(peer, config['bot_settings']['commands']['search_owners']['responses']['new_search'])
            
        except Exception as e:
            logging.error(f"Ошибка при поиске владельцев: {e}")
            bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}
        return

    elif state["mode"] == config['states']['help_with_ideas']:
        bot.messaging.send_message(peer, config['bot_settings']['commands']['help_idea']['responses']['generating'])
        
        try:
            ideas_response = generate_idea_suggestions(text)
            bot.messaging.send_message(peer, config['bot_settings']['commands']['help_idea']['responses']['result'].format(ideas=ideas_response))
            bot.messaging.send_message(peer, "\n🔹 Понравилась какая-то идея? Напишите `/idea` чтобы детально её проработать!")
            
            user_states[user_id] = {"mode": config['states']['main_menu']}
            
        except Exception as e:
            logging.error(f"Ошибка при генерации идей: {e}")
            bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}
        return

    # Обработка общих сообщений
    try:
        if text.startswith('/'):
            command = text[1:].lower()
            cmd_config = config['bot_settings']['commands']
            
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
        
        gpt_response, is_maybe_idea, command = check_general_message_with_gigachat(text)
        logging.info(f"🔎 Ответ GigaChat: {gpt_response}, Идея: {is_maybe_idea}, CMD: {command}")

        if command:
            if command == "help":
                help_handler(update)
            elif command == "start":
                start_handler(update)
            elif command == "ai_agent":
                agent_handler(update)
            elif command == "search_owners":
                search_owners_handler(update)
            elif command == "idea":
                idea_handler(update)
            elif command == "help_idea":
                help_idea_handler(update)
            elif command == "consultation":
                consultation_handler(update)
            else:
                bot.messaging.send_message(peer, gpt_response or config['error_messages']['not_understood'])
        elif is_maybe_idea:
            bot.messaging.send_message(peer, f"{gpt_response}\n\n💡 Хотите проверить эту идею на уникальность? Напишите `/idea`")
        else:
            bot.messaging.send_message(peer, gpt_response or config['error_messages']['not_understood'])
    
    except Exception as e:
        logging.error(f"Ошибка в text_handler: {e}")
        bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))

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