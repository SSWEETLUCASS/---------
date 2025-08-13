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

# Унифицированная отправка файла
def send_file(update: UpdateMessage, file_path: str, caption: str = None, name: str = None):
    try:
        logging.info(f"📤 Отправка файла: {file_path}")
        bot.messaging.send_file_sync(
            update.peer,
            file_path,
            name=name or os.path.basename(file_path),
            caption=caption or ""
        )
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка отправки файла {file_path}: {e}")
        return False

def start_handler(update: UpdateMessage):
    user_states[update.peer.id] = {"mode": config['states']['main_menu'], "skip_next": True}
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['start']['response'])

def idea_handler(update: UpdateMessage):
    user_id = update.peer.id
    if user_id in user_states and user_states[user_id].get("mode", "").startswith("idea_"):
        bot.messaging.send_message(update.peer, config['error_messages']['already_in_process'])
        return
    user_states[user_id] = {
        "mode": config['states']['idea_choose_format'],
        "current_field": 0,
        "idea_data": {},
        "skip_next": True
    }
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['idea']['responses']['initial'])

def agent_handler(update: UpdateMessage):
    try:
        agents_file_path = config['file_settings']['agents_file']
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(update.peer, config['bot_settings']['commands']['ai_agent']['responses']['file_not_found'])
            wb = Workbook()
            ws = wb.active
            ws.append(["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"])
            wb.save(agents_file_path)

        summary_file = generate_agents_summary_file(agents_file_path)
        bot.messaging.send_message(update.peer, config['bot_settings']['commands']['ai_agent']['responses']['initial'])

        send_file(update, agents_file_path)
        if summary_file and os.path.exists(summary_file):
            send_file(update, summary_file, caption="📊 Аналитический отчет")
            try:
                os.remove(summary_file)
            except Exception as e:
                logging.warning(f"Не удалось удалить временный файл: {e}")

    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
        bot.messaging.send_message(update.peer, config['error_messages']['file_error'].format(error=e))

def search_owners_handler(update: UpdateMessage):
    try:
        agents_file_path = config['file_settings']['agents_file']
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(update.peer, config['error_messages']['file_not_found'])
            return

        wb = load_workbook(agents_file_path)
        sheet = wb.active
        headers = [cell.value for cell in sheet[1]]
        agents_data = [dict(zip(headers, row)) for row in sheet.iter_rows(min_row=2, values_only=True)]

        user_states[update.peer.id] = {
            "mode": config['states']['search_owners'],
            "agents_data": agents_data,
            "skip_next": True
        }
        bot.messaging.send_message(update.peer, f"✅ Файл {os.path.basename(agents_file_path)} успешно загружен!\n\n💬 Теперь опишите свободно, что вас интересует...")
    except Exception as e:
        logging.error(f"Ошибка в search_owners_handler: {e}")
        bot.messaging.send_message(update.peer, config['error_messages']['general_error'].format(error=e))

def help_idea_handler(update: UpdateMessage):
    user_states[update.peer.id] = {"mode": config['states']['help_with_ideas'], "skip_next": True}
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['help_idea']['responses']['initial'])

def consultation_handler(update: UpdateMessage):
    user_states[update.peer.id] = {"mode": config['states']['main_menu'], "skip_next": True}
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['consultation']['response'])

def help_handler(update: UpdateMessage):
    user_states[update.peer.id] = {"mode": config['states']['main_menu'], "skip_next": True}
    bot.messaging.send_message(update.peer, config['bot_settings']['commands']['help']['response'])

# Проверка на текст идеи
def is_idea_text(text: str) -> bool:
    idea_keywords = ["идея", "хочу автоматизировать", "надо сделать", "предлагаю", "улучшить", "оптимизировать"]
    return len(text) > 15 and any(k in text.lower() for k in idea_keywords)

# Основной обработчик текста
def text_handler(update: UpdateMessage, widget=None):
    if not update.message or not update.message.text_message:
        return

    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    state = user_states.get(user_id, {"mode": config['states']['main_menu']})

    # Если только что была команда — пропускаем дубль
    if state.get("skip_next"):
        logging.info(f"⏩ Пропускаем обработку: только что была команда для пользователя {user_id}")
        state["skip_next"] = False
        return

    # Здесь продолжение логики text_handler — обработка режимов, идей и т.п.
    bot.messaging.send_message(update.peer, f"Получено сообщение: {text}")

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
