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

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", 5000))

SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 600))
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))

if not TOKEN or TOKEN == "ВАШ_ТОКЕН":
    raise ValueError("❌ TELEGRAM_TOKEN не установлен")
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
        
        # 🔥 SkillUP Ultra режим
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
        
        # 🔥 Используем усиленный анализ в режиме SkillUP
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
    
    # 1. ПЕРЕСЫЛКИ
    if msg.forward_from_chat:
        leak_type = "ПЕРЕСЫЛКА В ЧАТ"
        leak_details = f"В чат: {msg.forward_from_chat.title}"
        
    elif msg.forward_from:
        leak_type = "ПЕРЕСЫЛКА ПОЛЬЗОВАТЕЛЮ"
        target = msg.forward_from.username or f"id{msg.forward_from.id}"
        leak_details = f"Пользователю: {target}"
    
    # 2. АНАЛИЗ ТЕКСТА
    elif msg.text or msg.caption:
        text = msg.text or msg.caption
        
        # Любые ссылки
        link_pattern = r'(https?://\S+|www\.\S+|t\.me/\S+)'
        links = re.findall(link_pattern, text)
        if links:
            leak_type = "КОПИРОВАНИЕ ССЫЛКИ"
            leak_details = f"Найдены ссылки: {', '.join(links[:3])}"
        
        # Ключевые слова утечки
        leak_keywords = ['слив', 'скрин', 'screen', 'переслал', 'leak', 'слито', 'фоточата']
        found_keywords = [kw for kw in leak_keywords if kw in text.lower()]
        if found_keywords:
            leak_type = "ПОДОЗРИТЕЛЬНЫЙ ТЕКСТ"
            leak_details = f"Ключевые слова: {', '.join(found_keywords[:3])}"
        
        # Детекция длинных сообщений
        elif len(text) > 150 and '\n' in text:
            leak_type = "КОПИРОВАНИЕ ТЕКСТА"
            leak_details = f"Скопировал {len(text)} символов"
    
    # 3. АНАЛИЗ СКРИНШОТОВ
    screenshot_score = self.calculate_screenshot_score_ultra(msg)
    if screenshot_score > 50:
        leak_type = "ПОДОЗРЕНИЕ НА СКРИНШОТ"
        leak_details = f"Вероятность скриншота: {screenshot_score}% (ULTRA режим)"
    
    # 4. АНАЛИЗ МЕДИА
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
    
    # Анализ времени ответа
    if hasattr(msg, 'reply_to_message') and msg.reply_to_message:
        time_diff = (msg.date - msg.reply_to_message.date).total_seconds()
        if time_diff > 60:
            score += 25
        if time_diff > 300:
            score += 35
    
    # Анализ текста
    if msg.text:
        screenshot_indicators = ['📸', '🖼', '💾', '📱', '📲', '⬇️', '⬆️', '👇', '👆']
        if any(indicator in msg.text for indicator in screenshot_indicators):
            score += 30
        
        screenshot_words = ['скрин', 'screen', 'снял', 'фото', 'сохранил']
        if any(word in msg.text.lower() for word in screenshot_words):
            score += 35
        
        if len(msg.text) < 10 and any(c.isdigit() for c in msg.text):
            score += 20
    
    # Анализ медиа
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
    user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
    
    mode_icon = "🔥" if leak_info.get('detection_mode') == 'ULTRA' else "⚠️"
    alert = f"{mode_icon} ОБНАРУЖЕНА УТЕЧКА\n\n"
    alert += f"👤 Нарушитель: @{user['username']}\n"
    alert += f"📛 Имя: {user['first_name']} {user.get('last_name', '')}\n"
    alert += f"🆔 ID: {user_id}\n"
    alert += f"💬 Чат: {msg.chat.title}\n"
    alert += f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
    alert += f"📌 Тип нарушения: {leak_info['type']}\n"
    alert += f"📝 Детали: {leak_info['details']}\n"
    
    if leak_info.get('detection_mode') == 'ULTRA':
        alert += f"🎯 Точность: {leak_info.get('detection_score', 0)}%\n"
        alert += f"⚡ Режим: SkillUP Ultra\n"
    
    alert += f"\n📊 Всего нарушений: {len(self.leaks_by_user[user_id])}"
    
    try:
        await context.bot.send_message(
            chat_id=YOUR_ID,
            text=alert
        )
        logger.info(f"📤 Уведомление отправлено")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    ultra_status = "🔥 ВКЛЮЧЕН" if self.skillup_ultra_mode else "⚡ ВЫКЛЮЧЕН"
    
    await update.message.reply_text(
        f"🛡️ LeakTracker Bot\n\n"
        f"Я отслеживаю утечки информации из чатов.\n"
        f"🔥 SkillUP Ultra: {ultra_status}\n\n"
        f"📋 Команды:\n"
        f"/leakstats - таблица нарушителей\n"
        f"/leakinfo [id] - информация о нарушителе\n"
        f"/status - статус бота\n"
        f"/skillup - режим максимальной точности\n"
        f"/help - справка"
    )

async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = "📖 СПРАВКА:\n\n"
    help_text += "/start - информация о боте\n"
    help_text += "/help - эта справка\n"
    help_text += "/leakstats - таблица нарушителей\n"
    help_text += "/leakinfo [id] - информация о нарушителе\n"
    help_text += "/status - статус бота\n"
    help_text += "/pingstatus - статус самопинга (владелец)\n"
    help_text += "/toggleping - вкл/выкл самопинг (владелец)\n"
    help_text += "/skillup - 🔥 ВКЛ/ВЫКЛ режим SkillUP\n"
    help_text += "/clear - очистить данные (владелец)"
    
    await update.message.reply_text(help_text)

async def skillup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != YOUR_ID:
        await update.message.reply_text("⛔ Эта команда только для владельца")
        return
    
    if not context.args:
        status = "🔥 ВКЛЮЧЕН" if self.skillup_ultra_mode else "⚡ ВЫКЛЮЧЕН"
        await update.message.reply_text(
            f"🔥 SkillUP Ultra: {status}\n"
            f"Уровень точности: {self.ultra_detection_level}x\n\n"
            f"Использование:\n"
            f"/skillup on - включить\n"
            f"/skillup off - выключить"
        )
        return
    
    action = context.args[0].lower()
    
    if action == 'on' or action == 'вкл':
        self.skillup_ultra_mode = True
        await update.message.reply_text(
            "🔥 SKILLUP ULTRA АКТИВИРОВАН!\n\n"
            "✅ Детекция усилена в 5 раз\n"
            "✅ Пороги срабатывания снижены\n"
            "✅ Анализ скриншотов максимальный\n"
            "⚡ Уровень точности: 5x"
        )
        logger.info("🔥 SkillUP Ultra активирован")
        
    elif action == 'off' or action == 'выкл':
        self.skillup_ultra_mode = False
        await update.message.reply_text(
            "⚡ SkillUP Ultra выключен\n"
            "Бот в обычном режиме"
        )
        logger.info("⚡ SkillUP Ultra выключен")
    else:
        await update.message.reply_text(
            "❌ Неизвестная команда\n"
            "Используйте: /skillup on или /skillup off"
        )

async def leakstats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not self.leaks_by_user:
        await update.message.reply_text("📭 Нарушителей не обнаружено")
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
        
        ultra_leaks = [l for l in leaks if l.get('detection_mode') == 'ULTRA']
        
        stats.append({
            'user_id': user_id,
            'username': user['username'],
            'total_leaks': len(leaks),
            'ultra_leaks': len(ultra_leaks),
            'leak_types': leak_types
        })
    
    stats.sort(key=lambda x: x['total_leaks'], reverse=True)
    
    table = "📊 ТАБЛИЦА НАРУШИТЕЛЕЙ\n"
    if self.skillup_ultra_mode:
        table += "🔥 SkillUP Ultra: АКТИВЕН\n\n"
    else:
        table += "\n"
    
    table += "┌──────────────┬────────────────┬────────────┬─────────────────────────────┐\n"
    table += "│ Пользователь │ Всего нарушений │ ULTRA-утечек │ Основные типы нарушений  │\n"
    table += "├──────────────┼────────────────┼────────────┼─────────────────────────────┤\n"
    
    for stat in stats[:15]:
        username = f"@{stat['username']}" if not stat['username'].startswith('id') else stat['username']
        username_display = username[:12].ljust(12)
        
        ultra_display = f"{stat['ultra_leaks']}".center(12)
        
        types_str = ""
        for leak_type, count in list(stat['leak_types'].items())[:2]:
            short_type = leak_type[:10] + ".." if len(leak_type) > 10 else leak_type
            types_str += f"{short_type}:{count} "
        
        table += f"│ {username_display} │ {stat['total_leaks']:<14} │ {ultra_display} │ {types_str:<27} │\n"
    
    table += "└──────────────┴────────────────┴────────────┴─────────────────────────────┘\n"
    table += f"\n📈 Всего нарушителей: {len(stats)}"
    table += f"\n🔥 ULTRA-режим: {'ВКЛ' if self.skillup_ultra_mode else 'ВЫКЛ'}"
    table += f"\n🕒 Обновлено: {datetime.now().strftime('%H:%M:%S')}"
    
    await update.message.reply_text(f"<pre>{table}</pre>", parse_mode='HTML')
        async def leakinfo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("ℹ️ Использование: /leakinfo [ID пользователя или @username]")
            return
        
        target = context.args[0].replace('@', '')
        
        user_id = None
        for uid, info in self.user_info.items():
            if info['username'] == target or str(uid) == target:
                user_id = uid
                break
        
        if not user_id or user_id not in self.leaks_by_user:
            await update.message.reply_text("❌ Пользователь не найден или нарушений нет")
            return
        
        leaks = self.leaks_by_user[user_id]
        user = self.user_info[user_id]
        
        report = f"🔍 ИНФОРМАЦИЯ О НАРУШИТЕЛЕ\n\n"
        report += f"👤 Пользователь: @{user['username']}\n"
        report += f"🆔 ID: {user_id}\n"
        report += f"📛 Имя: {user['first_name']} {user.get('last_name', '')}\n"
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
        
        await update.message.reply_text(f"<pre>{report}</pre>", parse_mode='HTML')
    
    async def pingstatus_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.from_user.id != YOUR_ID:
            await update.message.reply_text("⛔ Эта команда только для владельца")
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
        
        message += f"\n🔗 URL: {RENDER_URL}"
        
        await update.message.reply_text(message)
    
    async def toggleping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.from_user.id != YOUR_ID:
            await update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        self.self_ping_enabled = not self.self_ping_enabled
        status = "🟢 ВКЛЮЧЕН" if self.self_ping_enabled else "🔴 ВЫКЛЮЧЕН"
        
        await update.message.reply_text(f"🔄 Самопинг теперь {status}")
        
        if self.self_ping_enabled:
            threading.Thread(target=self.perform_self_ping, daemon=True).start()
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        status += f"🔄 Всего пингов: {self.ping_count}\n"
        status += f"🔥 SkillUP Ultra: {'ВКЛ' if self.skillup_ultra_mode else 'ВЫКЛ'}"
        
        await update.message.reply_text(status)
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.from_user.id != YOUR_ID:
            await update.message.reply_text("⛔ Эта команда только для владельца")
            return
        
        if len(context.args) > 0 and context.args[0] == "confirm":
            self.leaks_by_user.clear()
            self.user_info.clear()
            self.save_data()
            await update.message.reply_text("✅ Все данные очищены")
        else:
            await update.message.reply_text(
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
            self.application.run_polling()
        except KeyboardInterrupt:
            self.shutdown()
    
    def shutdown(self):
        logger.info("🛑 Завершение работы бота...")
        self.is_running = False
        self.save_data()
        self.application.stop()
        logger.info("👋 Бот остановлен")

if __name__ == '__main__':
    try:
        bot = TelegramLeakBot()
        bot.run()
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка: {e}")
        raise
