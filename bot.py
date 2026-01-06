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
# Все эти переменные нужно установить в настройках Render
TOKEN = os.environ.get("TELEGRAM_TOKEN")  # Токен бота от @BotFather
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID"))  # Ваш ID Telegram
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")  # URL вашего приложения на Render
PORT = int(os.environ.get("PORT", 5000))  # Порт для Flask

# Дополнительные настройки (необязательные)
SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 600))  # Интервал пинга в секундах (по умолчанию 10 мин)
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))  # Интервал автосохранения в секундах
# =======================================================

# Проверка обязательных переменных
if not TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не установлен в переменных окружения")
if not YOUR_ID:
    raise ValueError("❌ YOUR_TELEGRAM_ID не установлен в переменных окружения")
if not RENDER_URL:
    raise ValueError("❌ RENDER_EXTERNAL_URL не установлен в переменных окружения")

# Flask приложение
app = Flask(__name__)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramLeakBot:
    def __init__(self):
        # Время старта для отсчета аптайма
        self.bot_start_time = datetime.now()
        
        # Структуры данных для хранения информации
        self.leaks_by_user = defaultdict(list)  # ID пользователя -> список нарушений
        self.user_info = {}  # ID пользователя -> информация о пользователе
        
        # Настройки самопинга
        self.ping_count = 0
        self.last_successful_ping = None
        self.self_ping_enabled = True
        self.is_running = True
        
        # Инициализация Telegram бота
        self.updater = Updater(TOKEN, use_context=True)
        self.dp = self.updater.dispatcher
        
        # Регистрация обработчиков команд
        self.register_handlers()
        
        # Загрузка сохраненных данных
        self.load_data()
        
        # Запуск фоновых задач
        self.start_background_tasks()
        
        # Настройка Flask эндпоинтов
        self.setup_flask_endpoints()
        
        logger.info(f"🤖 Бот инициализирован для работы на Render")
        logger.info(f"🔗 URL: {RENDER_URL}")
        logger.info(f"👤 Ваш ID: {YOUR_ID}")
    
    def register_handlers(self):
        """Регистрация команд бота"""
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
        """Настройка Flask эндпоинтов"""
        @app.route('/')
        def home():
            uptime = (datetime.now() - self.bot_start_time).seconds
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            return f"""
            <h1>🤖 LeakTracker Bot</h1>
            <p>✅ Бот работает! Uptime: {hours}ч {minutes}м</p>
            <p>🔗 <a href="/health">Health Check</a></p>
            <p>🏓 <a href="/ping">Ping</a></p>
            <p>📊 Нарушителей: {len(self.leaks_by_user)}</p>
            """
        
        @app.route('/health')
        def health():
            return {
                "status": "active",
                "service": "telegram-leak-bot",
                "uptime_seconds": (datetime.now() - self.bot_start_time).seconds,
                "ping_count": self.ping_count,
                "leak_count": len(self.leaks_by_user),
                "user_count": len(self.user_info),
                "last_ping": self.last_successful_ping.isoformat() if self.last_successful_ping else None,
                "self_ping_enabled": self.self_ping_enabled
            }
        
        @app.route('/ping')
        def ping():
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            return {
                "status": "pong",
                "ping_number": self.ping_count,
                "timestamp": datetime.now().isoformat(),
                "message": f"🏓 PONG! Ping #{self.ping_count}"
            }
    
    def start_background_tasks(self):
        """Запуск фоновых задач"""
        def self_ping_task():
            """Задача самопинга для предотвращения сна на Render"""
            while self.is_running:
                if self.self_ping_enabled:
                    self.perform_self_ping()
                time.sleep(SELF_PING_INTERVAL)  # Используем значение из переменных
        
        def auto_save_task():
            """Автосохранение данных"""
            while self.is_running:
                time.sleep(AUTO_SAVE_INTERVAL)  # Используем значение из переменных
                self.save_data()
                logger.debug("💾 Данные автосохранены")
        
        # Запускаем задачи в отдельных потоках
        threading.Thread(target=self_ping_task, daemon=True).start()
        threading.Thread(target=auto_save_task, daemon=True).start()
        
        logger.info(f"🔄 Фоновые задачи запущены: самопинг каждые {SELF_PING_INTERVAL}с, автосохранение каждые {AUTO_SAVE_INTERVAL}с")
    
    def perform_self_ping(self):
        """Выполнение самопинга"""
        try:
            # Пробуем несколько эндпоинтов
            endpoints = [
                f"{RENDER_URL}",
                f"{RENDER_URL}/health",
                f"{RENDER_URL}/ping"
            ]
            
            for endpoint in endpoints:
                response = requests.get(endpoint, timeout=15)
                if response.status_code == 200:
                    logger.debug(f"✅ Успешный пинг {endpoint}")
            
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            
            # Раз в 50 пингов логируем подробнее
            if self.ping_count % 50 == 0:
                logger.info(f"✅ Самопинг #{self.ping_count} выполнен успешно")
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка самопинга: {str(e)[:100]}")
    
    def monitor_messages(self, update: Update, context: CallbackContext):
        """Мониторинг сообщений на утечки"""
        msg = update.message
        if not msg or msg.chat.type == 'private':
            return
        
        user_id = msg.from_user.id
        chat_id = msg.chat.id
        
        # Сохраняем информацию о пользователе
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
        
        # Проверяем на утечки
        leak_info = self.detect_leak(msg)
        
        if leak_info:
            self.handle_leak(user_id, leak_info, msg, context)
    
    def detect_leak(self, msg):
        """Обнаружение утечки в сообщении"""
        leak_type = None
        leak_details = ""
        
        # 1. ПРОВЕРКА ПЕРЕСЫЛКИ
        if msg.forward_from_chat:
            leak_type = "ПЕРЕСЫЛКА В ЧАТ"
            leak_details = f"В чат: {msg.forward_from_chat.title}"
            
        elif msg.forward_from:
            leak_type = "ПЕРЕСЫЛКА ПОЛЬЗОВАТЕЛЮ"
            target = msg.forward_from.username or f"id{msg.forward_from.id}"
            leak_details = f"Пользователю: {target}"
        
        # 2. ПРОВЕРКА ССЫЛОК
        elif msg.text or msg.caption:
            text = msg.text or msg.caption
            chat_id = msg.chat.id
            
            # Ссылки на сообщения Telegram
            telegram_link_pattern = r't\.me/(?:c/)?[a-zA-Z0-9_\-/]+'
            if re.search(telegram_link_pattern, text):
                leak_type = "КОПИРОВАНИЕ ССЫЛКИ"
                leak_details = "Скопировал ссылку на сообщение"
            
            # Длинные тексты (возможно копирование)
            elif len(text) > 300 and '\n' in text:
                leak_type = "КОПИРОВАНИЕ ТЕКСТА"
                leak_details = f"Скопировал {len(text)} символов"
        
        # 3. ПРОВЕРКА НА СКРИНШОТ
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
        """Вычисление вероятности скриншота"""
        score = 0
        
        # Признаки скриншота:
        
        # 1. Реакция на старое сообщение
        if hasattr(msg, 'reply_to_message') and msg.reply_to_message:
            time_diff = (msg.date - msg.reply_to_message.date).total_seconds()
            if time_diff > 180:  # Более 3 минут
                score += 30
        
        # 2. Короткое сообщение с эмодзи
        if msg.text and len(msg.text) < 15:
            screenshot_emojis = ['📸', '🖼', '💾', '📱', '📲', '⬇️', '⬆️', '👇', '👆']
            if any(emoji in msg.text for emoji in screenshot_emojis):
                score += 40
        
        # 3. Сохранение медиа
        if msg.photo or msg.video or msg.document:
            score += 20
        
        return min(score, 100)
    
    def handle_leak(self, user_id, leak_info, msg, context):
        """Обработка обнаруженной утечки"""
        # Сохраняем утечку
        self.leaks_by_user[user_id].append(leak_info)
        
        # Ограничиваем историю до 50 нарушений на пользователя
        if len(self.leaks_by_user[user_id]) > 50:
            self.leaks_by_user[user_id] = self.leaks_by_user[user_id][-50:]
        
        # Отправляем уведомление владельцу
        self.send_leak_alert(user_id, leak_info, msg, context)
        
        # Автосохранение
        self.save_data()
    
    def send_leak_alert(self, user_id, leak_info, msg, context):
        """Отправка уведомления о утечке владельцу"""
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
            logger.info(f"📤 Уведомление отправлено владельцу о пользователе {user_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось отправить уведомление: {e}")
    
    # ========== КОМАНДЫ БОТА ==========
    
    def start_command(self, update: Update, context: CallbackContext):
        """Команда /start"""
        update.message.reply_text(
            "🛡️ LeakTracker Bot\n\n"
            "Я отслеживаю утечки информации из чатов.\n"
            "При обнаружении подозрительной активности я отправляю уведомление владельцу.\n\n"
            "📋 Доступные команды:\n"
            "/leakstats - таблица нарушителей\n"
            "/leakinfo [id] - информация о нарушителе\n"
            "/status - статус бота\n"
            "/help - справка"
        )
    
    def help_command(self, update: Update, context: CallbackContext):
        """Команда /help"""
        help_text = "📖 СПРАВКА ПО КОМАНДАМ\n\n"
        help_text += "/start - информация о боте\n"
        help_text += "/help - эта справка\n"
        help_text += "/leakstats - таблица всех нарушителей\n"
        help_text += "/leakinfo [id] - подробная информация о нарушителе\n"
        help_text += "/status - статус работы бота\n"
        help_text += "/pingstatus - статус самопинга (только для владельца)\n"
        help_text += "/toggleping - вкл/выкл самопинг (только для владельца)\n"
        help_text += "/clear - очистить данные (только для владельца)\n\n"
        help_text += "👁️ Бот автоматически отслеживает:\n"
        help_text += "• Пересылки сообщений\n"
        help_text += "• Копирование ссылок на сообщения\n"
        help_text += "• Подозрительную активность (скриншоты)"
        
        update.message.reply_text(help_text)
    
    def leakstats_command(self, update: Update, context: CallbackContext):
        """Команда /leakstats - таблица нарушителей"""
        if not self.leaks_by_user:
            update.message.reply_text("📭 Нарушителей не обнаружено")
            return
        
        # Подготавливаем данные
        stats = []
        for user_id, leaks in self.leaks_by_user.items():
            if not leaks:
                continue
            
            user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
            
            # Подсчет нарушений по типам
            leak_types = {}
            for leak in leaks[-20:]:  # Берем последние 20 нарушений
                leak_type = leak['type']
                leak_types[leak_type] = leak_types.get(leak_type, 0) + 1
            
            stats.append({
                'user_id': user_id,
                'username': user['username'],
                'total_leaks': len(leaks),
                'leak_types': leak_types
            })
        
        # Сортируем по количеству нарушений
        stats.sort(key=lambda x: x['total_leaks'], reverse=True)
        
        # Формируем таблицу
        table = "📊 ТАБЛИЦА НАРУШИТЕЛЕЙ\n\n"
        table += "┌──────────────┬────────────────┬─────────────────────────────┐\n"
        table += "│ Пользователь │ Всего нарушений │ Основные типы нарушений    │\n"
        table += "├──────────────┼────────────────┼─────────────────────────────┤\n"
        
        for stat in stats[:15]:  # Показываем топ-15
            username = f"@{stat['username']}" if stat['username'].startswith('id') == False else stat['username']
            username_display = username[:12].ljust(12)
            
            # Формируем строку с типами нарушений
            types_str = ""
            for leak_type, count in list(stat['leak_types'].items())[:3]:  # Берем первые 3 типа
                short_type = leak_type[:8] + ".." if len(leak_type) > 8 else leak_type
                types_str += f"{short_type}:{count} "
            
            table += f"│ {username_display} │ {stat['total_leaks']:<14} │ {types_str:<27} │\n"
        
        table += "└──────────────┴────────────────┴─────────────────────────────┘\n"
        table += f"\n📈 Всего нарушителей: {len(stats)}"
        table += f"\n🕒 Последнее обновление: {datetime.now().strftime('%H:%M:%S')}"
        
        update.message.reply_text(f"<pre>{table}</pre>", parse_mode='HTML')
    
    def leakinfo_command(self, update: Update, context: CallbackContext):
        """Команда /leakinfo - информация о нарушителе"""
        if not context.args:
            update.message.reply_text("ℹ️ Использование: /leakinfo [ID пользователя или @username]")
            return
        
        target = context.args[0].replace('@', '')
        
        # Ищем пользователя
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
        
        # Формируем отчет
        report = f"🔍 ИНФОРМАЦИЯ О НАРУШИТЕЛЕ\n\n"
        report += f"👤 Пользователь: @{user['username']}\n"
        report += f"🆔 ID: {user_id}\n"
        report += f"📛 Имя: {user['first_name']} {user.get('last_name', '')}\n"
        report += f"📅 Первый раз замечен: {user.get('first_seen', 'Неизвестно')}\n"
        report += f"📅 Последняя активность: {user.get('last_seen', 'Неизвестно')}\n\n"
        report += f"🚨 Всего нарушений: {len(leaks)}\n\n"
        
        # Статистика по типам нарушений
        type_stats = {}
        for leak in leaks:
            leak_type = leak['type']
            type_stats[leak_type] = type_stats.get(leak_type, 0) + 1
        
        report += "📊 Статистика по типам:\n"
        for leak_type, count in type_stats.items():
            percentage = (count / len(leaks)) * 100
            report += f"  {leak_type}: {count} ({percentage:.1f}%)\n"
        
        # Последние 5 нарушений
        if leaks:
            report += f"\n🕒 Последние нарушения:\n"
            for i, leak in enumerate(leaks[-5:][::-1], 1):
                time_str = datetime.fromisoformat(leak['timestamp']).strftime("%d.%m %H:%M")
                report += f"{i}. {time_str} - {leak['type']}\n"
                if leak['details']:
                    report += f"   {leak['details'][:50]}\n"
        
        update.message.reply_text(f"<pre>{report}</pre>", parse_mode='HTML')
    
    def pingstatus_command(self, update: Update, context: CallbackContext):
        """Команда /pingstatus - статус самопинга"""
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
        message += f"\n🏓 Ping endpoint: {RENDER_URL}/ping"
        message += f"\n❤️ Health 
