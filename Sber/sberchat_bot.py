import os
import json
import logging
from dotenv import load_dotenv
from dialog_bot_sdk.bot import DialogBot
from dialog_bot_sdk.entities.messaging import UpdateMessage, MessageContentType
from dialog_bot_sdk.entities.messaging import MessageHandler, CommandHandler
from openpyxl import load_workbook, Workbook

from ai_agent import (
    check_general_message_with_gigachat,
    check_idea_with_gigachat_local,
    generate_files,
    generate_agents_summary_file,
    find_agent_owners,
    generate_idea_suggestions,
    calculate_work_cost,
    generate_idea_evaluation_diagram,  # НОВЫЙ ИМПОРТ
    # Убираем импорт функций для команд памяти
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

def send_file(peer, file_path, text=None, name=None):
    """Отправка файла с возможным описанием"""
    try:
        logging.info(f"📤 Отправка файла: {file_path}")
        with open(file_path, "rb") as f:
            bot.messaging.send_file_sync(
                peer,
                f,
                name=name or os.path.basename(file_path),
                caption=text or ""
            )
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка отправки файла {file_path}: {e}")
        return False

# НОВАЯ ФУНКЦИЯ для отправки изображений
def send_image(peer, image_path, caption=None):
    """Отправка изображения через бота"""
    try:
        logging.info(f"📤 Отправка изображения: {image_path}")
        with open(image_path, "rb") as f:
            bot.messaging.send_file_sync(
                peer,
                f,
                name=os.path.basename(image_path),
                caption=caption or ""
            )
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка отправки изображения {image_path}: {e}")
        return False

def start_handler(update: UpdateMessage):
    user_id = update.peer.id
    user_states[user_id] = {"mode": config['states']['main_menu']}
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['start']['response'])

def idea_handler(update: UpdateMessage):
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

def agent_handler(update: UpdateMessage):
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

        if not send_file(peer, agents_file_path):
            bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_error'].format(file_type="основной"))

        if summary_file and os.path.exists(summary_file):
            if not send_file(peer, summary_file, text="📊 Аналитический отчет"):
                bot.messaging.send_message(peer, config['bot_settings']['commands']['ai_agent']['responses']['file_error'].format(file_type="аналитический"))
            try:
                os.remove(summary_file)
            except Exception as e:
                logging.warning(f"Не удалось удалить временный файл: {e}")

    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
        bot.messaging.send_message(peer, config['error_messages']['file_error'].format(error=e))

def search_owners_handler(update: UpdateMessage):
    peer = update.peer
    user_id = peer.id
    try:
        agents_file_path = config['file_settings']['agents_file']
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, config['error_messages']['file_not_found'])
            return

        wb = load_workbook(agents_file_path)
        sheet = wb.active
        headers = [cell.value for cell in sheet[1]]
        agents_data = [dict(zip(headers, row)) for row in sheet.iter_rows(min_row=2, values_only=True)]

        user_states[user_id] = {
            "mode": config['states']['search_owners'],
            "agents_data": agents_data
        }
        bot.messaging.send_message(peer, f"✅ Файл {os.path.basename(agents_file_path)} успешно загружен!\n\n💬 Теперь опишите свободно, что вас интересует...")
    except Exception as e:
        logging.error(f"Ошибка в search_owners_handler: {e}")
        bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))

def consultation_handler(update: UpdateMessage):
    peer = update.peer
    user_id = peer.id
    user_states[user_id] = {"mode": config['states']['main_menu']}
    bot.messaging.send_message(peer, config['bot_settings']['commands']['consultation']['response'])

def help_handler(update: UpdateMessage):
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['help']['response'])

# Функции для работы с памятью (только для внутреннего использования)
# Память теперь работает автоматически без команд пользователя

def process_template_idea(update: UpdateMessage, user_id: int):
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
            state["idea_data"]["user_id"] = user_id
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(text, state["idea_data"], is_free_form=False)
            cost_info = calculate_work_cost(state["idea_data"], is_unique)
            
            # === НОВЫЙ КОД: Генерация и отправка диаграммы ===
            try:
                diagram_path = generate_idea_evaluation_diagram(state["idea_data"], is_unique, parsed_data)
                if diagram_path and os.path.exists(diagram_path):
                    logging.info(f"📊 Отправка диаграммы оценки: {diagram_path}")
                    send_image(peer, diagram_path, "📊 Диаграмма оценки идеи")
                    try:
                        os.remove(diagram_path)  # Удаляем временный файл
                        logging.info(f"🗑️ Временный файл диаграммы удален: {diagram_path}")
                    except Exception as cleanup_error:
                        logging.warning(f"Не удалось удалить файл диаграммы: {cleanup_error}")
                else:
                    logging.warning("Диаграмма не была создана")
            except Exception as diagram_error:
                logging.error(f"Ошибка при создании диаграммы: {diagram_error}")
                # Продолжаем работу даже если диаграмма не создалась
            # === КОНЕЦ НОВОГО КОДА ===
            
            bot.messaging.send_message(peer, f"🧠 **Результат анализа:**\n\n{response}\n\n{cost_info}")

            if state["idea_data"]:
                word_path, excel_path = generate_files(state["idea_data"], cost_info)
                bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['files_ready'])
                send_file(peer, word_path, text="📄 Техническое описание")
                send_file(peer, excel_path, text="📊 Структурированные данные")
                try:
                    os.remove(word_path)
                    os.remove(excel_path)
                except:
                    pass

            user_states[user_id] = {"mode": config['states']['main_menu']}
        except Exception as e:
            logging.error(f"Ошибка при обработке шаблонной идеи: {e}")
            bot.messaging.send_message(peer, config['error_messages']['analysis_error'].format(error=e))
            user_states[user_id] = {"mode": config['states']['main_menu']}

def text_handler(update: UpdateMessage, widget=None):
    if not update.message or not update.message.text_message:
        return
    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer
    state = user_states.get(user_id, {"mode": config['states']['main_menu']})

    # Логирование для отладки
    logging.info(f"[User {user_id}] Message: {text[:100]}...")  # Первые 100 символов

    # Спецрежимы (остаются без изменений, но теперь с поддержкой памяти)
    if state["mode"] == config['states']['idea_choose_format']:
        if "шаблон" in text.lower():
            state["mode"] = config['states']['idea_template']
            state["current_field"] = 0
            state["idea_data"] = {}
            process_template_idea(update, user_id)
        elif "сам" in text.lower():
            state["mode"] = config['states']['idea_free_form']
            bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['free_form_prompt'])
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
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(text, user_data, is_free_form=True)
            cost_info = calculate_work_cost(parsed_data or user_data, is_unique)
            
            # === НОВЫЙ КОД: Генерация и отправка диаграммы для свободной формы ===
            try:
                diagram_path = generate_idea_evaluation_diagram(user_data, is_unique, parsed_data)
                if diagram_path and os.path.exists(diagram_path):
                    logging.info(f"📊 Отправка диаграммы оценки: {diagram_path}")
                    send_image(peer, diagram_path, "📊 Диаграмма оценки идеи")
                    try:
                        os.remove(diagram_path)  # Удаляем временный файл
                        logging.info(f"🗑️ Временный файл диаграммы удален: {diagram_path}")
                    except Exception as cleanup_error:
                        logging.warning(f"Не удалось удалить файл диаграммы: {cleanup_error}")
                else:
                    logging.warning("Диаграмма не была создана")
            except Exception as diagram_error:
                logging.error(f"Ошибка при создании диаграммы: {diagram_error}")
                # Продолжаем работу даже если диаграмма не создалась
            # === КОНЕЦ НОВОГО КОДА ===
            
            bot.messaging.send_message(peer, f"🧠 **Результат анализа:**\n\n{response}\n\n{cost_info}")
            
            if parsed_data:
                word_path, excel_path = generate_files(parsed_data, cost_info)
                bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['files_ready'])
                send_file(peer, word_path, text="📄 Техническое описание")
                send_file(peer, excel_path, text="📊 Структурированные данные")
                try:
                    os.remove(word_path)
                    os.remove(excel_path)
                except:
                    pass
            user_states[user_id] = {"mode": config['states']['main_menu']}
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
        except Exception as e:
            logging.error(f"Ошибка при генерации идей: {e}")
            bot.messaging.send_message(peer, config['error_messages']['general_error'].format(error=e))
        user_states[user_id] = {"mode": config['states']['main_menu']}
        return

    # Обычный диалог через GigaChat с использованием памяти
    try:
        logging.info(f"[User {user_id}] Sending to GigaChat with memory...")
        gpt_response, detected_command = check_general_message_with_gigachat(text, user_id)
        
        if detected_command:
            logging.info(f"[User {user_id}] Detected command: {detected_command}")
            # Выполняем только команду, без повторного текста от GPT
            if detected_command == "start":
                start_handler(update)
            elif detected_command == "ai_agent":
                agent_handler(update)
            elif detected_command == "search_owners":
                search_owners_handler(update)
            elif detected_command == "idea":
                idea_handler(update)
            elif detected_command == "consultation":
                consultation_handler(update)
            elif detected_command == "help":
                help_handler(update)
        else:
            if gpt_response and gpt_response.strip():
                # Отправляем ответ пользователю
                bot.messaging.send_message(peer, gpt_response)
                logging.info(f"[User {user_id}] Response sent successfully")
            else:
                fallback_msg = "🤔 Не совсем понял ваш вопрос. Попробуйте иначе или используйте /help"
                bot.messaging.send_message(peer, fallback_msg)
                logging.info(f"[User {user_id}] Fallback response sent")
                
    except Exception as e:
        error_msg = f"⚠️ Произошла ошибка при обработке сообщения: {str(e)}"
        logging.error(f"[User {user_id}] Error in text_handler: {e}")
        bot.messaging.send_message(peer, error_msg)

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": config['bot_settings']['endpoint'],
        "token": BOT_TOKEN,
        "is_secure": config['bot_settings']['is_secure'],
    })
    
    handlers = []
    
    # Основные команды из конфига
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
    
    logging.info("🤖 Бот запущен с поддержкой памяти диалогов!")
    logging.info("🧠 GigaChat будет автоматически помнить последние 10 сообщений каждого пользователя")
    logging.info("📊 Включена поддержка диаграмм оценки идей!")  # НОВОЕ СООБЩЕНИЕ
    
    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()