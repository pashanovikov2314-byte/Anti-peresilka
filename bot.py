#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SILENT TELEGRAM STATS BOT - Тихий сбор статистики
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading
import datetime
import re
from typing import Dict, List, Optional, Set, Any
from collections import defaultdict
from dataclasses import dataclass, field, asdict

# Импорты
try:
    import aiohttp
    from aiohttp import ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("ERROR: Install aiohttp: pip install aiohttp")
    sys.exit(1)

try:
    from flask import Flask, jsonify, render_template_string
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("ERROR: Install Flask: pip install Flask")

# ========== КОНФИГУРАЦИЯ ==========
class Config:
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    ALLOWED_USER_IDS = [int(x) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x]
    DATA_FILE = "telegram_stats.json"
    LOG_LEVEL = "INFO"
    
    # Настройки
    UPDATE_TIMEOUT = 30
    DETECT_FORWARDS = True
    DETECT_COPIES = True
    DETECT_SCREENSHOTS = True
    
    # Веб
    WEB_PORT = int(os.environ.get("PORT", "5000"))
    WEB_HOST = "0.0.0.0"
    
    @classmethod
    def validate(cls):
        if not cls.TELEGRAM_TOKEN:
            print("ERROR: TELEGRAM_TOKEN not set")
            return False
        if not cls.ALLOWED_USER_IDS:
            print("ERROR: ALLOWED_IDS not set")
            return False
        return True

# ========== ДАННЫЕ ==========
@dataclass
class MessageData:
    message_id: int
    user_id: int
    chat_id: int
    timestamp: str
    text: str = ""
    is_forwarded: bool = False
    is_copy: bool = False
    screenshot_risk: int = 0
    has_media: bool = False

@dataclass
class UserStats:
    user_id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    messages_count: int = 0
    forwarded_count: int = 0
    copied_count: int = 0
    first_seen: str = ""
    last_seen: str = ""

@dataclass
class ChatStats:
    chat_id: int
    title: str = ""
    messages_count: int = 0
    users_count: int = 0

# ========== АНАЛИЗАТОР ==========
class MessageAnalyzer:
    def __init__(self):
        self.screenshot_words = ['скрин', 'screenshot', 'снимок', 'сохранил', 'покажу']
        self.copy_words = ['скопировал', 'копирую', 'copy', 'взял текст']
    
    def analyze(self, message: Dict) -> MessageData:
        msg = MessageData(
            message_id=message.get('message_id', 0),
            user_id=message.get('from', {}).get('id', 0),
            chat_id=message.get('chat', {}).get('id', 0),
            timestamp=datetime.datetime.now().isoformat()
        )
        
        # Текст
        text = message.get('text') or message.get('caption') or ""
        msg.text = text[:500]  # Ограничиваем длину
        
        # Пересылка
        if 'forward_date' in message and Config.DETECT_FORWARDS:
            msg.is_forwarded = True
        
        # Медиа
        msg.has_media = any(k in message for k in ['photo', 'video', 'document', 'audio'])
        
        # Анализ текста
        if text:
            text_lower = text.lower()
            
            # Копирование
            if Config.DETECT_COPIES:
                for word in self.copy_words:
                    if word in text_lower:
                        msg.is_copy = True
                        break
            
            # Скриншоты
            if Config.DETECT_SCREENSHOTS:
                for word in self.screenshot_words:
                    if word in text_lower:
                        msg.screenshot_risk += 20
                msg.screenshot_risk = min(100, msg.screenshot_risk)
        
        return msg

# ========== ХРАНИЛИЩЕ ==========
class DataStorage:
    def __init__(self):
        self.messages: List[MessageData] = []
        self.users: Dict[int, UserStats] = {}
        self.chats: Dict[int, ChatStats] = {}
        self.analyzer = MessageAnalyzer()
        self.load()
    
    def add_message(self, message: Dict) -> bool:
        try:
            user_id = message.get('from', {}).get('id', 0)
            if user_id not in Config.ALLOWED_USER_IDS:
                return False
            
            msg_data = self.analyzer.analyze(message)
            self.messages.append(msg_data)
            
            # Обновить пользователя
            self._update_user(msg_data, message.get('from', {}))
            
            # Обновить чат
            self._update_chat(msg_data, message.get('chat', {}))
            
            # Автосохранение
            if len(self.messages) % 50 == 0:
                self.save()
            
            return True
            
        except Exception:
            return False
    
    def _update_user(self, msg: MessageData, user_info: Dict):
        user_id = msg.user_id
        
        if user_id not in self.users:
            self.users[user_id] = UserStats(
                user_id=user_id,
                username=user_info.get('username', ''),
                first_name=user_info.get('first_name', ''),
                last_name=user_info.get('last_name', ''),
                first_seen=msg.timestamp
            )
        
        user = self.users[user_id]
        user.messages_count += 1
        
        if msg.is_forwarded:
            user.forwarded_count += 1
        
        if msg.is_copy:
            user.copied_count += 1
        
        user.last_seen = msg.timestamp
    
    def _update_chat(self, msg: MessageData, chat_info: Dict):
        chat_id = msg.chat_id
        
        if chat_id not in self.chats:
            self.chats[chat_id] = ChatStats(
                chat_id=chat_id,
                title=chat_info.get('title', f'Chat {chat_id}')
            )
        
        chat = self.chats[chat_id]
        chat.messages_count += 1
        
        # Обновить количество пользователей
        user_ids = {m.user_id for m in self.messages if m.chat_id == chat_id}
        chat.users_count = len(user_ids)
    
    # API методы
    def get_overall_stats(self) -> Dict:
        total = len(self.messages)
        forwarded = sum(1 for m in self.messages if m.is_forwarded)
        copied = sum(1 for m in self.messages if m.is_copy)
        
        return {
            "total_messages": total,
            "total_users": len(self.users),
            "total_chats": len(self.chats),
            "forwarded_percent": (forwarded / total * 100) if total > 0 else 0,
            "copied_percent": (copied / total * 100) if total > 0 else 0,
            "data_since": self.messages[0].timestamp[:10] if self.messages else "Нет данных"
        }
    
    def get_user_stats(self, user_id: int) -> Dict:
        if user_id not in self.users:
            return {"error": "User not found"}
        
        user = self.users[user_id]
        user_msgs = [m for m in self.messages if m.user_id == user_id]
        
        return {
            "user_id": user_id,
            "username": user.username,
            "messages_total": user.messages_count,
            "messages_forwarded": user.forwarded_count,
            "messages_copied": user.copied_count,
            "first_seen": user.first_seen[:19],
            "last_seen": user.last_seen[:19],
            "screenshot_risk_total": sum(m.screenshot_risk for m in user_msgs)
        }
    
    def get_chat_stats(self, chat_id: int) -> Dict:
        if chat_id not in self.chats:
            return {"error": "Chat not found"}
        
        chat = self.chats[chat_id]
        chat_msgs = [m for m in self.messages if m.chat_id == chat_id]
        
        # Топ пользователей
        user_counts = defaultdict(int)
        for msg in chat_msgs:
            user_counts[msg.user_id] += 1
        
        top_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "chat_id": chat_id,
            "title": chat.title,
            "messages_total": chat.messages_count,
            "users_total": chat.users_count,
            "top_users": [
                {"user_id": uid, "messages": count, "username": self.users.get(uid, UserStats(uid)).username}
                for uid, count in top_users
            ]
        }
    
    def get_all_users(self) -> List[Dict]:
        return [self.get_user_stats(uid) for uid in self.users]
    
    def get_all_chats(self) -> List[Dict]:
        return [self.get_chat_stats(cid) for cid in self.chats]
    
    def save(self):
        try:
            data = {
                "messages": [asdict(m) for m in self.messages[-2000:]],
                "users": {uid: asdict(u) for uid, u in self.users.items()},
                "chats": {cid: asdict(c) for cid, c in self.chats.items()},
                "saved_at": datetime.datetime.now().isoformat()
            }
            
            with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"Saved: {len(self.messages)} messages, {len(self.users)} users")
            
        except Exception as e:
            print(f"Save error: {e}")
    
    def load(self):
        try:
            if os.path.exists(Config.DATA_FILE):
                with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.messages = [MessageData(**m) for m in data.get("messages", [])]
                
                self.users = {}
                for uid_str, u_data in data.get("users", {}).items():
                    user = UserStats(**u_data)
                    self.users[user.user_id] = user
                
                self.chats = {}
                for cid_str, c_data in data.get("chats", {}).items():
                    chat = ChatStats(**c_data)
                    self.chats[chat.chat_id] = chat
                
                print(f"Loaded: {len(self.messages)} messages, {len(self.users)} users")
                
        except Exception as e:
            print(f"Load error: {e}")

# ========== TELEGRAM БОТ ==========
class TelegramBot:
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.storage = DataStorage()
        self.running = False
        self.last_update_id = 0
        
        # Логирование
        logging.basicConfig(
            level=Config.LOG_LEVEL,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    async def get_updates(self) -> List[Dict]:
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": Config.UPDATE_TIMEOUT,
                "allowed_updates": ["message"]
            }
            
            timeout = ClientTimeout(total=Config.UPDATE_TIMEOUT + 10)
            
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            return data.get("result", [])
                    
                    return []
                    
        except Exception as e:
            self.logger.error(f"Update error: {e}")
            return []
    
    async def process_update(self, update: Dict):
        try:
            update_id = update.get("update_id", 0)
            if update_id > self.last_update_id:
                self.last_update_id = update_id
            
            if "message" in update:
                msg = update["message"]
                
                # Игнорировать команды и служебные
                if msg.get('text', '').startswith('/'):
                    return
                if any(k in msg for k in ['new_chat_members', 'left_chat_member']):
                    return
                
                # Обработать
                success = self.storage.add_message(msg)
                if success:
                    user = msg.get('from', {})
                    name = user.get('username') or user.get('first_name', 'Unknown')
                    self.logger.info(f"Message from {name} (ID: {user.get('id')})")
                
        except Exception as e:
            self.logger.error(f"Process error: {e}")
    
    async def run(self):
        self.running = True
        
        print("\n" + "="*50)
        print("SILENT TELEGRAM STATS BOT")
        print("="*50)
        print(f"Token: {'Set' if Config.TELEGRAM_TOKEN else 'NOT SET!'}")
        print(f"Allowed users: {Config.ALLOWED_USER_IDS}")
        print(f"Detect forwards: {Config.DETECT_FORWARDS}")
        print(f"Detect copies: {Config.DETECT_COPIES}")
        print(f"Detect screenshots: {Config.DETECT_SCREENSHOTS}")
        print("="*50 + "\n")
        
        # Проверка подключения
        if not await self.test_connection():
            print("ERROR: Cannot connect to Telegram")
            return
        
        print("Bot started. Silent mode - no messages in chats.")
        
        # Автосохранение
        def auto_save():
            while self.running:
                time.sleep(300)
                self.storage.save()
        
        threading.Thread(target=auto_save, daemon=True).start()
        
        # Главный цикл
        while self.running:
            try:
                updates = await self.get_updates()
                
                for update in updates:
                    await self.process_update(update)
                
                await asyncio.sleep(1)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Main loop error: {e}")
                await asyncio.sleep(5)
        
        self.storage.save()
        print("\nBot stopped.")
    
    async def test_connection(self) -> bool:
        try:
            url = f"{self.base_url}/getMe"
            async with ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            bot_info = data.get("result", {})
                            print(f"✅ Connected as @{bot_info.get('username')}")
                            return True
            
            return False
            
        except Exception as e:
            print(f"Connection error: {e}")
            return False

# ========== ВЕБ СЕРВЕР ==========
def create_web_app(bot):
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        stats = bot.storage.get_overall_stats()
        users = bot.storage.get_all_users()
        chats = bot.storage.get_all_chats()
        
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Telegram Stats</title>
            <style>
                body { font-family: Arial; margin: 40px; background: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; }
                .header { background: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; }
                .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }
                .stat-box { background: white; padding: 20px; border-radius: 8px; text-align: center; }
                .stat-value { font-size: 2em; font-weight: bold; color: #007bff; }
                .section { background: white; padding: 25px; border-radius: 10px; margin-bottom: 20px; }
                table { width: 100%; border-collapse: collapse; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
                th { background: #f8f9fa; }
                .api-list { background: #f8f9fa; padding: 15px; border-radius: 8px; }
                .api-item { margin: 10px 0; font-family: monospace; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤫 Silent Telegram Stats</h1>
                    <p>Bot работает в тихом режиме (не пишет в чаты)</p>
                </div>
                
                <div class="stats">
                    <div class="stat-box">
                        <div class="stat-label">Сообщений</div>
                        <div class="stat-value">''' + str(stats['total_messages']) + '''</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Пользователей</div>
                        <div class="stat-value">''' + str(stats['total_users']) + '''</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Чатов</div>
                        <div class="stat-value">''' + str(stats['total_chats']) + '''</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Пересылок</div>
                        <div class="stat-value">''' + f"{stats['forwarded_percent']:.1f}%" + '''</div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>👥 Пользователи (первые 20)</h2>
                    <table>
                        <tr>
                            <th>ID</th>
                            <th>Username</th>
                            <th>Сообщений</th>
                            <th>Пересылок</th>
                            <th>Копий</th>
                        </tr>
        '''
        
        for user in users[:20]:
            if 'error' not in user:
                html += f'''
                        <tr>
                            <td>{user['user_id']}</td>
                            <td>{user['username'] or '—'}</td>
                            <td>{user['messages_total']}</td>
                            <td>{user['messages_forwarded']}</td>
                            <td>{user['messages_copied']}</td>
                        </tr>
                '''
        
        html += '''
                    </table>
                </div>
                
                <div class="section">
                    <h2>💬 Чаты</h2>
                    <table>
                        <tr>
                            <th>ID</th>
                            <th>Название</th>
                            <th>Сообщений</th>
                            <th>Пользователей</th>
                        </tr>
        '''
        
        for chat in chats[:10]:
            if 'error' not in chat:
                html += f'''
                        <tr>
                            <td>{chat['chat_id']}</td>
                            <td>{chat['title']}</td>
                            <td>{chat['messages_total']}</td>
                            <td>{chat['users_total']}</td>
                        </tr>
                '''
        
        html += '''
                    </table>
                </div>
                
                <div class="section">
                    <h2>🔧 API Endpoints</h2>
                    <div class="api-list">
                        <div class="api-item">GET /api/stats - Общая статистика</div>
                        <div class="api-item">GET /api/users - Все пользователи</div>
                        <div class="api-item">GET /api/user/&lt;id&gt; - Статистика пользователя</div>
                        <div class="api-item">GET /api/chats - Все чаты</div>
                        <div class="api-item">GET /api/chat/&lt;id&gt; - Статистика чата</div>
                        <div class="api-item">GET /api/export - Полный экспорт</div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        '''
        
        return html
    
    @app.route('/api/stats')
    def api_stats():
        return jsonify(bot.storage.get_overall_stats())
    
    @app.route('/api/users')
    def api_users():
        users = [u for u in bot.storage.get_all_users() if 'error' not in u]
        return jsonify({"users": users, "count": len(users)})
    
    @app.route('/api/user/<int:user_id>')
    def api_user(user_id):
        return jsonify(bot.storage.get_user_stats(user_id))
    
    @app.route('/api/chats')
    def api_chats():
        chats = [c for c in bot.storage.get_all_chats() if 'error' not in c]
        return jsonify({"chats": chats, "count": len(chats)})
    
    @app.route('/api/chat/<int:chat_id>')
    def api_chat(chat_id):
        return jsonify(bot.storage.get_chat_stats(chat_id))
    
    @app.route('/api/export')
    def api_export():
        data = {
            "stats": bot.storage.get_overall_stats(),
            "users": bot.storage.get_all_users(),
            "chats": bot.storage.get_all_chats(),
            "exported": datetime.datetime.now().isoformat()
        }
        return jsonify(data)
    
    return app

# ========== ЗАПУСК ==========
async def main():
    # Проверка конфигурации
    if not Config.validate():
        return
    
    # Создание бота
    bot = TelegramBot()
    
    # Запуск веб-сервера в отдельном потоке
    if FLASK_AVAILABLE:
        app = create_web_app(bot)
        
        def run_web():
            app.run(
                host=Config.WEB_HOST,
                port=Config.WEB_PORT,
                debug=False,
                use_reloader=False
            )
        
        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()
        print(f"🌐 Web interface: http://localhost:{Config.WEB_PORT}")
    else:
        print("⚠️  Flask not installed - web interface disabled")
    
    # Запуск бота
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nStopping bot...")
    finally:
        bot.storage.save()

if __name__ == "__main__":
    asyncio.run(main())
