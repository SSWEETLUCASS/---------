import os
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
)

# Загрузка переменных окружения
load_dotenv()

# Установка путей к сертификатам
os.environ["REQUESTS_CA_BUNDLE"] = "/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/SberCA.pem"
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = "/home/sigma.sbrf.ru@22754707/Рабочий стол/main_chat_bot/test/certs/russiantrustedca.pem"

BOT_TOKEN = os.getenv("DIALOG_BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

TEMPLATE_FIELDS = [
    "Название инициативы", "Что хотим улучшить?", "Какие данные поступают агенту на выход?",
    "Как процесс выглядит сейчас? as-is", "Какой результат нужен от агента?",
    "Достижимый идеал(to-be)", "Масштаб процесса"
]

user_states = {}
bot = None  # Глобальная переменная

def start_handler(update: UpdateMessage) -> None:
    """Обработчик команды /start"""
    user_id = update.peer.id
    user_states[user_id] = {"mode": "main_menu"}
    
    bot.messaging.send_message(update.peer, """
👋 Привет!
Меня зовут *Агентолог*, я помогу тебе с идеями для AI-агентов.

Вот что я могу сделать:
1. *У меня есть идея!*💡 — проверить, уникальна ли идея
2. *АИ-агенты?*📍 — скачать список уже реализованных
3. *Кто поможет?*💬 — найти владельцев
4. *Поддержка📝* — задать вопрос команде

🔹 Просто напиши команду или опиши свою идею!
""")

def idea_handler(update: UpdateMessage) -> None:
    """Обработчик для работы с идеями"""
    peer = update.peer
    user_id = peer.id
    user_states[user_id] = {"mode": "choose_idea_format", "current_field": 0, "idea_data": {}}

    bot.messaging.send_message(peer,
        "📝 *Как вы хотите описать свою идею?*\n\n"
        "1️⃣ *Давай шаблон!* — я помогу поэтапно сформулировать идею по полям.\n"
        "2️⃣ *Я могу и сам написать* — если ты уже знаешь, что хочешь, напиши всё одним сообщением.\n\n"
        "👉 Напиши `шаблон` или `сам`.")

def agent_handler(update: UpdateMessage) -> None:
    """Обработчик для получения списка AI-агентов"""
    peer = update.peer
    
    try:
        # Проверяем существование файла
        agents_file_path = "agents.xlsx"
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, "⚠️ Файл с агентами не найден. Создаю новый файл...")
            # Создаем пустой файл с заголовками
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"])
            wb.save(agents_file_path)
        
        # Генерируем улучшенную версию файла с анализом
        summary_file = generate_agents_summary_file(agents_file_path)
        
        bot.messaging.send_message(peer, "📊 *Актуальный список AI-агентов:*\n\n"
                                         "📎 Прикладываю оригинальный файл и аналитический отчет!")
        
        # Отправляем оригинальный файл
        with open(agents_file_path, "rb") as f:
            bot.messaging.send_file(peer, f, filename="agents.xlsx")
        
        # Отправляем аналитический отчет
        if summary_file and os.path.exists(summary_file):
            with open(summary_file, "rb") as f:
                bot.messaging.send_file(peer, f, filename=os.path.basename(summary_file))
            os.remove(summary_file)  # Удаляем временный файл
            
    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
        bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при обработке файла: {e}")

def group_handler(update: UpdateMessage) -> None:
    """Обработчик для поиска владельцев агентов"""
    peer = update.peer
    user_id = peer.id
    
    try:
        agents_file_path = "agents.xlsx"
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, "⚠️ Файл с агентами не найден.")
            return
        
        # Переводим пользователя в режим поиска владельцев
        user_states[user_id] = {"mode": "search_owners"}
        
        bot.messaging.send_message(peer, 
            "🔍 *Поиск владельцев AI-агентов*\n\n"
            "Опишите область или тип агента, который вас интересует.\n"
            "Например: 'документооборот', 'аналитика', 'чат-бот' или название конкретного процесса.\n\n"
            "👉 Напишите ваш запрос:")
        
    except Exception as e:
        logging.error(f"Ошибка в group_handler: {e}")
        bot.messaging.send_message(peer, f"⚠️ Произошла ошибка: {e}")

def help_handler(update: UpdateMessage) -> None:
    """Обработчик команды помощи"""
    bot.messaging.send_message(update.peer, """
📞 *Поддержка и контакты:*

📧 **Email:** sigma.sbrf.ru@22754707
💬 **Telegram:** @sigma.sbrf.ru@22754707

🤖 **Возможности бота:**
• Проверка уникальности идей для AI-агентов
• Получение списка существующих агентов
• Поиск владельцев и контактов
• Генерация файлов с описанием инициатив

💡 **Как пользоваться:**
Просто опишите свою идею или воспользуйтесь командами в главном меню.

🔄 Для возврата в главное меню напишите `/start`
""")

def process_template_idea(update: UpdateMessage, user_id: int) -> None:
    """Обработка идеи по шаблону (поэтапно)"""
    peer = update.peer
    text = update.message.text_message.text.strip()
    
    state = user_states[user_id]
    current_field = state["current_field"]
    
    if current_field > 0:  # Сохраняем ответ на предыдущий вопрос
        field_name = TEMPLATE_FIELDS[current_field - 1]
        state["idea_data"][field_name] = text
    
    if current_field < len(TEMPLATE_FIELDS):
        # Задаем следующий вопрос
        field_name = TEMPLATE_FIELDS[current_field]
        bot.messaging.send_message(peer, f"📝 **{field_name}**\n\nОпишите этот аспект вашей инициативы:")
        state["current_field"] += 1
    else:
        # Все поля заполнены, проверяем идею
        bot.messaging.send_message(peer, "✅ Отлично! Все поля заполнены. Проверяю уникальность идеи...")
        
        try:
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, state["idea_data"], is_free_form=False
            )
            
            bot.messaging.send_message(peer, f"🧠 **Результат анализа:**\n\n{response}")
            
            # Генерируем файлы
            if state["idea_data"]:
                word_path, excel_path = generate_files(state["idea_data"])
                bot.messaging.send_message(peer, "📎 Прикладываю файлы с вашей инициативой:")
                
                with open(word_path, "rb") as f_docx:
                    bot.messaging.send_file(peer, f_docx, filename=os.path.basename(word_path))
                
                with open(excel_path, "rb") as f_xlsx:
                    bot.messaging.send_file(peer, f_xlsx, filename=os.path.basename(excel_path))
                
                os.remove(word_path)
                os.remove(excel_path)
            
            # Сбрасываем состояние
            user_states[user_id] = {"mode": "main_menu"}
            bot.messaging.send_message(peer, "\n🔄 Для новой проверки напишите `/start`")
            
        except Exception as e:
            logging.error(f"Ошибка при обработке шаблонной идеи: {e}")
            bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при анализе: {e}")
            user_states[user_id] = {"mode": "main_menu"}

def text_handler(update: UpdateMessage, widget=None):
    """Основной обработчик текстовых сообщений"""
    if not update.message or not update.message.text_message:
        return

    text = update.message.text_message.text.strip()
    user_id = update.peer.id
    peer = update.peer

    # Получаем состояние пользователя
    state = user_states.get(user_id, {"mode": "main_menu"})
    
    logging.info(f"📩 Пользователь {user_id}: {text}")
    logging.info(f"📊 Состояние: {state}")

    # Обработка в зависимости от состояния
    if state["mode"] == "choose_idea_format":
        if "шаблон" in text.lower():
            state["mode"] = "template_idea"
            state["current_field"] = 0
            state["idea_data"] = {}
            process_template_idea(update, user_id)
            return
        elif "сам" in text.lower():
            state["mode"] = "free_form_idea"
            bot.messaging.send_message(peer, 
                "📝 *Опишите свою идею свободным текстом:*\n\n"
                "Расскажите максимально подробно о том, что вы хотите автоматизировать "
                "или улучшить с помощью AI-агента.")
            return
        else:
            bot.messaging.send_message(peer, 
                "❓ Не понял. Напишите `шаблон` для пошагового заполнения "
                "или `сам` для свободного описания.")
            return
    
    elif state["mode"] == "template_idea":
        process_template_idea(update, user_id)
        return
    
    elif state["mode"] == "free_form_idea":
        # Обработка свободной формы идеи
        bot.messaging.send_message(peer, "💡 Анализирую вашу идею...")
        
        try:
            user_data = {"Описание в свободной форме": text}
            response, is_unique, parsed_data, suggest_processing = check_idea_with_gigachat_local(
                text, user_data, is_free_form=True
            )
            
            bot.messaging.send_message(peer, f"🧠 **Результат анализа:**\n\n{response}")
            
            if parsed_data:
                word_path, excel_path = generate_files(parsed_data)
                bot.messaging.send_message(peer, "📎 Прикладываю файлы с вашей инициативой:")
                
                with open(word_path, "rb") as f_docx:
                    bot.messaging.send_file(peer, f_docx, filename=os.path.basename(word_path))
                
                with open(excel_path, "rb") as f_xlsx:
                    bot.messaging.send_file(peer, f_xlsx, filename=os.path.basename(excel_path))
                
                os.remove(word_path)
                os.remove(excel_path)
            
            # Сбрасываем состояние
            user_states[user_id] = {"mode": "main_menu"}
            bot.messaging.send_message(peer, "\n🔄 Для новой проверки напишите `/start`")
            
        except Exception as e:
            logging.error(f"Ошибка при обработке свободной идеи: {e}")
            bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при анализе: {e}")
            user_states[user_id] = {"mode": "main_menu"}
        return
    
    elif state["mode"] == "search_owners":
        # Поиск владельцев агентов
        bot.messaging.send_message(peer, "🔍 Ищу владельцев по вашему запросу...")
        
        try:
            owners_info = find_agent_owners(text)
            bot.messaging.send_message(peer, f"👥 **Найденные владельцы:**\n\n{owners_info}")
            
            user_states[user_id] = {"mode": "main_menu"}
            bot.messaging.send_message(peer, "\n🔄 Для нового поиска напишите `/start`")
            
        except Exception as e:
            logging.error(f"Ошибка при поиске владельцев: {e}")
            bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при поиске: {e}")
            user_states[user_id] = {"mode": "main_menu"}
        return

    # Обработка общих сообщений (когда пользователь в главном меню)
    try:
        gpt_response, maybe_idea, command = check_general_message_with_gigachat(text)
        
        logging.info(f"🔎 Ответ GigaChat: {gpt_response}, CMD: {command}, Похоже на идею: {maybe_idea}")

        if command == "help":
            help_handler(update)
            return
        elif command == "start":
            start_handler(update)
            return
        elif command == "ai_agent":
            agent_handler(update)
            return
        elif command == "group":
            group_handler(update)
            return
        elif command == "idea":
            idea_handler(update)
            return

        if maybe_idea:
            bot.messaging.send_message(peer, "💡 Похоже, вы описали идею. Сейчас проверю...")
            
            user_data = {"Описание в свободной форме": text}
            response, is_unique, parsed_data, suggest_processing = check_idea_with_gigachat_local(
                text, user_data, is_free_form=True)

            bot.messaging.send_message(peer, f"🧠 **Ответ GigaChat:**\n\n{response}")

            if parsed_data:
                word_path, excel_path = generate_files(parsed_data)
                bot.messaging.send_message(peer, "📎 Прикладываю файлы с вашей инициативой:")

                with open(word_path, "rb") as f_docx:
                    bot.messaging.send_file(peer, f_docx, filename=os.path.basename(word_path))

                with open(excel_path, "rb") as f_xlsx:
                    bot.messaging.send_file(peer, f_xlsx, filename=os.path.basename(excel_path))

                os.remove(word_path)
                os.remove(excel_path)

            elif suggest_processing:
                bot.messaging.send_message(peer, "🤔 Хотите проверить идею на уникальность? Напишите `/idea`!")

        else:
            bot.messaging.send_message(peer, gpt_response or "🤖 Я вас не понял. Попробуйте ещё раз или напишите `/start`")
    
    except Exception as e:
        logging.error(f"Ошибка в text_handler: {e}")
        bot.messaging.send_message(peer, f"⚠️ Произошла ошибка: {e}")

def main():
    global bot
    bot = DialogBot.create_bot({
        "endpoint": "epbotsift.sberchat.sberbank.ru",
        "token": BOT_TOKEN,
        "is_secure": True,
    })

    bot.messaging.command_handler([
        CommandHandler(start_handler, "start"),
        CommandHandler(idea_handler, "idea"),
        CommandHandler(agent_handler, "ai_agent"),
        CommandHandler(group_handler, "group"),
        CommandHandler(help_handler, "help"),
    ])

    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)
    ])

    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()