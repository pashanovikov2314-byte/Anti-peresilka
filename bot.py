import logging
import re
import time
import threading
import requests
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from collections import defaultdict
import json
import os

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", 5000))

SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 600))
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))

if not TOKEN or TOKEN == "ВАШ_ТОКЕН":
    raise ValueError("❌ TELEGRAM_TOKEN не установлен или неверный")
if not YOUR_ID or YOUR_ID == 0:
    raise ValueError("❌ YOUR_TELEGRAM_ID не установлен")
if not RENDER_URL:
    raise ValueError("❌ RENDER_EXTERNAL_URL не установлен")

app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramLeakBot:
    def __init__(self):
        self.bot_start_time = datetime.now()
        self.leaks_by_user = defaultdict(list)
        self.user_info = {}
        self.ping_count = 0
        self.last_successful_ping = None
        self.self_ping_enabled = True
        self.is_running = True
        
        self.updater = Updater(TOKEN, use_context=True)
        self.dp = self.updater.dispatcher
        
        self.register_handlers()
        self.load_data()
        self.start_background_tasks()
        self.setup_flask_endpoints()
        
        logger.info("🤖 Бот инициализирован")
    
    def register_handlers(self):
        self.dp.add_handler(CommandHandler("start", self.start_command))
        self.dp.add_handler(CommandHandler("help", self.help_command))
        self.dp.add_handler(CommandHandler("leakstats", self.leakstats_command))
        self.dp.add_handler(CommandHandler("leakinfo", self.leakinfo_command))
        self.dp.add_handler(CommandHandler("pingstatus", self.pingstatus_command))
        self.dp.add_handler(CommandHandler("toggleping", self.toggleping_command))
        self.dp.add_handler(CommandHandler("status", self.status_command))
        self.dp.add_handler(CommandHandler("clear", self.clear_command))
        self.dp.add_handler(MessageHandler(Filters.all & ~Filters.command, self.monitor_messages))
    
    def setup_flask_endpoints(self):
        @app.route('/')
        def home():
            uptime = (datetime.now() - self.bot_start_time).seconds
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            return f"<h1>🤖 LeakTracker Bot</h1><p>✅ Работает! Uptime: {hours}ч {minutes}м</p>"
        
        @app.route('/health')
        def health():
            return {
                "status": "active",
                "uptime_seconds": (datetime.now() - self.bot_start_time).seconds,
                "ping_count": self.ping_count,
                "leak_count": len(self.leaks_by_user),
                "user_count": len(self.user_info)
            }
        
        @app.route('/ping')
        def ping():
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            return {"status": "pong", "ping_number": self.ping_count}
    
    def start_background_tasks(self):
        def self_ping_task():
            while self.is_running:
                if self.self_ping_enabled:
                    self.perform_self_ping()
                time.sleep(SELF_PING_INTERVAL)
        
        def auto_save_task():
            while self.is_running:
                time.sleep(AUTO_SAVE_INTERVAL)
                self.save_data()
                logger.debug("💾 Данные автосохранены")
        
        threading.Thread(target=self_ping_task, daemon=True).start()
        threading.Thread(target=auto_save_task, daemon=True).start()
    
    def perform_self_ping(self):
        try:
            endpoints = [RENDER_URL, f"{RENDER_URL}/health", f"{RENDER_URL}/ping"]
            for endpoint in endpoints:
                response = requests.get(endpoint, timeout=15)
                if response.status_code == 200:
                    logger.debug(f"✅ Пинг {endpoint}")
            
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            
            if self.ping_count % 50 == 0:
                logger.info(f"✅ Самопинг #{self.ping_count} выполнен")
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка самопинга: {str(e)[:100]}")
    
    def monitor_messages(self, update: Update, context: CallbackContext):
        msg = update.message
        if not msg or msg.chat.type == 'private':
            return
        
        user_id = msg.from_user.id
        
        if user_id not in self.user_info:
            self.user_info[user_id] = {
                'username': msg.from_user.username or f"id{user_id}",
                'first_name': msg.from_user.first_name or "",
                'last_name': msg.from_user.last_name or "",
                'last_seen': datetime.now().isoformat(),
                'first_seen': datetime.now().isoformat()
            }
        else:
            self.user_info[user_id]['last_seen'] = datetime.now().isoformat()
        
        leak_info = self.detect_leak(msg)
        
        if leak_info:
            self.handle_leak(user_id, leak_info, msg, context)
    
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
            chat_id = msg.chat.id
            
            telegram_link_pattern = r't\.me/(?:c/)?[a-zA-Z0-9_\-/]+'
            if re.search(telegram_link_pattern, text):
                leak_type = "КОПИРОВАНИЕ ССЫЛКИ"
                leak_details = "Скопировал ссылку на сообщение"
            
            elif len(text) > 300 and '\n' in text:
                leak_type = "КОПИРОВАНИЕ ТЕКСТА"
                leak_details = f"Скопировал {len(text)} символов"
        
        screenshot_score = self.calculate_screenshot_score(msg)
        if screenshot_score > 75:
            leak_type = "ПОДОЗРЕНИЕ НА СКРИНШОТ"
            leak_details = f"Вероятность скриншота: {screenshot_score}%"
        
        if leak_type:
            return {
                'type': leak_type,
                'details': leak_details,
                'timestamp': datetime.now().isoformat(),
                'chat_id': msg.chat.id,
                'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
                'message_id': msg.message_id
            }
        
        return None
    
    def calculate_screenshot_score(self, msg):
        score = 0
        
        if hasattr(msg, 'reply_to_message') and msg.reply_to_message:
            time_diff = (msg.date - msg.reply_to_message.date).total_seconds()
            if time_diff > 180:
                score += 30
        
        if msg.text and len(msg.text) < 15:
            screenshot_emojis = ['📸', '🖼', '💾', '📱', '📲', '⬇️', '⬆️', '👇', '👆']
            if any(emoji in msg.text for emoji in screenshot_emojis):
                score += 40
        
        if msg.photo or msg.video or msg.document:
            score += 20
        
        return min(score, 100)
    
    def handle_leak(self, user_id, leak_info, msg, context):
        self.leaks_by_user[user_id].append(leak_info)
        
        if len(self.leaks_by_user[user_id]) > 50:
            self.leaks_by_user[user_id] = self.leaks_by_user[user_id][-50:]
        
        self.send_leak_alert(user_id, leak_info, msg, context)
        self.save_data()
    
    def send_leak_alert(self, user_id, leak_info, msg, context):
        user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
        
        alert = f"🚨 ОБНАРУЖЕНА УТЕЧКА\n\n"
        alert += f"👤 Нарушитель: @{user['username']}\n"
        alert += f"📛 Имя: {user['first_name']} {user.get('last_name', '')}\n"
        alert += f"🆔 ID: {user_id}\n"
        alert += f"💬 Чат: {msg.chat.title}\n"
        alert += f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
        alert += f"📌 Тип нарушения: {leak_info['type']}\n"
        alert += f"📝 Детали: {leak_info['details']}\n\n"
        alert += f"📊 Всего нарушений у этого пользователя: {len(self.leaks_by_user[user_id])}"
        
        try:
            context.bot.send_message(
                chat_id=YOUR_ID,
                text=alert
            )
            logger.info(f"📤 Уведомление отправлено о пользователе {user_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось отправить уведомление: {e}")
    
    def start_command(self, update: Update, context: CallbackContext):
        update.message.reply_text(
            "🛡️ LeakTracker Bot\n\n"
            "Я отслеживаю утечки информации из чатов.\n\n"
            "📋 Команды:\n"
            "/leakstats - таблица нарушителей\n"
            "/leakinfo [id] - информация о нарушителе\n"
            "/status - статус бота\n"
            "/help - справка"
        )
    
    def help_command(self, update: Update, context: CallbackContext):
        help_text = "📖 СПРАВКА:\n\n"
        help_text += "/start - информация о боте\n"
        help_text += "/help - эта справка\n"
        help_text += "/leakstats - таблица всех нарушителей\n"
        help_text += "/leakinfo [id] - информация о нарушителе\n"
        help_text += "/status - статус бота\n"
        help_text += "/pingstatus - статус самопинга (владелец)\n"
        help_text += "/toggleping - вкл/выкл самопинг (владелец)\n"
        help_text += "/clear - очистить данные (владелец)"
        
        update.message.reply_text(help_text)
            def leakstats_command(self, update: Update, context: CallbackContext):
        if not self.leaks_by_user:
            update.message.reply_text("📭 Нарушителей не обнаружено")
            return
        
        stats = []
        for user_id, leaks in self.leaks_by_user.items():
            if not leaks:
                continue
            
            user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
            
            leak_types = {}
            for leak in leaks[-20:]:
                leak_type = leak['type']
                leak_types[leak_type] = leak_types.get(leak_type, 0) + 1
            
            stats.append({
                'user_id': user_id,
                'username': user['username'],
                'total_leaks': len(leaks),
                'leak_types': leak_types
            })
        
        stats.sort(key=lambda x: x['total_leaks'], reverse=True)
        
        table = "📊 ТАБЛИЦА НАРУШИТЕЛЕЙ\n\n"
        table += "┌──────────────┬────────────────┬─────────────────────────────┐\n"
        table += "│ Пользователь │ Всего нарушений │ Основные типы нарушений    │\n"
        table += "├──────────────┼────────────────┼─────────────────────────────┤\n"
        
        for stat in stats[:15]:
            username = f"@{stat['username']}" if not stat['username'].startswith('id') else stat['username']
            username_display = username[:12].ljust(12)
            
            types_str = ""
            for leak_type, count in list(stat['leak_types'].items())[:3]:
                short_type = leak_type[:8] + ".." if len(leak_type) > 8 else leak_type
                types_str += f"{short_type}:{count} "
            
            table += f"│ {username_display} │ {stat['total_leaks']:<14} │ {types_str:<27} │\n"
        
        table += "└──────────────┴────────────────┴─────────────────────────────┘\n"
        table += f"\n📈 Всего нарушителей: {len(stats)}"
        table += f"\n🕒 Последнее обновление: {datetime.now().strftime('%H:%M:%S')}"
        
        update.message.reply_text(f"<pre>{table}</pre>", parse_mode='HTML')
    
    def leakinfo_command(self, update: Update, context: CallbackContext):
        if not context.args:
            update.message.reply_text("ℹ️ Использование: /leakinfo [ID пользователя или @username]")
            return
        
        target = context.args[0].replace('@', '')
        
        user_id = None
        for uid, info in self.user_info.items():
            if info['username'] == target or str(uid) == target:
                user_id = uid
                break
        
        if not user_id or user_id not in self.leaks_by_user:
            update.message.reply_text("❌ Пользователь не найден или нарушений нет")
            return
        
        leaks = self.leaks_by_user[user_id]
        user = self.user_info[user_id]
        
        report = f"🔍 ИНФОРМАЦИЯ О НАРУШИТЕЛЕ\n\n"
        report += f"👤 Пользователь: @{user['username']}\n"
        report += f"🆔 ID: {user_id}\n"
        report += f"📛 Имя: {user['first_name']} {user.get('last_name', '')}\n"
        report += f"📅 Первый раз замечен: {user.get('first_seen', 'Неизвестно')}\n"
        report += f"📅 Последняя активность: {user.get('last_seen', 'Неизвестно')}\n\n"
        report += f"🚨 Всего нарушений: {len(leaks)}\n\n"
        
        type_stats = {}
        for leak in leaks:
            leak_type = leak['type']
            type_stats[leak_type] = type_stats.get(leak_type, 0) + 1
        
        report += "📊 Статистика по типам:\n"
        for leak_type, count in type_stats.items():
            percentage = (count / len(leaks)) * 100
            report += f"  {leak_type}: {count} ({percentage:.1f}%)\n"
        
        if leaks:
            report += f"\n🕒 Последние нарушения:\n"
            for i, leak in enumerate(leaks[-5:][::-1], 1):
                time_str = datetime.fromisoformat(leak['timestamp']).strftime("%d.%m %H:%M")
                report += f"{i}. {time_str} - {leak['type']}\n"
                if leak['details']:
                    report += f"   {leak['details'][:50]}\n"
        
        update.message.reply_text(f"<pre>{report}</pre>", parse_mode='HTML')
    
    def pingstatus_command(self, update: Update, context: CallbackContext):
        if update.message.from_user.id != YOUR_ID:
            update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        uptime = (datetime.now() - self.bot_start_time).seconds
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        
        status = "🟢 ВКЛЮЧЕН" if self.self_ping_enabled else "🔴 ВЫКЛЮЧЕН"
        
        message = f"📡 СТАТУС САМОПИНГА\n\n"
        message += f"Состояние: {status}\n"
        message += f"Всего пингов: {self.ping_count}\n"
        message += f"Время работы: {hours}ч {minutes}м\n"
        message += f"Интервал пинга: {SELF_PING_INTERVAL} секунд\n"
        
        if self.last_successful_ping:
            last_ping_ago = (datetime.now() - self.last_successful_ping).seconds // 60
            last_time = self.last_successful_ping.strftime("%H:%M:%S")
            message += f"Последний пинг: {last_time} ({last_ping_ago} минут назад)\n"
        else:
            message += f"Последний пинг: Никогда\n"
        
        message += f"\n🔗 URL приложения: {RENDER_URL}"
        
        update.message.reply_text(message)
    
    def toggleping_command(self, update: Update, context: CallbackContext):
        if update.message.from_user.id != YOUR_ID:
            update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        self.self_ping_enabled = not self.self_ping_enabled
        status = "🟢 ВКЛЮЧЕН" if self.self_ping_enabled else "🔴 ВЫКЛЮЧЕН"
        
        update.message.reply_text(f"🔄 Самопинг теперь {status}")
        
        if self.self_ping_enabled:
            threading.Thread(target=self.perform_self_ping, daemon=True).start()
    
    def status_command(self, update: Update, context: CallbackContext):
        uptime = (datetime.now() - self.bot_start_time).seconds
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        
        status = f"🤖 СТАТУС БОТА\n\n"
        status += f"📍 Хостинг: Render\n"
        status += f"⏰ Время работы: {hours}ч {minutes}м\n"
        status += f"📊 Нарушителей: {len(self.leaks_by_user)}\n"
        status += f"👤 Мониторится пользователей: {len(self.user_info)}\n"
        status += f"🔗 URL: {RENDER_URL}\n"
        status += f"🏓 Самопинг: {'Включен' if self.self_ping_enabled else 'Выключен'}\n"
        status += f"🔄 Всего пингов: {self.ping_count}"
        
        update.message.reply_text(status)
    
    def clear_command(self, update: Update, context: CallbackContext):
        if update.message.from_user.id != YOUR_ID:
            update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        if len(context.args) > 0 and context.args[0] == "confirm":
            self.leaks_by_user.clear()
            self.user_info.clear()
            self.save_data()
            update.message.reply_text("✅ Все данные очищены")
        else:
            update.message.reply_text(
                "⚠️ Вы уверены, что хотите очистить все данные?\n"
                "Для подтверждения: /clear confirm"
            )
    
    def load_data(self):
        try:
            if os.path.exists('leak_data.json'):
                with open('leak_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    self.leaks_by_user = defaultdict(list)
                    for user_id_str, leaks in data.get('leaks', {}).items():
                        self.leaks_by_user[int(user_id_str)] = leaks
                    
                    self.user_info = {int(k): v for k, v in data.get('users', {}).items()}
                    
                logger.info(f"📂 Данные загружены")
            else:
                logger.info("📂 Файл с данными не найден")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки данных: {e}")
    
    def save_data(self):
        try:
            data = {
                'leaks': dict(self.leaks_by_user),
                'users': self.user_info,
                'last_save': datetime.now().isoformat(),
                'ping_count': self.ping_count,
                'bot_start_time': self.bot_start_time.isoformat()
            }
            
            with open('leak_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения данных: {e}")
            return False
    
    def run(self):
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        logger.info(f"🚀 Бот запускается на порту {PORT}")
        
        try:
            self.updater.bot.send_message(
                chat_id=YOUR_ID,
                text=f"🤖 LeakTracker Bot запущен!\n📍 Хостинг: Render\n🔗 URL: {RENDER_URL}"
            )
        except:
            pass
        
        self.updater.start_polling()
        logger.info("✅ Бот начал работу")
        
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown()
    
    def shutdown(self):
        logger.info("🛑 Завершение работы бота...")
        self.is_running = False
        self.save_data()
        self.updater.stop()
        logger.info("👋 Бот остановлен")

if __name__ == '__main__':
    try:
        bot = TelegramLeakBot()
        bot.run()
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка: {e}")
        raise
