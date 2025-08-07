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
    generate_idea_suggestions,
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
    return bot_instance.messaging.send_filewrapped(
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

def start_handler(update: UpdateMessage) -> None:
    """Обработчик команды /start"""
    user_id = update.peer.id
    user_states[user_id] = {"mode": "main_menu"}
    
    bot.messaging.send_message(update.peer, """
🤖 **Добро пожаловать в Агентолог!**

Я ваш персональный помощник по разработке AI-агентов. Помогу проверить уникальность идей, найти существующие решения и создать техническое описание вашей инициативы.

**🔧 Мои возможности:**

💡 **У меня есть идея!** — проверю уникальность и создам техническое описание
   • Сравню с существующими агентами
   • Проанализирую на практичность
   • Создам Word и Excel документы

📊 **АИ-агенты?** — предоставлю актуальный список реализованных агентов
   • База всех существующих инициатив
   • Аналитические отчеты
   • Статистика по типам и блокам

🔍 **Поиск владельцев** — найду владельцев и контакты по вашему запросу
   • Поиск экспертов по области
   • Контактная информация
   • Рекомендации по сотрудничеству

🧠 **Помоги с идеей!** — предложу варианты для автоматизации
   • Генерация новых идей
   • Анализ возможностей AI
   • Советы по реализации

📝 **Поддержка** — техническая помощь и консультации

**🚀 Как начать:**
• Просто опишите свою идею
• Или выберите нужную функцию
• Напишите команду или задайте вопрос

Готов помочь! Что вас интересует? 🎯
""")

def idea_handler(update: UpdateMessage) -> None:
    """Обработчик для работы с идеями"""
    peer = update.peer
    user_id = peer.id
    
    if user_id in user_states and user_states[user_id].get("mode", "").startswith("idea_"):
        bot.messaging.send_message(peer, "Вы уже в процессе работы с идеей. Продолжайте заполнение.")
        return
    
    user_states[user_id] = {"mode": "idea_choose_format", "current_field": 0, "idea_data": {}}
    bot.messaging.send_message(peer,
        "📝 **Как вы хотите описать свою идею?**\n\n"
        "1️⃣ **Давай шаблон!** — я помогу поэтапно сформулировать идею по полям.\n"
        "2️⃣ **Я могу и сам написать** — если ты уже знаешь, что хочешь, напиши всё одним сообщением.\n\n"
        "👉 Напиши `шаблон` или `сам`.")

def agent_handler(update: UpdateMessage) -> None:
    """Обработчик для получения списка AI-агентов"""
    peer = update.peer
    
    try:
        agents_file_path = "agents.xlsx"
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, "⚠️ Файл с агентами не найден. Создаю новый файл...")
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(["Блок", "ССП", "Владелец", "Контакт", "Название", "Краткое название", "Описание", "Тип"])
            wb.save(agents_file_path)
        
        summary_file = generate_agents_summary_file(agents_file_path)
        
        bot.messaging.send_message(peer, "📊 **Актуальный список AI-агентов:**\n\n"
                                         "📎 Прикладываю оригинальный файл и аналитический отчет!")
        
        with open(agents_file_path, "rb") as f:
            send_file_sync(bot, peer, f, name="agents.xlsx")
        
        if summary_file and os.path.exists(summary_file):
            with open(summary_file, "rb") as f:
                send_file_sync(bot, peer, f, name=os.path.basename(summary_file))
            os.remove(summary_file)
            
    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
        bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при обработке файла: {e}")

def search_owners_handler(update: UpdateMessage) -> None:
    """Обработчик для поиска владельцев агентов"""
    peer = update.peer
    user_id = peer.id
    
    try:
        agents_file_path = "agents.xlsx"
        if not os.path.exists(agents_file_path):
            bot.messaging.send_message(peer, "⚠️ Файл с агентами не найден.")
            return
        
        user_states[user_id] = {"mode": "search_owners"}
        
        bot.messaging.send_message(peer, 
            "🔍 **Поиск владельцев AI-агентов**\n\n"
            "Вы можете искать:\n"
            "- По имени владельца (Иванов, Петрова)\n"
            "- По названию агента (чат-бот, аналитика)\n"
            "- По типу процесса (документооборот, кредитование)\n\n"
            "👉 Напишите имя, название или тип:")
    except Exception as e:
        logging.error(f"Ошибка в agent_handler: {e}")
def help_idea_handler(update: UpdateMessage) -> None:
    """Обработчик для помощи с генерацией идей"""
    peer = update.peer
    user_id = peer.id
    
    user_states[user_id] = {"mode": "help_with_ideas"}
    
    bot.messaging.send_message(peer,
        "🧠 **Помощь с генерацией идей для AI-агентов**\n\n"
        "Расскажите мне:\n"
        "• В какой области вы работаете?\n"
        "• Какие процессы хотелось бы автоматизировать?\n"
        "• Есть ли конкретные задачи, которые отнимают много времени?\n\n"
        "Или просто напишите 'предложи идеи' и я дам несколько вариантов!\n\n"
        "👉 Опишите ваш запрос:")

def help_handler(update: UpdateMessage) -> None:
    """Обработчик команды помощи"""
    bot.messaging.send_message(update.peer, """
📞 **Поддержка и контакты:**

📧 **Email:** sigma.sbrf.ru@22754707
💬 **Telegram:** @sigma.sbrf.ru@22754707

🤖 **Возможности бота:**
• Проверка уникальности идей для AI-агентов
• Получение списка существующих агентов
• Поиск владельцев и контактов
• Генерация файлов с описанием инициатив
• Помощь в разработке новых идей

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
    
    if current_field > 0:
        field_name = TEMPLATE_FIELDS[current_field - 1]
        state["idea_data"][field_name] = text
    
    if current_field < len(TEMPLATE_FIELDS):
        field_name = TEMPLATE_FIELDS[current_field]
        bot.messaging.send_message(peer, f"📝 **{field_name}**\n\nОпишите этот аспект вашей инициативы:")
        state["current_field"] += 1
    else:
        bot.messaging.send_message(peer, "✅ Отлично! Все поля заполнены. Проверяю уникальность идеи...")
        
        try:
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, state["idea_data"], is_free_form=False
            )
            
            bot.messaging.send_message(peer, f"🧠 **Результат анализа:**\n\n{response}")
            
            if state["idea_data"]:
                word_path, excel_path = generate_files(state["idea_data"])
                bot.messaging.send_message(peer, "📎 Прикладываю файлы с вашей инициативой:")
                
                with open(word_path, "rb") as f_docx:
                    send_file_sync(bot, peer, f_docx, name=os.path.basename(word_path))
                
                with open(excel_path, "rb") as f_xlsx:
                    send_file_sync(bot, peer, f_xlsx, name=os.path.basename(excel_path))
                
                os.remove(word_path)
                os.remove(excel_path)
            
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

    state = user_states.get(user_id, {"mode": "main_menu"})
    
    logging.info(f"📩 Пользователь {user_id}: {text}")
    logging.info(f"📊 Состояние: {state}")

    # Обработка в зависимости от состояния
    if state["mode"] == "idea_choose_format":
        if "шаблон" in text.lower():
            state["mode"] = "idea_template"
            state["current_field"] = 0
            state["idea_data"] = {}
            process_template_idea(update, user_id)
            return
        elif "сам" in text.lower():
            state["mode"] = "idea_free_form"
            bot.messaging.send_message(peer, 
                "📝 **Опишите свою идею свободным текстом:**\n\n"
                "Расскажите максимально подробно о том, что вы хотите автоматизировать "
                "или улучшить с помощью AI-агента.")
            return
        else:
            bot.messaging.send_message(peer, 
                "❓ Не понял. Напишите `шаблон` для пошагового заполнения "
                "или `сам` для свободного описания.")
            return
    
    elif state["mode"] == "idea_template":
        process_template_idea(update, user_id)
        return
    
    elif state["mode"] == "idea_free_form":
        bot.messaging.send_message(peer, "💡 Анализирую вашу идею...")
        
        try:
            user_data = {"Описание в свободной форме": text}
            response, is_unique, parsed_data, _ = check_idea_with_gigachat_local(
                text, user_data, is_free_form=True
            )
            
            bot.messaging.send_message(peer, f"🧠 **Результат анализа:**\n\n{response}")
            
            if parsed_data:
                word_path, excel_path = generate_files(parsed_data)
                bot.messaging.send_message(peer, "📎 Прикладываю файлы с вашей инициативой:")
                
                with open(word_path, "rb") as f_docx:
                    send_file_sync(bot, peer, f_docx, name=os.path.basename(word_path))
                
                with open(excel_path, "rb") as f_xlsx:
                    send_file_sync(bot, peer, f_xlsx, name=os.path.basename(excel_path))
                
                os.remove(word_path)
                os.remove(excel_path)
            
            user_states[user_id] = {"mode": "main_menu"}
            bot.messaging.send_message(peer, "\n🔄 Для новой проверки напишите `/start`")
            
        except Exception as e:
            logging.error(f"Ошибка при обработке свободной идеи: {e}")
            bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при анализе: {e}")
            user_states[user_id] = {"mode": "main_menu"}
        return
    
    elif state["mode"] == "search_owners":
        bot.messaging.send_message(peer, "🔍 Ищу владельцев по вашему запросу...")
        
        try:
            owners_info = find_agent_owners(text)
            bot.messaging.send_message(peer, owners_info)
            
            user_states[user_id] = {"mode": "main_menu"}
            bot.messaging.send_message(peer, "\n🔄 Для нового поиска напишите `/search_owners`")
            
        except Exception as e:
            logging.error(f"Ошибка при поиске владельцев: {e}")
            bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при поиске: {e}")
            user_states[user_id] = {"mode": "main_menu"}
        return

    elif state["mode"] == "help_with_ideas":
        bot.messaging.send_message(peer, "🧠 Генерирую идеи для вас...")
        
        try:
            ideas_response = generate_idea_suggestions(text)
            bot.messaging.send_message(peer, f"💡 **Идеи для AI-агентов:**\n\n{ideas_response}")
            bot.messaging.send_message(peer, 
                "\n🔹 Понравилась какая-то идея? Напишите `/idea` чтобы детально её проработать!")
            
            user_states[user_id] = {"mode": "main_menu"}
            
        except Exception as e:
            logging.error(f"Ошибка при генерации идей: {e}")
            bot.messaging.send_message(peer, f"⚠️ Произошла ошибка при генерации идей: {e}")
            user_states[user_id] = {"mode": "main_menu"}
        return

    # Обработка общих сообщений
    try:
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
            elif command == "help":
                help_handler(update)
            else:
                bot.messaging.send_message(peer, "❌ Неизвестная команда. Напишите `/start` для просмотра доступных команд.")
            return
        
        gpt_response, command = check_general_message_with_gigachat(text)
        
        logging.info(f"🔎 Ответ GigaChat: {gpt_response}, CMD: {command}")

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
            else:
                bot.messaging.send_message(peer, gpt_response or "🤖 Я вас не понял. Попробуйте ещё раз или напишите `/start`")
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
        CommandHandler(search_owners_handler, "search_owners"),
        CommandHandler(search_owners_handler, "group"),
        CommandHandler(help_idea_handler, "help_idea"),
        CommandHandler(help_handler, "help"),
    ])

    bot.messaging.message_handler([
        MessageHandler(text_handler, MessageContentType.TEXT_MESSAGE)
    ])

    bot.updates.on_updates(do_read_message=True, do_register_commands=True)

if __name__ == "__main__":
    main()