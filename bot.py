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

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВАШ_ТОКЕН")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", "123456789"))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ваш-бот.onrender.com")
PORT = int(os.environ.get("PORT", 5000))
# ==================================

# Flask приложение для Render
app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SelfPingBot:
    def __init__(self):
        self.bot_start_time = datetime.now()
        self.leaks_by_user = defaultdict(list)
        self.user_info = {}
        
        # Статистика самопинга
        self.ping_count = 0
        self.last_successful_ping = None
        self.self_ping_enabled = True
        
        # Инициализируем бота
        self.updater = Updater(TOKEN, use_context=True)
        self.dp = self.updater.dispatcher
        
        # Регистрация обработчиков
        self.register_handlers()
        
        # Загрузка данных
        self.load_data()
        
        # Запуск фоновых задач
        self.start_background_tasks()
        
        logger.info("🤖 Бот инициализирован с самопингом")
    
    def register_handlers(self):
        """Регистрация команд бота"""
        self.dp.add_handler(CommandHandler("start", self.start_cmd))
        self.dp.add_handler(CommandHandler("leakstats", self.leakstats_cmd))
        self.dp.add_handler(CommandHandler("pingstatus", self.pingstatus_cmd))
        self.dp.add_handler(CommandHandler("toggleping", self.toggleping_cmd))
        self.dp.add_handler(MessageHandler(Filters.all & ~Filters.command, self.monitor_messages))
    
    def start_background_tasks(self):
        """Запуск фоновых задач для самопинга и автосохранения"""
        # Задача самопинга каждые 10 минут
        def self_ping_task():
            while True:
                if self.self_ping_enabled:
                    self.perform_self_ping()
                time.sleep(600)  # 10 минут
        
        # Автосохранение данных каждые 5 минут
        def auto_save_task():
            while True:
                time.sleep(300)  # 5 минут
                self.save_data()
                logger.info("💾 Данные автосохранены")
        
        # Запускаем в отдельных потоках
        threading.Thread(target=self_ping_task, daemon=True).start()
        threading.Thread(target=auto_save_task, daemon=True).start()
        
        # Также создаем Flask эндпоинты для проверки
        @app.route('/')
        def home():
            return f"✅ Бот работает! Uptime: {(datetime.now() - self.bot_start_time).seconds // 60} мин"
        
        @app.route('/health')
        def health():
            return {
                "status": "active",
                "uptime": (datetime.now() - self.bot_start_time).seconds,
                "ping_count": self.ping_count,
                "leak_count": len(self.leaks_by_user),
                "last_ping": self.last_successful_ping.isoformat() if self.last_successful_ping else None
            }
        
        @app.route('/ping')
        def ping_endpoint():
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            return f"🏓 PONG! Ping #{self.ping_count} at {datetime.now().strftime('%H:%M:%S')}"
    
    def perform_self_ping(self):
        """Выполнение самопинга - бот сам себя будит"""
        try:
            # Пинг 1: Pingdom-стиль - запрос к корневому URL
            response1 = requests.get(RENDER_URL, timeout=10)
            
            # Пинг 2: Запрос к health endpoint
            response2 = requests.get(f"{RENDER_URL}/health", timeout=10)
            
            # Пинг 3: Запрос к ping endpoint
            response3 = requests.get(f"{RENDER_URL}/ping", timeout=10)
            
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            
            logger.info(f"✅ Самопинг #{self.ping_count} выполнен успешно")
            logger.info(f"   Статусы: {response1.status_code}, {response2.status_code}, {response3.status_code}")
            
            # Если пинги успешны, отправляем уведомление в телеграм (раз в 100 пингов)
            if self.ping_count % 100 == 0:
                self.send_ping_report()
                
        except Exception as e:
            logger.error(f"❌ Ошибка самопинга: {e}")
            
            # Пытаемся восстановиться - отправляем уведомление владельцу
            try:
                self.updater.bot.send_message(
                    chat_id=YOUR_ID,
                    text=f"⚠️ Ошибка самопинга: {str(e)[:200]}"
                )
            except:
                pass
    
    def send_ping_report(self):
        """Отправка отчета о самопинге владельцу"""
        try:
            uptime = (datetime.now() - self.bot_start_time).seconds
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            
            report = f"📊 ОТЧЕТ САМОПИНГА\n\n"
            report += f"✅ Бот активен: {hours}ч {minutes}м\n"
            report += f"🔁 Всего пингов: {self.ping_count}\n"
            report += f"📈 Обнаружено нарушителей: {len(self.leaks_by_user)}\n"
            report += f"👤 Мониторится пользователей: {len(self.user_info)}\n"
            report += f"🕒 Последний пинг: {self.last_successful_ping.strftime('%H:%M:%S') if self.last_successful_ping else 'Никогда'}\n"
            report += f"🔗 URL: {RENDER_URL}"
            
            self.updater.bot.send_message(
                chat_id=YOUR_ID,
                text=report
            )
        except Exception as e:
            logger.error(f"Не удалось отправить отчет: {e}")
    
    def monitor_messages(self, update: Update, context: CallbackContext):
        """Мониторинг сообщений на утечки"""
        msg = update.message
        if not msg or msg.chat.type == 'private':
            return
        
        user_id = msg.from_user.id
        
        # Сохраняем информацию о пользователе
        if user_id not in self.user_info:
            self.user_info[user_id] = {
                'username': msg.from_user.username or f"id{user_id}",
                'first_name': msg.from_user.first_name or "",
                'last_name': msg.from_user.last_name or "",
                'last_seen': datetime.now().isoformat()
            }
        
        # Проверяем на утечки
        leak_detected = False
        leak_type = None
        leak_details = ""
        
        # 1. ПРОВЕРКА ПЕРЕСЫЛКИ
        if msg.forward_from_chat:
            leak_detected = True
            leak_type = "ПЕРЕСЫЛКА В ЧАТ"
            leak_details = f"В чат: {msg.forward_from_chat.title}"
            
        elif msg.forward_from:
            leak_detected = True
            leak_type = "ПЕРЕСЫЛКА ПОЛЬЗОВАТЕЛЮ"
            target = msg.forward_from.username or f"id{msg.forward_from.id}"
            leak_details = f"Пользователю: {target}"
        
        # 2. ПРОВЕРКА ССЫЛОК НА СООБЩЕНИЯ
        elif msg.text or msg.caption:
            text = msg.text or msg.caption
            chat_id = msg.chat.id
            
            if 't.me/c/' in text or (f"t.me/{str(chat_id).replace('-100', '')}" in text):
                leak_detected = True
                leak_type = "КОПИРОВАНИЕ ССЫЛКИ"
                leak_details = "Скопировал ссылку на сообщение"
            
            elif len(text) > 500 and '\n' in text and ':' in text:
                leak_detected = True
                leak_type = "КОПИРОВАНИЕ ТЕКСТА"
                leak_details = f"Скопировал {len(text)} символов"
        
        # 3. ПРОВЕРКА НА СКРИНШОТ
        screenshot_risk = self.check_screenshot_risk(msg)
        if screenshot_risk > 70:
            leak_detected = True
            leak_type = "ПОДОЗРЕНИЕ НА СКРИНШОТ"
            leak_details = f"Уровень риска: {screenshot_risk}%"
        
        # Если обнаружена утечка
        if leak_detected:
            self.record_leak(user_id, leak_type, leak_details, msg)
            self.send_alert_to_owner(user_id, leak_type, leak_details, msg, context)
    
    def check_screenshot_risk(self, msg):
        """Проверка риска скриншота"""
        risk = 0
        
        if hasattr(msg, 'reply_to_message') and msg.reply_to_message:
            original_time = msg.reply_to_message.date
            current_time = msg.date
            time_diff = (current_time - original_time).total_seconds()
            
            if time_diff > 300:
                risk += 40
        
        if msg.text and len(msg.text) < 10 and any(c in msg.text for c in ['📸', '🖼', '💾', '👇', '⬆️', '⬇️']):
            risk += 30
        
        return risk
    
    def record_leak(self, user_id, leak_type, details, msg):
        """Запись утечки в базу"""
        leak_record = {
            'timestamp': datetime.now().isoformat(),
            'type': leak_type,
            'details': details,
            'chat_id': msg.chat.id,
            'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
            'message_id': msg.message_id
        }
        
        self.leaks_by_user[user_id].append(leak_record)
        
        if len(self.leaks_by_user[user_id]) > 100:
            self.leaks_by_user[user_id] = self.leaks_by_user[user_id][-100:]
    
    def send_alert_to_owner(self, user_id, leak_type, details, msg, context):
        """Отправка уведомления владельцу в ЛС"""
        user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
        
        alert = f"🚨 ОБНАРУЖЕНА УТЕЧКА\n\n"
        alert += f"Нарушитель: @{user['username']}\n"
        alert += f"Имя: {user['first_name']} {user.get('last_name', '')}\n"
        alert += f"ID: {user_id}\n"
        alert += f"Чат: {msg.chat.title}\n"
        alert += f"Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
        alert += f"Тип нарушения: {leak_type}\n"
        alert += f"Детали: {details}"
        
        try:
            context.bot.send_message(
                chat_id=YOUR_ID,
                text=alert
            )
            logger.info(f"Уведомление отправлено владельцу о пользователе {user_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление: {e}")
    
    # ========== КОМАНДЫ БОТА ==========
    
    def start_cmd(self, update: Update, context: CallbackContext):
        help_text = "🛡️ LeakTracker Bot (Self-Ping Edition)\n\n"
        help_text += "Я отслеживаю утечки из чатов и отправляю уведомления вам в ЛС.\n"
        help_text += "Бот автоматически поддерживает свою работу 24/7.\n\n"
        help_text += "Команды:\n"
        help_text += "/leakstats - таблица всех нарушителей\n"
        help_text += "/pingstatus - статус самопинга\n"
        help_text += "/toggleping - вкл/выкл самопинг\n"
        
        update.message.reply_text(help_text)
    
    def leakstats_cmd(self, update: Update, context: CallbackContext):
        """Таблица нарушителей"""
        if not self.leaks_by_user:
            update.message.reply_text("Нарушителей не обнаружено")
            return
        
        stats = []
        for user_id, leaks in self.leaks_by_user.items():
            if not leaks:
                continue
            
            user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
            
            counts = defaultdict(int)
            for leak in leaks:
                counts[leak['type']] += 1
            
            stats.append({
                'user_id': user_id,
                'username': user['username'],
                'name': f"{user['first_name']} {user.get('last_name', '')}".strip(),
                'total': len(leaks),
                'counts': dict(counts)
            })
        
        stats.sort(key=lambda x: x['total'], reverse=True)
        
        table = "📊 ТАБЛИЦА НАРУШИТЕЛЕЙ\n\n"
        table += "┌──────────────┬────────────────┬─────────────────────────────────────────────┐\n"
        table += "│ Пользователь │ Всего нарушений │ Типы нарушений                            │\n"
        table += "├──────────────┼────────────────┼─────────────────────────────────────────────┤\n"
        
        for stat in stats[:20]:
            username = stat['username'] or f"id{stat['user_id']}"
            name = stat['name'][:10] + "..." if len(stat['name']) > 10 else stat['name']
            
            type_str = ""
            for leak_type, count in stat['counts'].items():
                short_type = leak_type[:15] + "..." if len(leak_type) > 15 else leak_type
                type_str += f"{short_type}: {count}, "
            type_str = type_str.rstrip(", ")
            
            table += f"│ @{username:<12} │ {stat['total']:<14} │ {type_str:<43} │\n"
        
        table += "└──────────────┴────────────────┴─────────────────────────────────────────────┘\n"
        table += f"\nВсего нарушителей: {len(stats)}"
        
        update.message.reply_text(f"<pre>{table}</pre>", parse_mode='HTML')
    
    def pingstatus_cmd(self, update: Update, context: CallbackContext):
        """Статус самопинга"""
        user_id = update.message.from_user.id
        
        if user_id != YOUR_ID:
            update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        uptime = (datetime.now() - self.bot_start_time).seconds
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        
        status = f"📡 СТАТУС САМОПИНГА\n\n"
        status += f"✅ Самопинг: {'ВКЛ' if self.self_ping_enabled else 'ВЫКЛ'}\n"
        status += f"🔁 Всего пингов: {self.ping_count}\n"
        status += f"⏰ Время работы: {hours}ч {minutes}м\n"
        status += f"🕒 Последний успешный пинг: "
        
        if self.last_successful_ping:
            time_diff = (datetime.now() - self.last_successful_ping).seconds // 60
            status += f"{self.last_successful_ping.strftime('%H:%M:%S')} ({time_diff} мин назад)\n"
        else:
            status += "Никогда\n"
        
        status += f"🔗 URL приложения: {RENDER_URL}\n"
        status += f"🌐 Health-check: {RENDER_URL}/health\n"
        status += f"🏓 Ping endpoint: {RENDER_URL}/ping"
        
        update.message.reply_text(status)
    
    def toggleping_cmd(self, update: Update, context: CallbackContext):
        """Включение/выключение самопинга"""
        user_id = update.message.from_user.id
        
        if user_id != YOUR_ID:
            update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        self.self_ping_enabled = not self.self_ping_enabled
        status = "ВКЛЮЧЕН" if self.self_ping_enabled else "ВЫКЛЮЧЕН"
        
        update.message.reply_text(f"🔄 Самопинг теперь {status}")
        
        # Если включили, сразу выполняем пинг
        if self.self_ping_enabled:
            threading.Thread(target=self.perform_self_ping, daemon=True).start()
    
    def load_data(self):
        """Загрузка данных"""
        try:
            if os.path.exists('leak_data.json'):
                with open('leak_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.leaks_by_user = defaultdict(list, {int(k): v for k, v in data.get('leaks', {}).items()})
                    self.user_info = {int(k): v for k, v in data.get('users', {}).items()}
        except Exception as e:
            logger.error(f"Ошибка загрузки данных: {e}")
    
    def save_data(self):
        """Сохранение данных"""
        try:
            data = {
                'leaks': dict(self.leaks_by_user),
                'users': self.user_info,
                'last_update': datetime.now().isoformat()
            }
            
            with open('leak_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных: {e}")
    
    def run(self):
        """Запуск бота и Flask приложения"""
        # Запуск Flask в отдельном потоке
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Запуск бота
        logger.info(f"🤖 Бот запущен на порту {PORT}")
        logger.info(f"🌐 URL: {RENDER_URL}")
        logger.info(f"🏓 Самопинг: {'Включен' if self.self_ping_enabled else 'Выключен'}")
        
        # Первый самопинг при запуске
        if self.self_ping_enabled:
            self.perform_self_ping()
        
        # Запуск бота в режиме polling (на Render лучше использовать webhooks, но для простоты polling)
        self.updater.start_polling()
        self.updater.idle()

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    try:
        bot = SelfPingBot()
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
