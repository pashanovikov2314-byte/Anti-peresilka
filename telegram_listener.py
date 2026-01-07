import logging
import re
import json
import os
from datetime import datetime
import requests
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Настройки
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramListener:
    def __init__(self):
        self.updater = Updater(TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher
        
        # Регистрация обработчиков
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        self.dispatcher.add_handler(CommandHandler("leakstats", self.leakstats_command))
        self.dispatcher.add_handler(CommandHandler("skillup", self.skillup_command))
        self.dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, self.monitor_messages))
        
        logger.info("👂 Telegram Listener инициализирован")
    
    def start_command(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        
        if user_id not in ALLOWED_USER_IDS:
            update.message.reply_text("❌ Бот временно не работает.")
            return
        
        welcome = """
🔒 **LeakTracker** активирован

Доступные команды:
/help - Справка
/leakstats - Статистика утечек
/skillup - Режим повышенной детекции

🤖 Бот работает в фоновом режиме.
Все обнаруженные утечки будут отправлены вам в ЛС.
        """
        update.message.reply_text(welcome, parse_mode='Markdown')
    
    def help_command(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        help_text = """
📖 **LeakTracker - Помощь**

Бот отслеживает потенциальные утечки информации в чатах:
• Пересылки сообщений
• Ссылки на Telegram
• Длинные тексты
• Подозрительные медиафайлы
        """
        update.message.reply_text(help_text, parse_mode='Markdown')
    
    def leakstats_command(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        try:
            response = requests.get(f"{RENDER_URL}/health", timeout=10)
            if response.status_code == 200:
                data = response.json()
                stats = f"📊 **Статистика**\n\n"
                stats += f"• Утечек: {data.get('leak_count', 0)}\n"
                stats += f"• Пользователей: {data.get('user_count', 0)}\n"
                stats += f"• Пингов: {data.get('ping_count', 0)}\n"
                stats += f"• Режим: {'ULTRA 🔥' if data.get('skillup_ultra') else 'NORMAL'}"
                
                update.message.reply_text(stats, parse_mode='Markdown')
        except:
            update.message.reply_text("❌ Сервер статистики недоступен")
    
    def skillup_command(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        update.message.reply_text("⚡ Режим SkillUP управляется через веб-интерфейс")
    
    def detect_leak(self, msg):
        leak_type = None
        leak_details = ""
        
        if msg.forward_from_chat:
            leak_type = "ПЕРЕСЫЛКА В ЧАТ"
            leak_details = f"В чат: {msg.forward_from_chat.title}"
            
        elif msg.forward_from:
            leak_type = "ПЕРЕСЫЛКА ПОЛЬЗОВАТЕЛЮ"
            target = msg.forward_from.username or f"id{msg.forward_from.id}"
            leak_details = f"Пользователю: {target}"
        
        elif msg.text or msg.caption:
            text = msg.text or msg.caption
            
            telegram_link_pattern = r't\.me/(?:c/)?[a-zA-Z0-9_\-/]+'
            if re.search(telegram_link_pattern, text):
                leak_type = "КОПИРОВАНИЕ ССЫЛКИ"
                leak_details = "Скопировал ссылку на сообщение"
            
            elif len(text) > 300 and '\n' in text:
                leak_type = "КОПИРОВАНИЕ ТЕКСТА"
                leak_details = f"Скопировал {len(text)} символов"
        
        if leak_type:
            return {
                'type': leak_type,
                'details': leak_details,
                'chat_id': msg.chat.id,
                'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
                'message_id': msg.message_id,
                'detection_mode': 'NORMAL'
            }
        
        return None
    
    def monitor_messages(self, update: Update, context: CallbackContext):
        msg = update.message
        if not msg or msg.chat.type == 'private':
            return
        
        user_id = msg.from_user.id
        
        # Детекция утечки
        leak_info = self.detect_leak(msg)
        
        if leak_info:
            try:
                # Отправка на основной сервер
                api_url = f"{RENDER_URL}/api/leak/{user_id}"
                
                user_data = {
                    'username': msg.from_user.username or f"id{user_id}",
                    'first_name': msg.from_user.first_name or "",
                    'last_name': msg.from_user.last_name or ""
                }
                
                payload = {
                    **leak_info,
                    'user_data': user_data
                }
                
                response = requests.post(api_url, json=payload, timeout=10)
                
                if response.status_code == 200:
                    logger.info(f"✅ Утечка отправлена для пользователя {user_id}")
                else:
                    logger.error(f"❌ Ошибка отправки утечки: {response.text}")
                    
            except Exception as e:
                logger.error(f"❌ Ошибка обработки утечки: {e}")
    
    def run(self):
        self.updater.start_polling()
        self.updater.idle()

if __name__ == '__main__':
    listener = TelegramListener()
    listener.run()
