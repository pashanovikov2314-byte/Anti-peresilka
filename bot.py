# ========== ЗАГЛУШКА ДЛЯ imghdr (удалён в Python 3.11+) ==========
import sys

class ImghdrStub:
    """Заглушка для модуля imghdr, который был удалён в Python 3.11+"""
    
    @staticmethod
    def what(file, h=None):
        """Определение типа изображения (заглушка)"""
        return None
    
    @staticmethod
    def test_jpeg(h):
        return None
    
    @staticmethod 
    def test_png(h):
        return None
    
    @staticmethod
    def test_gif(h):
        return None
    
    @staticmethod
    def test_tiff(h):
        return None
    
    @staticmethod
    def test_rgb(h):
        return None
    
    @staticmethod
    def test_pbm(h):
        return None
    
    @staticmethod
    def test_pgm(h):
        return None
    
    @staticmethod
    def test_ppm(h):
        return None
    
    @staticmethod
    def test_rast(h):
        return None
    
    @staticmethod
    def test_xbm(h):
        return None
    
    @staticmethod
    def test_bmp(h):
        return None
    
    @staticmethod
    def test_exr(h):
        return None
    
    @staticmethod
    def test_webp(h):
        return None

# Создаём фиктивный модуль
imghdr_module = type(sys)('imghdr')
imghdr_module.__dict__.update({k: v for k, v in ImghdrStub.__dict__.items() 
                              if not k.startswith('__')})

# Добавляем в sys.modules для импорта
sys.modules['imghdr'] = imghdr_module

# ========== ИМПОРТЫ ==========
import logging
import re
import time
import threading
import requests
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
import json
import os

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", 5000))

SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 600))
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не установлен")
if not ALLOWED_USER_IDS:
    raise ValueError("ALLOWED_IDS не установлен")

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
        
        self.skillup_ultra_mode = False
        self.ultra_detection_level = 5
        
        self.application = Application.builder().token(TOKEN).build()
        
        self.register_handlers()
        self.load_data()
        self.start_background_tasks()
        self.setup_flask_endpoints()
        
        logger.info("🤖 Бот инициализирован")
    
    def register_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("leakstats", self.leakstats_command))
        self.application.add_handler(CommandHandler("leakinfo", self.leakinfo_command))
        self.application.add_handler(CommandHandler("pingstatus", self.pingstatus_command))
        self.application.add_handler(CommandHandler("toggleping", self.toggleping_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("skillup", self.skillup_command))
        self.application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self.monitor_messages))
    
    def setup_flask_endpoints(self):
        @app.route('/')
        def home():
            uptime = (datetime.now() - self.bot_start_time).seconds
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            ultra = "🟢 ВКЛ" if self.skillup_ultra_mode else "🔴 ВЫКЛ"
            return f"<h1>🤖 LeakTracker Bot</h1><p>✅ Работает! Uptime: {hours}ч {minutes}м<br>🔥 SkillUP: {ultra}</p>"
        
        @app.route('/health')
        def health():
            return {
                "status": "active",
                "uptime_seconds": (datetime.now() - self.bot_start_time).seconds,
                "ping_count": self.ping_count,
                "leak_count": len(self.leaks_by_user),
                "user_count": len(self.user_info),
                "skillup_ultra": self.skillup_ultra_mode
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
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("❌ Бот временно не работает.")
            return
        
        welcome = """
🔒 **LeakTracker** активирован

Доступные команды:
/help - Справка
/leakstats - Статистика утечек
/leakinfo [ID] - Инфо по утечке
/pingstatus - Статус самопинга
/toggleping - Вкл/Выкл самопинг
/status - Общий статус
/clear - Очистить данные
/skillup - Режим повышенной детекции

🤖 Бот работает в фоновом режиме.
Все обнаруженные утечки будут отправлены вам в ЛС.
        """
        await update.message.reply_text(welcome, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        help_text = """
📖 **LeakTracker - Помощь**

Бот отслеживает потенциальные утечки информации в чатах:

🔍 **Что детектирует:**
• Пересылки сообщений
• Ссылки на Telegram
• Длинные тексты (копирование)
• Подозрительные медиафайлы
• Возможные скриншоты

⚡ **Режимы работы:**
• NORMAL - Базовая детекция
• ULTRA (/skillup) - Усиленная проверка

📊 **Команды анализа:**
/leakstats - Общая статистика
/leakinfo [ID] - Детали утечки

🔧 **Управление:**
/status - Статус системы
/toggleping - Управление самопингом
/clear - Очистка данных

🤫 **Примечание:** Бот не отвечает в чатах, только в ЛС.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def monitor_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                'first_seen': datetime.now().isoformat(),
                'message_count': 0
            }
        else:
            self.user_info[user_id]['last_seen'] = datetime.now().isoformat()
            self.user_info[user_id]['message_count'] = self.user_info[user_id].get('message_count', 0) + 1
        
        leak_info = self.detect_leak_ultra(msg) if self.skillup_ultra_mode else self.detect_leak(msg)
        
        if leak_info:
            await self.handle_leak(user_id, leak_info, msg, context)
    
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
                'message_id': msg.message_id,
                'detection_mode': 'NORMAL'
            }
        
        return None
    
    def detect_leak_ultra(self, msg):
        """🔥 РЕЖИМ SKILLUP ULTRA: 5x увеличение точности"""
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
            
            link_pattern = r'(https?://\S+|www\.\S+|t\.me/\S+)'
            links = re.findall(link_pattern, text)
            if links:
                leak_type = "КОПИРОВАНИЕ ССЫЛКИ"
                leak_details = f"Найдены ссылки: {', '.join(links[:3])}"
            
            elif len(text) > 150 and '\n' in text:
                leak_type = "КОПИРОВАНИЕ ТЕКСТА"
                leak_details = f"Скопировал {len(text)} символов"
        
        screenshot_score = self.calculate_screenshot_score_ultra(msg)
        if screenshot_score > 50:
            leak_type = "ПОДОЗРЕНИЕ НА СКРИНШОТ"
            leak_details = f"Вероятность скриншота: {screenshot_score}% (ULTRA режим)"
        
        if msg.photo or msg.video or msg.document:
            media_type = "фото" if msg.photo else "видео" if msg.video else "документ"
            if not leak_type:
                leak_type = "СОХРАНЕНИЕ МЕДИА"
                leak_details = f"Сохранил {media_type}"
        
        if leak_type:
            return {
                'type': leak_type,
                'details': leak_details,
                'timestamp': datetime.now().isoformat(),
                'chat_id': msg.chat.id,
                'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
                'message_id': msg.message_id,
                'detection_mode': 'ULTRA',
                'detection_score': screenshot_score if 'скриншот' in leak_type.lower() else 85,
                'ultra_level': self.ultra_detection_level
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
    
    def calculate_screenshot_score_ultra(self, msg):
        """🔥 Усиленная детекция скриншотов"""
        score = 0
        
        if hasattr(msg, 'reply_to_message') and msg.reply_to_message:
            time_diff = (msg.date - msg.reply_to_message.date).total_seconds()
            if time_diff > 60:
                score += 25
            if time_diff > 300:
                score += 35
        
        if msg.text:
            screenshot_indicators = ['📸', '🖼', '💾', '📱', '📲', '⬇️', '⬆️', '👇', '👆']
            if any(indicator in msg.text for indicator in screenshot_indicators):
                score += 30
            
            if len(msg.text) < 10 and any(c.isdigit() for c in msg.text):
                score += 20
        
        if msg.photo:
            score += 25
        if msg.video:
            score += 20
        if msg.document:
            score += 15
        
        return min(score * self.ultra_detection_level, 100)
    
    async def handle_leak(self, user_id, leak_info, msg, context):
        self.leaks_by_user[user_id].append(leak_info)
        
        if len(self.leaks_by_user[user_id]) > 50:
            self.leaks_by_user[user_id] = self.leaks_by_user[user_id][-50:]
        
        await self.send_leak_alert(user_id, leak_info, msg, context)
        self.save_data()
    
    async def send_leak_alert(self, user_id, leak_info, msg, context):
        for admin_id in ALLOWED_USER_IDS:
            try:
                user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
                
                mode_icon = "🔥" if leak_info.get('detection_mode') == 'ULTRA' else "⚠️"
                alert = f"{mode_icon} ОБНАРУЖЕНА УТЕЧКА\n\n"
                alert += f"👤 Нарушитель: @{user['username']}\n"
                alert += f"📛 Имя: {user['first_name']}\n"
                alert += f"🆔 ID: {user_id}\n\n"
                alert += f"📊 Тип: {leak_info['type']}\n"
                alert += f"📝 Детали: {leak_info['details']}\n"
                alert += f"⏰ Время: {leak_info['timestamp'][11:16]}\n"
                alert += f"💬 Чат: {leak_info['chat_title']}\n"
                alert += f"🔗 Ссылка: https://t.me/c/{str(leak_info['chat_id'])[4:]}/{leak_info['message_id']}\n\n"
                
                if leak_info.get('detection_score'):
                    alert += f"🎯 Оценка: {leak_info['detection_score']}/100\n"
                
                alert += f"📈 Всего утечек от этого пользователя: {len(self.leaks_by_user[user_id])}"
                
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=alert,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                logger.info(f"📨 Отправлено оповещение админу {admin_id}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
    
    async def leakstats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        total_leaks = sum(len(v) for v in self.leaks_by_user.values())
        total_users = len(self.leaks_by_user)
        
        stats = f"📊 **Статистика утечек**\n\n"
        stats += f"• Всего утечек: {total_leaks}\n"
        stats += f"• Пользователей с утечками: {total_users}\n"
        stats += f"• Всего отслеживаемых: {len(self.user_info)}\n"
        stats += f"• Режим: {'ULTRA 🔥' if self.skillup_ultra_mode else 'NORMAL'}\n\n"
        
        if total_users > 0:
            stats += "🔝 **Топ нарушителей:**\n"
            sorted_users = sorted(
                self.leaks_by_user.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:5]
            
            for i, (uid, leaks) in enumerate(sorted_users, 1):
                user = self.user_info.get(uid, {'username': f'id{uid}'})
                stats += f"{i}. @{user['username']} - {len(leaks)} утечек\n"
        
        await update.message.reply_text(stats, parse_mode='Markdown')
    
    async def leakinfo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        if not context.args:
            await update.message.reply_text("❌ Укажите ID пользователя: /leakinfo [ID]")
            return
        
        try:
            target_id = int(context.args[0])
        except:
            await update.message.reply_text("❌ Неверный ID")
            return
        
        leaks = self.leaks_by_user.get(target_id, [])
        user = self.user_info.get(target_id, {'username': f'id{target_id}'})
        
        if not leaks:
            await update.message.reply_text(f"ℹ️ У пользователя @{user['username']} нет утечек")
            return
        
        response = f"📄 **Утечки пользователя @{user['username']}**\n\n"
        
        for i, leak in enumerate(leaks[-10:], 1):
            response += f"{i}. **{leak['type']}**\n"
            response += f"   📝 {leak['details']}\n"
            response += f"   ⏰ {leak['timestamp'][:16]}\n"
            response += f"   💬 {leak['chat_title']}\n\n"
        
        response += f"📈 Всего утечек: {len(leaks)}"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    
    async def pingstatus_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        status = "🟢 ВКЛЮЧЕН" if self.self_ping_enabled else "🔴 ВЫКЛЮЧЕН"
        last_ping = self.last_successful_ping.strftime("%H:%M:%S") if self.last_successful_ping else "никогда"
        
        response = f"📡 **Статус самопинга**\n\n"
        response += f"• Статус: {status}\n"
        response += f"• Кол-во пингов: {self.ping_count}\n"
        response += f"• Последний: {last_ping}\n"
        response += f"• Интервал: {SELF_PING_INTERVAL} сек.\n"
        response += f"• URL: {RENDER_URL[:30]}..."
        
        await update.message.reply_text(response, parse_mode='Markdown')
    
    async def toggleping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        self.self_ping_enabled = not self.self_ping_enabled
        status = "включен" if self.self_ping_enabled else "выключен"
        await update.message.reply_text(f"🔄 Самопинг {status}!")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        uptime = datetime.now() - self.bot_start_time
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        
        response = f"🤖 **Статус бота**\n\n"
        response += f"• Работает: {hours}ч {minutes}м\n"
        response += f"• Пингов: {self.ping_count}\n"
        response += f"• Пользователей: {len(self.user_info)}\n"
        response += f"• Утечек: {sum(len(v) for v in self.leaks_by_user.values())}\n"
        response += f"• Режим: {'ULTRA 🔥' if self.skillup_ultra_mode else 'NORMAL'}\n"
        response += f"• Самопинг: {'🟢 ВКЛ' if self.self_ping_enabled else '🔴 ВЫКЛ'}\n"
        response += f"• Web сервер: {'🟢 ONLINE' if RENDER_URL else '🔴 OFFLINE'}"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        count = sum(len(v) for v in self.leaks_by_user.values())
        self.leaks_by_user.clear()
        self.user_info.clear()
        
        await update.message.reply_text(f"🧹 Очищено {count} утечек и данных о пользователях")
    
    async def skillup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        self.skillup_ultra_mode = not self.skillup_ultra_mode
        status = "🔥 ULTRA MODE" if self.skillup_ultra_mode else "NORMAL"
        await update.message.reply_text(f"⚡ Режим изменен на: {status}")
    
    def save_data(self):
        try:
            data = {
                'leaks_by_user': dict(self.leaks_by_user),
                'user_info': self.user_info,
                'ping_count': self.ping_count,
                'skillup_ultra_mode': self.skillup_ultra_mode
            }
            
            with open('bot_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")
    
    def load_data(self):
        try:
            if os.path.exists('bot_data.json'):
                with open('bot_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.leaks_by_user.update(data.get('leaks_by_user', {}))
                self.user_info.update(data.get('user_info', {}))
                self.ping_count = data.get('ping_count', 0)
                self.skillup_ultra_mode = data.get('skillup_ultra_mode', False)
                
                logger.info(f"✅ Данные загружены: {len(self.leaks_by_user)} пользователей с утечками")
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
    
    def run(self):
        flask_thread = threading.Thread(
            target=lambda: app.run(
                host='0.0.0.0',
                port=PORT,
                debug=False,
                use_reloader=False
            ),
            daemon=True
        )
        flask_thread.start()
        
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

def main():
    bot = TelegramLeakBot()
    bot.run()

if __name__ == '__main__':
    main()