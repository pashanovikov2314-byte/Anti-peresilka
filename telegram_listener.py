import logging
import re
import json
import time
import requests
import secrets
from datetime import datetime
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
API_KEY = os.environ.get("API_KEY", secrets.token_hex(16))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramLeakListener:
    """Telegram листенер для мониторинга утечек"""
    
    def __init__(self):
        if not TOKEN:
            raise ValueError("❌ TELEGRAM_TOKEN не установлен")
        
        self.updater = Updater(TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher
        
        # Статистика
        self.stats = {
            'messages': 0,
            'leaks': 0,
            'users': 0,
            'errors': 0
        }
        
        # Регистрация обработчиков
        self._setup_handlers()
        
        logger.info("👂 Telegram Listener инициализирован")
    
    def _setup_handlers(self):
        """Настройка обработчиков"""
        # Команды для админов
        self.dispatcher.add_handler(CommandHandler("start", self._cmd_start))
        self.dispatcher.add_handler(CommandHandler("help", self._cmd_help))
        self.dispatcher.add_handler(CommandHandler("stats", self._cmd_stats))
        self.dispatcher.add_handler(CommandHandler("status", self._cmd_status))
        
        # Мониторинг сообщений
        self.dispatcher.add_handler(MessageHandler(
            Filters.all & ~Filters.command,
            self._handle_message
        ))
    
    def _cmd_start(self, update: Update, context: CallbackContext):
        """Команда /start"""
        user_id = update.effective_user.id
        
        if user_id not in ALLOWED_USER_IDS:
            update.message.reply_text("❌ Бот временно не работает.")
            return
        
        welcome = """
🔐 **LeakTracker v2.0**

Система мониторинга утечек информации

**Доступные команды:**
/help - Справка
/stats - Статистика
/status - Статус системы

🤖 *Бот работает в фоновом режиме*
*Все обнаруженные утечки будут отправлены админам*
        """
        
        update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)
    
    def _cmd_help(self, update: Update, context: CallbackContext):
        """Команда /help"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        help_text = """
📖 **LeakTracker - Справка**

**Что детектирует система:**
• Пересылки сообщений
• Ссылки на Telegram
• Финансовые данные
• Персональные данные
• Учетные данные

**Уровни риска:**
🔴 ВЫСОКИЙ - Немедленные действия
🟡 СРЕДНИЙ - Мониторинг
🟢 НИЗКИЙ - Запись в лог

**Веб-интерфейс:** """ + (RENDER_URL if RENDER_URL else "Не настроен") + """
        """
        
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    def _cmd_stats(self, update: Update, context: CallbackContext):
        """Команда /stats"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        stats_text = f"""
📊 **Статистика мониторинга**

**Локальная:**
• Сообщений обработано: {self.stats['messages']}
• Утечек обнаружено: {self.stats['leaks']}
• Пользователей в мониторинге: {self.stats['users']}
• Ошибок: {self.stats['errors']}

**Системная:**
• Сервер: {'🟢 ONLINE' if RENDER_URL else '🔴 OFFLINE'}
• Админов: {len(ALLOWED_USER_IDS)}
        """
        
        update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    def _cmd_status(self, update: Update, context: CallbackContext):
        """Команда /status"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        # Проверка связи с сервером
        server_status = "🔴 OFFLINE"
        if RENDER_URL:
            try:
                response = requests.get(f"{RENDER_URL}/api/health", timeout=5)
                if response.status_code == 200:
                    server_status = "🟢 ONLINE"
            except:
                pass
        
        status_text = f"""
🔄 **Статус системы**

**Мониторинг:**
• Telegram бот: 🟢 АКТИВЕН
• Веб сервер: {server_status}
• API ключ: {'🟢 УСТАНОВЛЕН' if API_KEY else '🔴 ОТСУТСТВУЕТ'}

**Последняя активность:**
• Время: {datetime.now().strftime('%H:%M:%S')}
• Сообщений/час: {self.stats['messages']}
        """
        
        update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
    
    def _detect_leak(self, message) -> dict:
        """Детекция утечки в сообщении"""
        leak_info = None
        
        # 1. Проверка пересылки
        if message.forward_from_chat:
            leak_info = {
                'type': 'FORWARD_TO_CHAT',
                'details': f"Чат: {message.forward_from_chat.title}",
                'risk_score': 60,
                'chat_id': message.chat.id,
                'chat_title': message.chat.title or f"Чат {message.chat.id}",
                'message_id': message.message_id
            }
        elif message.forward_from:
            target = message.forward_from.username or f"id{message.forward_from.id}"
            leak_info = {
                'type': 'FORWARD_TO_USER',
                'details': f"Пользователь: {target}",
                'risk_score': 50,
                'chat_id': message.chat.id,
                'chat_title': message.chat.title or f"Чат {message.chat.id}",
                'message_id': message.message_id
            }
        
        # 2. Анализ текста
        text = message.text or message.caption or ""
        
        if text:
            # Ссылки на Telegram
            telegram_links = re.findall(r't\.me/(?:c/)?[a-zA-Z0-9_\-/]+', text)
            if telegram_links:
                leak_info = {
                    'type': 'TELEGRAM_LINKS',
                    'details': f"Ссылки: {', '.join(telegram_links[:3])}",
                    'risk_score': 40,
                    'chat_id': message.chat.id,
                    'chat_title': message.chat.title or f"Чат {message.chat.id}",
                    'message_id': message.message_id,
                    'text': text[:200]
                }
            
            # Длинные тексты
            elif len(text) > 500 and '\n' in text:
                leak_info = {
                    'type': 'LONG_TEXT_COPY',
                    'details': f"Длинный текст: {len(text)} симв.",
                    'risk_score': 30,
                    'chat_id': message.chat.id,
                    'chat_title': message.chat.title or f"Чат {message.chat.id}",
                    'message_id': message.message_id,
                    'text': text[:200]
                }
            
            # Конфиденциальные данные
            patterns = [
                (r'\b\d{16}\b', 'CARD_NUMBER', 80),
                (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}', 'EMAIL', 20),
                (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}\b', 'PHONE', 30),
            ]
            
            for pattern, leak_type, score in patterns:
                if re.search(pattern, text):
                    leak_info = {
                        'type': leak_type,
                        'details': 'Конфиденциальные данные',
                        'risk_score': score,
                        'chat_id': message.chat.id,
                        'chat_title': message.chat.title or f"Чат {message.chat.id}",
                        'message_id': message.message_id,
                        'text': text[:200]
                    }
                    break
        
        # 3. Медиа файлы
        if message.photo or message.video or message.document:
            if not leak_info:
                media_type = "фото" if message.photo else "видео" if message.video else "документ"
                leak_info = {
                    'type': 'MEDIA_SAVE',
                    'details': f"Сохранил {media_type}",
                    'risk_score': 25,
                    'chat_id': message.chat.id,
                    'chat_title': message.chat.title or f"Чат {message.chat.id}",
                    'message_id': message.message_id
                }
        
        return leak_info
    
    def _send_to_server(self, user_id: int, leak_data: dict) -> bool:
        """Отправка данных на сервер"""
        if not RENDER_URL or not API_KEY:
            logger.warning("⚠️ Сервер не настроен, данные не отправлены")
            return False
        
        try:
            # Подготовка данных
            payload = {
                'user_id': user_id,
                'leak_data': leak_data,
                'timestamp': datetime.now().isoformat()
            }
            
            # Отправка
            headers = {'X-API-Key': API_KEY, 'Content-Type': 'application/json'}
            response = requests.post(
                f"{RENDER_URL}/api/report",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Утечка отправлена для пользователя {user_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка соединения: {e}")
            self.stats['errors'] += 1
            return False
    
    def _send_alert(self, user_id: int, leak_info: dict):
        """Отправка уведомления админам"""
        alert_msg = f"""
⚠️ **ОБНАРУЖЕНА УТЕЧКА**

👤 **Пользователь:** id{user_id}
📊 **Тип:** {leak_info.get('type')}
🎯 **Риск:** {leak_info.get('risk_score')}/100
💬 **Чат:** {leak_info.get('chat_title')}
⏰ **Время:** {datetime.now().strftime('%H:%M:%S')}

📝 **Детали:** {leak_info.get('details', '')[:100]}
        """
        
        for admin_id in ALLOWED_USER_IDS:
            try:
                self.updater.bot.send_message(
                    chat_id=admin_id,
                    text=alert_msg,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                logger.info(f"📨 Уведомление отправлено админу {admin_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
    
    def _handle_message(self, update: Update, context: CallbackContext):
        """Обработка сообщений"""
        message = update.message
        if not message or message.chat.type == 'private':
            return
        
        user_id = message.from_user.id
        self.stats['messages'] += 1
        
        # Детекция утечки
        leak_info = self._detect_leak(message)
        
        if leak_info:
            self.stats['leaks'] += 1
            
            # Добавление информации о пользователе
            leak_info['username'] = message.from_user.username or f"id{user_id}"
            leak_info['first_name'] = message.from_user.first_name or ""
            leak_info['last_name'] = message.from_user.last_name or ""
            leak_info['user_id'] = user_id
            
            # Отправка на сервер
            if RENDER_URL and API_KEY:
                success = self._send_to_server(user_id, leak_info)
                
                # Уведомление админов для высокого риска
                if success and leak_info.get('risk_score', 0) >= 50:
                    self._send_alert(user_id, leak_info)
            
            logger.info(f"🔍 Утечка обнаружена: {leak_info['type']} (риск: {leak_info.get('risk_score')})")
    
    def run(self):
        """Запуск бота"""
        logger.info("🚀 Запуск Telegram Listener...")
        
        # Проверка конфигурации
        if not RENDER_URL:
            logger.warning("⚠️ RENDER_URL не установлен, серверные функции недоступны")
        
        self.updater.start_polling()
        logger.info("✅ Telegram бот запущен и слушает сообщения")
        self.updater.idle()

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    try:
        listener = TelegramLeakListener()
        listener.run()
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
