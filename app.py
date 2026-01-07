import os
import json
import time
import logging
import threading
import datetime
from typing import Dict, List
from dataclasses import dataclass, asdict
from flask import Flask, jsonify, render_template_string
import requests

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

# Автоматически определяем WEBHOOK_URL
RENDER_SERVICE_NAME = os.environ.get("RENDER_SERVICE_NAME", "")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

if RENDER_EXTERNAL_URL:
    WEBHOOK_URL = RENDER_EXTERNAL_URL
elif RENDER_SERVICE_NAME:
    WEBHOOK_URL = f"https://{RENDER_SERVICE_NAME}.onrender.com"
else:
    WEBHOOK_URL = ""

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не установлен")
if not ALLOWED_IDS:
    raise ValueError("❌ ALLOWED_IDS не установлен")

print(f"🔧 Конфигурация:")
print(f"   Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
print(f"   Allowed IDs: {ALLOWED_IDS}")
print(f"   Port: {PORT}")
print(f"   Webhook URL: {WEBHOOK_URL}")

# ========== МОДЕЛИ ==========
@dataclass
class Message:
    message_id: int
    user_id: int
    chat_id: int
    timestamp: str
    text: str = ""
    is_forwarded: bool = False
    is_copy: bool = False
    screenshot_risk: int = 0

@dataclass
class User:
    user_id: int
    username: str = ""
    first_name: str = ""
    messages_count: int = 0
    forwarded_count: int = 0
    copied_count: int = 0
    first_seen: str = ""
    last_seen: str = ""

@dataclass
class Chat:
    chat_id: int
    title: str = ""
    messages_count: int = 0
    users_count: int = 0

# ========== ХРАНИЛИЩЕ ==========
class Storage:
    def __init__(self):
        self.messages: List[Message] = []
        self.users: Dict[int, User] = {}
        self.chats: Dict[int, Chat] = {}
        self.load()
    
    def save(self):
        try:
            data = {
                "messages": [asdict(m) for m in self.messages[-1000:]],
                "users": {uid: asdict(u) for uid, u in self.users.items()},
                "chats": {cid: asdict(c) for cid, c in self.chats.items()},
                "saved_at": datetime.datetime.now().isoformat()
            }
            with open("data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"💾 Данные сохранены: {len(self.messages)} сообщений")
        except Exception as e:
            print(f"❌ Ошибка сохранения: {e}")
    
    def load(self):
        try:
            if os.path.exists("data.json"):
                with open("data.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                self.messages = [Message(**m) for m in data.get("messages", [])]
                
                self.users = {}
                for uid_str, u_data in data.get("users", {}).items():
                    user = User(**u_data)
                    self.users[user.user_id] = user
                
                self.chats = {}
                for cid_str, c_data in data.get("chats", {}).items():
                    chat = Chat(**c_data)
                    self.chats[chat.chat_id] = chat
                    
                print(f"📂 Данные загружены: {len(self.messages)} сообщений, {len(self.users)} пользователей")
        except Exception as e:
            print(f"⚠️ Не удалось загрузить данные: {e}")
    
    def add_message(self, message_data: Dict) -> bool:
        try:
            user_id = message_data.get("from", {}).get("id", 0)
            if user_id not in ALLOWED_IDS:
                return False
            
            # Создать сообщение
            msg = Message(
                message_id=message_data.get("message_id", 0),
                user_id=user_id,
                chat_id=message_data.get("chat", {}).get("id", 0),
                timestamp=datetime.datetime.now().isoformat(),
                text=(message_data.get("text") or message_data.get("caption") or "")[:500],
                is_forwarded="forward_date" in message_data
            )
            
            # Проверить на копирование
            text_lower = msg.text.lower()
            if any(word in text_lower for word in ["скопировал", "копирую", "copy", "взял текст"]):
                msg.is_copy = True
            
            # Проверить на скриншоты
            if any(word in text_lower for word in ["скрин", "screenshot", "снимок", "сохранил", "покажу"]):
                msg.screenshot_risk = 50
            
            # Добавить в хранилище
            self.messages.append(msg)
            
            # Обновить пользователя
            user_info = message_data.get("from", {})
            if user_id not in self.users:
                self.users[user_id] = User(
                    user_id=user_id,
                    username=user_info.get("username", ""),
                    first_name=user_info.get("first_name", ""),
                    first_seen=msg.timestamp
                )
            
            user = self.users[user_id]
            user.messages_count += 1
            if msg.is_forwarded:
                user.forwarded_count += 1
            if msg.is_copy:
                user.copied_count += 1
            user.last_seen = msg.timestamp
            
            # Обновить чат
            chat_info = message_data.get("chat", {})
            chat_id = msg.chat_id
            if chat_id not in self.chats:
                self.chats[chat_id] = Chat(
                    chat_id=chat_id,
                    title=chat_info.get("title", f"Chat {chat_id}")
                )
            
            chat = self.chats[chat_id]
            chat.messages_count += 1
            
            # Обновить количество пользователей в чате
            user_ids = {m.user_id for m in self.messages if m.chat_id == chat_id}
            chat.users_count = len(user_ids)
            
            # Автосохранение
            if len(self.messages) % 50 == 0:
                self.save()
            
            # Логирование
            username = user_info.get("username") or user_info.get("first_name", "Unknown")
            log_msg = f"📨 Сообщение от {username} (ID: {user_id})"
            if msg.is_forwarded:
                log_msg += " [ПЕРЕСЛАНО]"
            if msg.is_copy:
                log_msg += " [КОПИЯ]"
            if msg.screenshot_risk > 0:
                log_msg += f" [СКРИНШОТ РИСК: {msg.screenshot_risk}%]"
            print(log_msg)
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка добавления сообщения: {e}")
            return False
    
    def get_stats(self) -> Dict:
        total = len(self.messages)
        forwarded = sum(1 for m in self.messages if m.is_forwarded)
        copied = sum(1 for m in self.messages if m.is_copy)
        
        return {
            "total_messages": total,
            "total_users": len(self.users),
            "total_chats": len(self.chats),
            "forwarded_percent": round((forwarded / total * 100) if total > 0 else 0, 1),
            "copied_percent": round((copied / total * 100) if total > 0 else 0, 1),
            "data_since": self.messages[0].timestamp[:10] if self.messages else "Нет данных",
            "last_update": datetime.datetime.now().isoformat()[:19]
        }
    
    def get_users(self) -> List[Dict]:
        result = []
        for user in self.users.values():
            result.append({
                "user_id": user.user_id,
                "username": user.username,
                "first_name": user.first_name,
                "messages_count": user.messages_count,
                "forwarded_count": user.forwarded_count,
                "copied_count": user.copied_count,
                "first_seen": user.first_seen[:19] if user.first_seen else "",
                "last_seen": user.last_seen[:19] if user.last_seen else ""
            })
        return sorted(result, key=lambda x: x["messages_count"], reverse=True)
    
    def get_chats(self) -> List[Dict]:
        result = []
        for chat in self.chats.values():
            result.append({
                "chat_id": chat.chat_id,
                "title": chat.title,
                "messages_count": chat.messages_count,
                "users_count": chat.users_count
            })
        return sorted(result, key=lambda x: x["messages_count"], reverse=True)

# ========== TELEGRAM БОТ ==========
class TelegramBot:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.storage = Storage()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.webhook_set = False
    
    def setup_webhook(self):
        """Установить вебхук"""
        if not WEBHOOK_URL:
            print("⚠️ WEBHOOK_URL не установлен, используем polling")
            return False
        
        try:
            url = f"{self.base_url}/setWebhook"
            data = {
                "url": f"{WEBHOOK_URL}/webhook",
                "max_connections": 40,
                "allowed_updates": ["message", "edited_message"]
            }
            
            print(f"🔗 Устанавливаю webhook: {WEBHOOK_URL}/webhook")
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if result.get("ok"):
                print(f"✅ Webhook установлен успешно")
                self.webhook_set = True
                return True
            else:
                print(f"❌ Ошибка webhook: {result}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка установки webhook: {e}")
            return False
    
    def process_webhook(self, update: Dict) -> bool:
        """Обработать вебхук"""
        try:
            if "message" in update:
                message = update["message"]
                
                # Игнорировать команды
                if message.get("text", "").startswith("/"):
                    return False
                
                # Игнорировать служебные
                if any(key in message for key in ["new_chat_members", "left_chat_member"]):
                    return False
                
                # Добавить в статистику
                return self.storage.add_message(message)
                    
            return False
            
        except Exception as e:
            print(f"❌ Ошибка обработки вебхука: {e}")
            return False

# ========== FLASK APP ==========
app = Flask(__name__)
bot = TelegramBot()

# Автосохранение каждые 5 минут
def auto_save():
    while True:
        time.sleep(300)
        bot.storage.save()

threading.Thread(target=auto_save, daemon=True).start()

# HTML шаблон
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>🤫 Silent Telegram Stats</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 20px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .header h1 {
            color: #667eea;
            font-size: 2em;
            margin-bottom: 10px;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 3px 10px rgba(0,0,0,0.08);
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
            margin: 5px 0;
        }
        .stat-label {
            color: #666;
            font-size: 0.9em;
        }
        .section {
            background: white;
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 20px;
            box-shadow: 0 3px 10px rgba(0,0,0,0.08);
        }
        .section h2 {
            color: #667eea;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }
        tr:hover {
            background: #f5f7fa;
        }
        .api-list {
            display: grid;
            gap: 10px;
        }
        .api-item {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 8px;
            border-left: 3px solid #667eea;
            font-family: monospace;
            font-size: 0.9em;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            color: white;
            opacity: 0.8;
            font-size: 0.9em;
        }
        .status {
            display: inline-block;
            padding: 5px 10px;
            background: #4CAF50;
            color: white;
            border-radius: 20px;
            font-size: 0.8em;
            margin-top: 10px;
        }
        .config-table {
            width: 100%;
            margin-top: 10px;
        }
        .config-table td {
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        .config-table td:first-child {
            font-weight: 500;
            color: #555;
        }
        .btn {
            display: inline-block;
            padding: 8px 16px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            margin-top: 10px;
            font-size: 0.9em;
        }
        .btn:hover {
            background: #5a67d8;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤫 Silent Telegram Stats Bot</h1>
            <p>Тихая система сбора статистики. Бот НЕ пишет в чаты.</p>
            <div class="status">🟢 СИСТЕМА АКТИВНА</div>
            {% if webhook_url %}
            <a href="/setup" class="btn">Установить Webhook</a>
            {% endif %}
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Сообщений</div>
                <div class="stat-value">{{ stats.total_messages }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Пользователей</div>
                <div class="stat-value">{{ stats.total_users }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Чатов</div>
                <div class="stat-value">{{ stats.total_chats }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Пересылок</div>
                <div class="stat-value">{{ stats.forwarded_percent }}%</div>
            </div>
        </div>
        
        <div class="section">
            <h2>👥 Пользователи (топ-20)</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Username</th>
                    <th>Сообщений</th>
                    <th>Пересылок</th>
                    <th>Копий</th>
                    <th>Последняя активность</th>
                </tr>
                {% for user in users[:20] %}
                <tr>
                    <td><code>{{ user.user_id }}</code></td>
                    <td><strong>@{{ user.username or '—' }}</strong></td>
                    <td>{{ user.messages_count }}</td>
                    <td>{{ user.forwarded_count }}</td>
                    <td>{{ user.copied_count }}</td>
                    <td>{{ user.last_seen or '—' }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="section">
            <h2>💬 Чаты</h2>
            <table>
                <tr>
                    <th>Название</th>
                    <th>Сообщений</th>
                    <th>Участников</th>
                </tr>
                {% for chat in chats %}
                <tr>
                    <td>{{ chat.title }}</td>
                    <td>{{ chat.messages_count }}</td>
                    <td>{{ chat.users_count }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="section">
            <h2>🔧 API</h2>
            <div class="api-list">
                <div class="api-item">GET <a href="/api/stats" target="_blank">/api/stats</a> - Статистика</div>
                <div class="api-item">GET <a href="/api/users" target="_blank">/api/users</a> - Пользователи</div>
                <div class="api-item">GET <a href="/api/chats" target="_blank">/api/chats</a> - Чаты</div>
                <div class="api-item">GET <a href="/api/export" target="_blank">/api/export</a> - Экспорт</div>
                <div class="api-item">GET <a href="/health" target="_blank">/health</a> - Проверка</div>
            </div>
        </div>
        
        <div class="section">
            <h2>⚙️ Конфигурация</h2>
            <table class="config-table">
                <tr>
                    <td>Разрешённые ID:</td>
                    <td><code>{{ allowed_ids }}</code></td>
                </tr>
                <tr>
                    <td>Webhook URL:</td>
                    <td>{{ webhook_url or 'Не установлен' }}</td>
                </tr>
                <tr>
                    <td>Webhook статус:</td>
                    <td>{{ 'Установлен' if webhook_enabled else 'Не установлен' }}</td>
                </tr>
                <tr>
                    <td>Сбор данных с:</td>
                    <td>{{ stats.data_since }}</td>
                </tr>
                <tr>
                    <td>Последнее обновление:</td>
                    <td>{{ stats.last_update }}</td>
                </tr>
            </table>
        </div>
        
        <div class="footer">
            <p>Silent Telegram Stats Bot • Тихий режим • Данные обновляются в реальном времени</p>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    stats = bot.storage.get_stats()
    users = bot.storage.get_users()
    chats = bot.storage.get_chats()
    
    return render_template_string(
        HTML_TEMPLATE,
        stats=stats,
        users=users,
        chats=chats,
        allowed_ids=ALLOWED_IDS,
        webhook_url=WEBHOOK_URL,
        webhook_enabled=bot.webhook_set
    )

@app.route('/api/stats')
def api_stats():
    return jsonify(bot.storage.get_stats())

@app.route('/api/users')
def api_users():
    users = bot.storage.get_users()
    return jsonify({"users": users, "count": len(users)})

@app.route('/api/chats')
def api_chats():
    chats = bot.storage.get_chats()
    return jsonify({"chats": chats, "count": len(chats)})

@app.route('/api/export')
def api_export():
    data = {
        "stats": bot.storage.get_stats(),
        "users": bot.storage.get_users(),
        "chats": bot.storage.get_chats(),
        "exported_at": datetime.datetime.now().isoformat()
    }
    return jsonify(data)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхука от Telegram"""
    try:
        update = request.get_json()
        if update:
            bot.process_webhook(update)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False}), 500

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": "telegram-stats-bot",
        "timestamp": datetime.datetime.now().isoformat(),
        "stats": {
            "messages": len(bot.storage.messages),
            "users": len(bot.storage.users),
            "chats": len(bot.storage.chats)
        }
    })

@app.route('/setup')
def setup_webhook_route():
    """Установить вебхук вручную"""
    if bot.setup_webhook():
        return jsonify({"ok": True, "message": "Webhook установлен", "url": f"{WEBHOOK_URL}/webhook"})
    return jsonify({"ok": False, "message": "Ошибка установки webhook"})

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🤫 SILENT TELEGRAM STATS BOT")
    print("="*60)
    print(f"🔑 Токен: {'✓ Установлен' if TELEGRAM_TOKEN else '✗ НЕ УСТАНОВЛЕН'}")
    print(f"👥 Разрешённые ID: {ALLOWED_IDS}")
    print(f"🌐 Порт: {PORT}")
    print(f"🔗 Webhook URL: {WEBHOOK_URL or 'Не установлен'}")
    print(f"📊 Сообщений в базе: {len(bot.storage.messages)}")
    print("="*60)
    print("⚡ Бот запущен в ТИХОМ РЕЖИМЕ")
    print("📊 Веб-интерфейс доступен по адресу: /")
    print("🔧 API доступен по адресам: /api/*")
    print("="*60 + "\n")
    
    # Попробовать установить вебхук
    if WEBHOOK_URL:
        print("🔄 Пробую установить webhook...")
        bot.setup_webhook()
    
    # Запустить Flask
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
