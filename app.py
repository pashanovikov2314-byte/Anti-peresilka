import os
import json
import time
import re
import asyncio
import hashlib
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import requests
import logging
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()] or ALLOWED_IDS
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ТЕЛЕГРАМ API ==========
class TelegramMonitor:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        
    def send_message(self, chat_id, text, parse_mode="HTML"):
        """Отправить сообщение в Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"Send message error: {e}")
            return {"ok": False}
    
    def get_chat_member(self, chat_id, user_id):
        """Получить информацию об участнике чата"""
        try:
            url = f"{self.base_url}/getChatMember"
            data = {"chat_id": chat_id, "user_id": user_id}
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"Get chat member error: {e}")
            return {"ok": False}
    
    def get_chat(self, chat_id):
        """Получить информацию о чате"""
        try:
            url = f"{self.base_url}/getChat"
            data = {"chat_id": chat_id}
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"Get chat error: {e}")
            return {"ok": False}

# ========== БАЗА ДАННЫХ МОНИТОРИНГА ==========
class ScreenshotMonitorDB:
    def __init__(self):
        self.conn = sqlite3.connect('screenshot_monitor.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_tables()
    
    def init_tables(self):
        """Инициализация таблиц базы данных"""
        # Таблица для отслеживания скриншотов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                message_id INTEGER,
                screenshot_type TEXT,
                detected_at TIMESTAMP,
                message_text TEXT,
                forwarded_from TEXT
            )
        ''')
        
        # Таблица для пересланных сообщений
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_chat_id INTEGER,
                original_message_id INTEGER,
                forwarded_chat_id INTEGER,
                forwarded_message_id INTEGER,
                user_id INTEGER,
                username TEXT,
                forwarded_at TIMESTAMP,
                message_content TEXT,
                is_to_pm INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица для копирования сообщений
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS copied_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                message_id INTEGER,
                copied_text TEXT,
                copied_at TIMESTAMP,
                detection_method TEXT
            )
        ''')
        
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_bot INTEGER DEFAULT 0,
                first_seen TIMESTAMP,
                last_activity TIMESTAMP,
                total_screenshots INTEGER DEFAULT 0,
                total_forwards INTEGER DEFAULT 0,
                total_copies INTEGER DEFAULT 0,
                suspicious_score INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица чатов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                type TEXT,
                added_to_monitoring TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        self.conn.commit()
    
    def add_screenshot_event(self, chat_id, user_id, username, first_name, message_id, screenshot_type, message_text, forwarded_from=None):
        """Добавить запись о скриншоте"""
        self.cursor.execute('''
            INSERT INTO screenshots 
            (chat_id, user_id, username, first_name, message_id, screenshot_type, detected_at, message_text, forwarded_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, username, first_name, message_id, screenshot_type, datetime.now(), message_text, forwarded_from))
        
        # Обновить статистику пользователя
        self.cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, first_seen, last_activity)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, datetime.now(), datetime.now()))
        
        self.cursor.execute('''
            UPDATE users 
            SET total_screenshots = total_screenshots + 1,
                last_activity = ?,
                suspicious_score = suspicious_score + 5
            WHERE user_id = ?
        ''', (datetime.now(), user_id))
        
        self.conn.commit()
        return self.cursor.lastrowid
    
    def add_forward_event(self, original_chat_id, original_message_id, forwarded_chat_id, forwarded_message_id, user_id, username, message_content, is_to_pm=False):
        """Добавить запись о пересылке"""
        self.cursor.execute('''
            INSERT INTO forwarded_messages 
            (original_chat_id, original_message_id, forwarded_chat_id, forwarded_message_id, user_id, username, forwarded_at, message_content, is_to_pm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (original_chat_id, original_message_id, forwarded_chat_id, forwarded_message_id, user_id, username, datetime.now(), message_content, 1 if is_to_pm else 0))
        
        # Обновить статистику пользователя
        self.cursor.execute('''
            UPDATE users 
            SET total_forwards = total_forwards + 1,
                last_activity = ?,
                suspicious_score = suspicious_score + (10 if ? = 1 else 3)
            WHERE user_id = ?
        ''', (datetime.now(), 1 if is_to_pm else 0, user_id))
        
        self.conn.commit()
        return self.cursor.lastrowid
    
    def add_copy_event(self, chat_id, user_id, username, message_id, copied_text, detection_method):
        """Добавить запись о копировании"""
        self.cursor.execute('''
            INSERT INTO copied_messages 
            (chat_id, user_id, username, message_id, copied_text, copied_at, detection_method)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, username, message_id, copied_text, datetime.now(), detection_method))
        
        # Обновить статистику пользователя
        self.cursor.execute('''
            UPDATE users 
            SET total_copies = total_copies + 1,
                last_activity = ?,
                suspicious_score = suspicious_score + 2
            WHERE user_id = ?
        ''', (datetime.now(), user_id))
        
        self.conn.commit()
        return self.cursor.lastrowid
    
    def add_chat(self, chat_id, title, username, chat_type):
        """Добавить чат в мониторинг"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO chats (chat_id, title, username, type, added_to_monitoring)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, title, username or "", chat_type, datetime.now()))
        self.conn.commit()
    
    def get_user_stats(self, user_id):
        """Получить статистику пользователя"""
        self.cursor.execute('''
            SELECT * FROM users WHERE user_id = ?
        ''', (user_id,))
        return self.cursor.fetchone()
    
    def get_recent_screenshots(self, limit=50):
        """Получить последние скриншоты"""
        self.cursor.execute('''
            SELECT * FROM screenshots 
            ORDER BY detected_at DESC 
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()
    
    def get_recent_forwards(self, limit=50):
        """Получить последние пересылки"""
        self.cursor.execute('''
            SELECT * FROM forwarded_messages 
            ORDER BY forwarded_at DESC 
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()
    
    def get_suspicious_users(self, limit=20):
        """Получить подозрительных пользователей"""
        self.cursor.execute('''
            SELECT * FROM users 
            WHERE suspicious_score > 0 
            ORDER BY suspicious_score DESC 
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()

# ========== ОСНОВНОЙ КЛАСС МОНИТОРИНГА ==========
class ScreenshotMonitor:
    def __init__(self, token, allowed_ids):
        self.tg = TelegramMonitor(token)
        self.db = ScreenshotMonitorDB()
        self.allowed_ids = allowed_ids
        self.monitored_chats = set()
        self.screenshot_patterns = [
            "обнаружен снимок экрана",
            "screenshot detected",
            "скриншот обнаружен",
            "снимок экрана",
            "made a screenshot"
        ]
        
        # Загружаем чаты из БД
        self.load_monitored_chats()
    
    def load_monitored_chats(self):
        """Загрузить чаты из базы данных"""
        self.db.cursor.execute('SELECT chat_id FROM chats WHERE is_active = 1')
        for row in self.db.cursor.fetchall():
            self.monitored_chats.add(row[0])
    
    def detect_screenshot(self, message_text):
        """Обнаружить упоминание скриншота в сообщении"""
        if not message_text:
            return False, None
        
        message_lower = message_text.lower()
        for pattern in self.screenshot_patterns:
            if pattern in message_lower:
                return True, pattern
        
        return False, None
    
    def analyze_message(self, message_data):
        """Анализировать сообщение на подозрительные действия"""
        results = {
            'is_screenshot': False,
            'is_forward': False,
            'is_copy': False,
            'is_to_pm': False,
            'details': {}
        }
        
        # Проверка на пересылку
        if 'forward_from_chat' in message_data or 'forward_from' in message_data:
            results['is_forward'] = True
            results['details']['forward_type'] = 'cross_chat' if 'forward_from_chat' in message_data else 'user'
            
            # Проверка, переслано ли в ЛС
            chat = message_data.get('chat', {})
            if chat.get('type') == 'private':
                results['is_to_pm'] = True
        
        # Проверка текста на скриншоты
        text = message_data.get('text', '') or message_data.get('caption', '')
        is_screenshot, pattern = self.detect_screenshot(text)
        if is_screenshot:
            results['is_screenshot'] = True
            results['details']['screenshot_pattern'] = pattern
        
        return results
    
    def process_webhook(self, update):
        """Обработать вебхук от Telegram"""
        try:
            # Обработка сообщений
            if 'message' in update:
                message = update['message']
                chat_id = message.get('chat', {}).get('id')
                user_id = message.get('from', {}).get('id')
                username = message.get('from', {}).get('username', '')
                first_name = message.get('from', {}).get('first_name', '')
                message_id = message.get('message_id')
                text = message.get('text', '') or message.get('caption', '')
                
                # Анализ сообщения
                analysis = self.analyze_message(message)
                
                # Если это уведомление о скриншоте
                if analysis['is_screenshot']:
                    logger.info(f"Обнаружен скриншот от пользователя {user_id} в чате {chat_id}")
                    
                    # Определяем, кто сделал скриншот
                    screenshot_user = self.extract_screenshot_user(text, user_id)
                    
                    # Сохраняем в БД
                    screenshot_id = self.db.add_screenshot_event(
                        chat_id=chat_id,
                        user_id=screenshot_user['user_id'],
                        username=screenshot_user['username'],
                        first_name=screenshot_user['first_name'],
                        message_id=message_id,
                        screenshot_type=analysis['details']['screenshot_pattern'],
                        message_text=text[:500],
                        forwarded_from=screenshot_user.get('original_user')
                    )
                    
                    # Отправляем оповещение админам
                    if screenshot_id:
                        self.send_screenshot_alert(screenshot_user, chat_id, message_id, text)
                
                # Если это пересылка
                elif analysis['is_forward']:
                    logger.info(f"Обнаружена пересылка от пользователя {user_id}")
                    
                    forward_data = self.extract_forward_info(message)
                    
                    # Сохраняем в БД
                    forward_id = self.db.add_forward_event(
                        original_chat_id=forward_data['original_chat_id'],
                        original_message_id=forward_data['original_message_id'],
                        forwarded_chat_id=chat_id,
                        forwarded_message_id=message_id,
                        user_id=user_id,
                        username=username,
                        message_content=forward_data['message_content'],
                        is_to_pm=analysis['is_to_pm']
                    )
                    
                    # Отправляем оповещение админам
                    if forward_id:
                        self.send_forward_alert(user_id, username, forward_data, analysis['is_to_pm'])
                
                # Если чат не в мониторинге, добавляем его
                if chat_id not in self.monitored_chats:
                    self.add_chat_to_monitoring(chat_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return False
    
    def extract_screenshot_user(self, text, sender_id):
        """Извлечь информацию о пользователе, сделавшем скриншот"""
        # Пытаемся извлечь из текста уведомления
        user_info = {
            'user_id': sender_id,
            'username': '',
            'first_name': '',
            'original_user': None
        }
        
        # Паттерны для извлечения username
        patterns = [
            r'пользователь\s+@(\w+)',
            r'user\s+@(\w+)',
            r'@(\w+)\s+сделал',
            r'@(\w+)\s+made'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                user_info['username'] = match.group(1)
                break
        
        return user_info
    
    def extract_forward_info(self, message):
        """Извлечь информацию о пересылке"""
        forward_info = {
            'original_chat_id': None,
            'original_message_id': None,
            'message_content': ''
        }
        
        # Получаем оригинальное сообщение
        if 'forward_from_chat' in message:
            forward_info['original_chat_id'] = message['forward_from_chat'].get('id')
            forward_info['original_message_id'] = message.get('forward_from_message_id')
        
        # Получаем контент сообщения
        text = message.get('text', '') or message.get('caption', '')
        forward_info['message_content'] = text[:200] + ('...' if len(text) > 200 else '')
        
        return forward_info
    
    def add_chat_to_monitoring(self, chat_id):
        """Добавить чат в мониторинг"""
        try:
            chat_info = self.tg.get_chat(chat_id)
            if chat_info.get('ok'):
                chat_data = chat_info['result']
                self.db.add_chat(
                    chat_id=chat_id,
                    title=chat_data.get('title', f'Chat {chat_id}'),
                    username=chat_data.get('username'),
                    chat_type=chat_data.get('type', 'unknown')
                )
                self.monitored_chats.add(chat_id)
                logger.info(f"Добавлен чат в мониторинг: {chat_data.get('title', chat_id)}")
        except Exception as e:
            logger.error(f"Error adding chat to monitoring: {e}")
    
    def send_screenshot_alert(self, user_info, chat_id, message_id, screenshot_text):
        """Отправить оповещение о скриншоте"""
        alert_message = f"""
🚨 <b>ОБНАРУЖЕН СКРИНШОТ</b>

<b>Пользователь:</b> @{user_info['username'] or 'Неизвестно'}
<b>ID пользователя:</b> {user_info['user_id']}
<b>Чат ID:</b> {chat_id}
<b>Сообщение ID:</b> {message_id}
<b>Время обнаружения:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<b>Текст уведомления:</b>
{screenshot_text[:300]}{'...' if len(screenshot_text) > 300 else ''}

<i>Система автоматического мониторинга</i>
"""
        
        for admin_id in self.allowed_ids:
            self.tg.send_message(admin_id, alert_message)
    
    def send_forward_alert(self, user_id, username, forward_data, is_to_pm):
        """Отправить оповещение о пересылке"""
        destination = "личные сообщения" if is_to_pm else "другой чат"
        
        alert_message = f"""
⚠️ <b>ОБНАРУЖЕНА ПЕРЕСЫЛКА</b>

<b>Пользователь:</b> @{username or 'Неизвестно'}
<b>ID пользователя:</b> {user_id}
<b>Направление:</b> {destination}
<b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<b>Переслано из чата:</b> {forward_data['original_chat_id']}
<b>Сообщение ID:</b> {forward_data['original_message_id']}

<b>Содержимое:</b>
{forward_data['message_content']}

<i>Система автоматического мониторинга</i>
"""
        
        for admin_id in self.allowed_ids:
            self.tg.send_message(admin_id, alert_message)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
monitor = ScreenshotMonitor(TELEGRAM_TOKEN, ALLOWED_IDS)
app = Flask(__name__)

# ========== WEBHOOK ENDPOINT ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной вебхук для Telegram"""
    try:
        update = request.json
        monitor.process_webhook(update)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ========== СТАТИСТИКА ДЛЯ ВЕБ-ИНТЕРФЕЙСА ==========
@app.route('/')
def index():
    """Главная страница веб-интерфейса"""
    return render_template('index.html')

@app.route('/api/stats')
def api_stats():
    """API для получения статистики"""
    stats = {
        'total_screenshots': len(monitor.db.get_recent_screenshots(1000)),
        'total_forwards': len(monitor.db.get_recent_forwards(1000)),
        'monitored_chats': len(monitor.monitored_chats),
        'suspicious_users': len(monitor.db.get_suspicious_users()),
        'last_update': datetime.now().isoformat()
    }
    return jsonify(stats)

@app.route('/api/recent_screenshots')
def api_recent_screenshots():
    """API для получения последних скриншотов"""
    screenshots = monitor.db.get_recent_screenshots(50)
    result = []
    
    for s in screenshots:
        result.append({
            'id': s[0],
            'chat_id': s[1],
            'user_id': s[2],
            'username': s[3],
            'first_name': s[4],
            'message_id': s[5],
            'screenshot_type': s[6],
            'detected_at': s[7],
            'message_text': s[8],
            'forwarded_from': s[9]
        })
    
    return jsonify({'screenshots': result})

@app.route('/api/recent_forwards')
def api_recent_forwards():
    """API для получения последних пересылок"""
    forwards = monitor.db.get_recent_forwards(50)
    result = []
    
    for f in forwards:
        result.append({
            'id': f[0],
            'original_chat_id': f[1],
            'original_message_id': f[2],
            'forwarded_chat_id': f[3],
            'forwarded_message_id': f[4],
            'user_id': f[5],
            'username': f[6],
            'forwarded_at': f[7],
            'message_content': f[8],
            'is_to_pm': bool(f[9])
        })
    
    return jsonify({'forwards': result})

# ========== НАСТРОЙКА WEBHOOK ==========
@app.route('/setup')
def setup_webhook():
    """Настроить вебхук"""
    try:
        webhook_url = os.environ.get("WEBHOOK_URL", f"https://{request.host}/webhook")
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {
            "url": webhook_url,
            "max_connections": 100,
            "allowed_updates": ["message", "edited_message"]
        }
        
        response = requests.post(url, json=data)
        result = response.json()
        
        return jsonify({
            "success": result.get("ok", False),
            "webhook_url": webhook_url,
            "message": "Webhook configured successfully"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== ЗАПУСК СЕРВЕРА ==========
if __name__ == "__main__":
    logger.info(f"🚀 Запуск Screenshot Monitor v2.0")
    logger.info(f"✅ Разрешённые пользователи: {len(ALLOWED_IDS)}")
    logger.info(f"✅ Мониторинг чатов: {len(monitor.monitored_chats)}")
    logger.info(f"🌐 Webhook порт: {PORT}")
    
    app.run(host="0.0.0.0", port=PORT, debug=False)