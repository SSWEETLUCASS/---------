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

user_states = {}
bot = None

def get_user_name(update: UpdateMessage) -> str:
    try:
        sender = update.message.sender_data
        return f"{sender.name} {sender.nick}" if sender else f"ID:{update.peer.id}"
    except Exception:
        return f"ID:{update.peer.id}"

def send_file(peer, file_path, text=None, name=None):
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

        send_file(peer, agents_file_path)
        if summary_file and os.path.exists(summary_file):
            send_file(peer, summary_file, text="📊 Аналитический отчет")
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

def help_idea_handler(update: UpdateMessage):
    peer = update.peer
    user_id = peer.id
    user_states[user_id] = {"mode": config['states']['help_with_ideas']}
    bot.messaging.send_message(peer, config['bot_settings']['commands']['help_idea']['responses']['initial'])

def consultation_handler(update: UpdateMessage):
    peer = update.peer
    user_id = peer.id
    user_states[user_id] = {"mode": config['states']['main_menu']}
    bot.messaging.send_message(peer, config['bot_settings']['commands']['consultation']['response'])

def help_handler(update: UpdateMessage):
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['help']['response'])

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
            response, is_unique, parsed_data, _, _ = check_idea_with_gigachat_local(text, state["idea_data"], is_free_form=False)
            cost_info = calculate_work_cost(parsed_data, is_unique)
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

def is_idea_text(text: str) -> bool:
    idea_keywords = ["идея", "хочу автоматизировать", "надо сделать", "предлагаю", "улучшить", "оптимизировать"]
    return len(text) > 15 and any(k in text.lower() for k in idea_keywords)

def text_handler(update: UpdateMessage, widget=None):
    if not update.message or not update.message.text_message:
        return
    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer
    user_name = get_user_name(update)
    state = user_states.get(user_id, {"mode": config['states']['main_menu']})

    logging.info(f"📩 [{user_name}] ({user_id}): {text}")
    logging.info(f"📊 Состояние: {state}")

    # Обработка режимов
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

    elif state["mode"] == config['states']['idea_free_form'] or is_idea_text(text):
        bot.messaging.send_message(peer, config['bot_settings']['commands']['idea']['responses']['processing'])
        try:
            user_data = {"Описание в свободной форме": text, "user_id": user_id}
            response, is_unique, parsed_data, _, _ = check_idea_with_gigachat_local(text, user_data, is_free_form=True)
            cost_info = calculate_work_cost(parsed_data or user_data, is_unique)
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

    # Обычный диалог
    try:
        gpt_response, detected_command, _ = check_general_message_with_gigachat(text, user_id)
        if detected_command:
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
        elif gpt_response and gpt_response.strip():
            bot.messaging.send_message(peer, gpt_response)
        else:
            bot.messaging.send_message(peer, "🤔 Не совсем понял ваш вопрос. Попробуйте иначе или используйте /help")
    except Exception as e:
        logging.error(f"Ошибка в text_handler: {e}")
        bot.messaging.send_message(peer, "⚠️ Произошла ошибка при обработке сообщения.")

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": config['bot_settings']['endpoint'],
        "token": BOT_TOKEN,
        "is_secure": config['bot_settings']['is_secure'],
    })
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
