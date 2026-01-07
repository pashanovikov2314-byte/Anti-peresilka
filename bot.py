import logging
import re
import time
import threading
import requests
import hashlib
import pickle
import base64
import secrets
import math
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
PORT = int(os.environ.get("PORT", 5000))

# Уровень безопасности
SECURITY_LEVEL = int(os.environ.get("SECURITY_LEVEL", 7))

if not TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не установлен")
if not ALLOWED_USER_IDS:
    raise ValueError("❌ ALLOWED_IDS не установлен")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== СИСТЕМА АНАЛИЗА ==========
class MessageAnalyzer:
    """Анализатор сообщений на пересылки и скриншоты"""
    
    def __init__(self, security_level=7):
        self.security_level = security_level
        self.user_stats = defaultdict(lambda: {'forwarded': 0, 'copied': 0, 'warnings': 0})
        
    def check_message(self, update: Update) -> dict:
        """Проверка сообщения на нарушения"""
        result = {
            'violations': [],
            'risk_level': 'LOW',
            'action': 'ALLOW'
        }
        
        message = update.message
        user_id = message.from_user.id
        
        # Проверка на пересланное сообщение
        if message.forward_date:
            result['violations'].append('FORWARDED_MESSAGE')
            self.user_stats[user_id]['forwarded'] += 1
            logger.info(f"⚠️ Обнаружено пересланное сообщение от {user_id}")
        
        # Проверка на копирование текста (если есть reply_to_message с таким же текстом)
        if message.reply_to_message:
            original_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            current_text = message.text or message.caption or ""
            
            if original_text and current_text and self.is_text_copied(original_text, current_text):
                result['violations'].append('COPIED_TEXT')
                self.user_stats[user_id]['copied'] += 1
                logger.info(f"⚠️ Обнаружено копирование текста от {user_id}")
        
        # Проверка на угрозу скриншота
        if self.check_screenshot_threat(message.text or message.caption or ""):
            result['violations'].append('SCREENSHOT_THREAT')
            logger.info(f"⚠️ Обнаружена угроза скриншота от {user_id}")
        
        # Определение уровня риска
        if len(result['violations']) > 0:
            result['risk_level'] = 'HIGH'
            
            # Если много нарушений - блокировка
            total_violations = self.user_stats[user_id]['forwarded'] + self.user_stats[user_id]['copied']
            if total_violations >= 3:
                result['action'] = 'DELETE'
            elif total_violations >= 2:
                result['action'] = 'WARN'
            else:
                result['action'] = 'NOTIFY'
        
        return result
    
    def is_text_copied(self, original: str, current: str, threshold: float = 0.8) -> bool:
        """Проверка, является ли текст копией"""
        if not original or not current:
            return False
        
        # Приводим к нижнему регистру и удаляем пробелы
        orig_clean = original.lower().strip()
        curr_clean = current.lower().strip()
        
        # Если тексты идентичны
        if orig_clean == curr_clean:
            return True
        
        # Проверка на частичное копирование
        if len(orig_clean) > 20 and len(curr_clean) > 20:
            # Ищем общие подстроки
            common_words = set(orig_clean.split()) & set(curr_clean.split())
            similarity = len(common_words) / max(len(set(orig_clean.split())), 1)
            
            return similarity >= threshold
        
        return False
    
    def check_screenshot_threat(self, text: str) -> bool:
        """Проверка текста на упоминание скриншотов"""
        if not text:
            return False
        
        text_lower = text.lower()
        screenshot_keywords = [
            'скриншот', 'screenshot', 'снял скрин', 'заскринил',
            'сохранил', 'переслал', 'копия экрана', 'фото экрана'
        ]
        
        threat_phrases = [
            'сохранил себе', 'у меня есть скрин', 'я сохранил',
            'сделал скрин', 'заскринил это', 'уже скопировал'
        ]
        
        for keyword in screenshot_keywords:
            if keyword in text_lower:
                # Проверяем контекст
                for phrase in threat_phrases:
                    if phrase in text_lower:
                        return True
        
        return False
    
    def get_user_stats(self, user_id: int) -> dict:
        """Получить статистику пользователя"""
        return dict(self.user_stats.get(user_id, {'forwarded': 0, 'copied': 0, 'warnings': 0}))

# ========== TELEGRAM БОТ ==========
class LeakTrackerBot:
    """Основной класс бота"""
    
    def __init__(self, token: str):
        self.token = token
        self.analyzer = MessageAnalyzer(SECURITY_LEVEL)
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
        
    def setup_handlers(self):
        """Настройка обработчиков"""
        # Команды
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("my_stats", self.my_stats_command))
        
        # Обработка всех сообщений
        self.app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self.handle_message))
        
        # Обработка ошибок
        self.app.add_error_handler(self.error_handler)
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = user.id
        
        # Проверка доступа
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        welcome_text = f"""
👋 Привет, {user.first_name}!

🤖 Я — бот для отслеживания пересылок, копирования и угроз скриншотов.

📊 **Функции:**
• Отслеживание пересланных сообщений
• Обнаружение копирования текста
• Выявление угроз скриншотов
• Статистика нарушений

🛡️ **Уровень безопасности:** {SECURITY_LEVEL}/10

📝 **Доступные команды:**
/start - Запуск бота
/help - Помощь
/stats - Общая статистика
/my_stats - Моя статистика

⚠️ Бот автоматически проверяет все сообщения.
        """
        
        await update.message.reply_text(welcome_text)
        logger.info(f"🟢 Пользователь {user_id} запустил бота")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_text = """
📖 **Помощь по использованию бота:**

🤖 **Как работает бот:**
1. Автоматически проверяет все сообщения в чате
2. Обнаруживает пересланные сообщения
3. Находит копирование текста
4. Выявляет угрозы скриншотов

⚠️ **Нарушения:**
• Пересланные сообщения - если дата пересылки не скрыта
• Копирование текста - если текст совпадает с ответом на сообщение
• Угроза скриншота - если в тексте есть упоминание о сохранении/скриншоте

📊 **Статистика:**
• /stats - общая статистика (только для админов)
• /my_stats - ваша личная статистика

🔧 **Настройки:**
Уровень безопасности настраивается через переменные окружения.

🛡️ Бот работает автоматически, вмешательство не требуется.
        """
        
        await update.message.reply_text(help_text)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats (только для админов)"""
        user_id = update.effective_user.id
        
        if user_id != YOUR_ID and user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("❌ Эта команда только для администраторов.")
            return
        
        # Получаем общую статистику
        total_users = len(self.analyzer.user_stats)
        total_forwarded = sum(stats['forwarded'] for stats in self.analyzer.user_stats.values())
        total_copied = sum(stats['copied'] for stats in self.analyzer.user_stats.values())
        
        stats_text = f"""
📊 **Общая статистика системы:**

👥 **Пользователей:** {total_users}
📨 **Переслано сообщений:** {total_forwarded}
📋 **Скопировано текстов:** {total_copied}
🛡️ **Уровень безопасности:** {SECURITY_LEVEL}/10

📈 **Активные пользователи:**
"""
        
        # Добавляем статистику по пользователям
        for uid, stats in list(self.analyzer.user_stats.items())[:10]:  # Ограничиваем 10 пользователями
            total_violations = stats['forwarded'] + stats['copied']
            if total_violations > 0:
                stats_text += f"• ID {uid}: {total_violations} нарушений\n"
        
        await update.message.reply_text(stats_text)
    
    async def my_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /my_stats"""
        user_id = update.effective_user.id
        stats = self.analyzer.get_user_stats(user_id)
        
        stats_text = f"""
📊 **Ваша статистика:**

👤 **Ваш ID:** {user_id}
📨 **Переслано сообщений:** {stats['forwarded']}
📋 **Скопировано текстов:** {stats['copied']}
⚠️ **Предупреждений:** {stats['warnings']}

📝 **Рекомендации:**
• Избегайте пересылки сообщений
• Не копируйте текст других пользователей
• Не упоминайте о скриншотах

🛡️ Ваш рейтинг безопасности: {'Высокий' if stats['forwarded'] + stats['copied'] == 0 else 'Средний' if stats['forwarded'] + stats['copied'] < 3 else 'Низкий'}
        """
        
        await update.message.reply_text(stats_text)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка всех сообщений"""
        user_id = update.effective_user.id
        message = update.message
        
        # Пропускаем команды
        if message.text and message.text.startswith('/'):
            return
        
        # Проверяем доступ
        if user_id not in ALLOWED_USER_IDS:
            await message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        # Анализируем сообщение
        analysis = self.analyzer.check_message(update)
        
        # Если есть нарушения
        if analysis['violations']:
            violations_text = ", ".join(analysis['violations'])
            risk_text = analysis['risk_level']
            
            # Формируем предупреждение
            warning_text = f"""
⚠️ **Обнаружено нарушение!**

📋 **Тип нарушения:** {violations_text}
🎯 **Уровень риска:** {risk_text}
👤 **Пользователь:** @{update.effective_user.username or update.effective_user.id}
            """
            
            # Отправляем предупреждение
            await message.reply_text(warning_text)
            
            # Если нужно удалить сообщение
            if analysis['action'] == 'DELETE':
                try:
                    await message.delete()
                    await message.reply_text("🗑️ Сообщение удалено из-за множественных нарушений.")
                except Exception as e:
                    logger.error(f"Ошибка удаления сообщения: {e}")
            
            # Логируем
            logger.warning(f"Нарушение от {user_id}: {violations_text}")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Ошибка: {context.error}")
        
        if update and hasattr(update, 'message'):
            try:
                await update.message.reply_text("❌ Произошла ошибка. Пожалуйста, попробуйте позже.")
            except:
                pass
    
    def run(self):
        """Запуск бота"""
        logger.info("🚀 Запуск Telegram бота...")
        logger.info(f"🔐 Уровень безопасности: {SECURITY_LEVEL}")
        logger.info(f"👥 Разрешено пользователей: {len(ALLOWED_USER_IDS)}")
        
        # Запуск бота
        self.app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

# ========== FLASK APP (для веб-интерфейса) ==========
app = Flask(__name__)
bot = None

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>LeakTracker Bot</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }
            .status { padding: 10px; background: #4CAF50; color: white; border-radius: 5px; display: inline-block; margin: 10px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 LeakTracker Telegram Bot</h1>
            <div class="status">🟢 BOT IS RUNNING</div>
            <p>Система мониторинга пересылок, копирования и угроз скриншотов</p>
            <p>Бот работает в фоновом режиме и проверяет все сообщения</p>
        </div>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

# ========== ЗАПУСК ==========
def main():
    """Основная функция запуска"""
    global bot
    
    # Создаем и запускаем бота
    bot = LeakTrackerBot(TOKEN)
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=bot.run, daemon=True)
    bot_thread.start()
    
    logger.info("🤖 Telegram бот запущен в фоновом режиме")
    
    # Запускаем Flask сервер
    logger.info(f"🌐 Веб-сервер запускается на порту {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
