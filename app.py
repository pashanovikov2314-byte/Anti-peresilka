import os
import json
import time
from datetime import datetime
from flask import Flask, request, jsonify
import requests

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

print("="*60)
print("🔐 SECURITY TELEGRAM BOT - Отвечает только разрешённым")
print("="*60)
print(f"Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
print(f"Allowed IDs: {ALLOWED_IDS}")
print(f"Port: {PORT}")
print("="*60)

# ========== ХРАНИЛИЩЕ ==========
class Storage:
    def __init__(self):
        self.messages = []
        self.users = {}
        self.chats = {}
        self.leaks = []  # Утечки
        self.load()
    
    def save(self):
        try:
            data = {
                "messages": self.messages[-1000:],
                "users": self.users,
                "chats": self.chats,
                "leaks": self.leaks[-100:],
                "saved": datetime.now().isoformat()
            }
            with open("data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"💾 Saved: {len(self.messages)} messages, {len(self.leaks)} leaks")
        except Exception as e:
            print(f"Save error: {e}")
    
    def load(self):
        try:
            if os.path.exists("data.json"):
                with open("data.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.messages = data.get("messages", [])
                self.users = data.get("users", {})
                self.chats = data.get("chats", {})
                self.leaks = data.get("leaks", [])
                print(f"📂 Loaded: {len(self.messages)} messages, {len(self.leaks)} leaks")
        except:
            pass

storage = Storage()

# ========== АНАЛИЗАТОР УТЕЧЕК ==========
class LeakDetector:
    @staticmethod
    def detect_leaks(text: str) -> dict:
        """Обнаружить утечки в тексте"""
        text_lower = text.lower()
        leaks = []
        risk_score = 0
        
        # Паттерны для обнаружения
        patterns = {
            "пересылка": ["переслал", "forward", "отправил", "поделился"],
            "копирование": ["скопировал", "копирую", "copy", "сохранил текст"],
            "скриншот": ["скрин", "screenshot", "снимок", "заскринил"],
            "утечка": ["слил", "утекло", "слито", "утечка", "просочилось"],
            "секрет": ["секрет", "тайна", "конфиденциально", "не говори никому"],
            "данные": ["пароль", "логин", "карта", "счет", "паспорт", "номер"]
        }
        
        for leak_type, keywords in patterns.items():
            for keyword in keywords:
                if keyword in text_lower:
                    leaks.append(leak_type)
                    risk_score += 20
                    break
        
        # Контекстные фразы (более опасные)
        danger_phrases = [
            ("покажу всем", 40),
            ("распространил", 35),
            ("разошлю всем", 30),
            ("уже у всех", 30),
            ("в открытом доступе", 25)
        ]
        
        for phrase, score in danger_phrases:
            if phrase in text_lower:
                risk_score += score
                leaks.append(f"опасная_фраза: {phrase}")
        
        return {
            "has_leak": len(leaks) > 0,
            "risk_score": min(100, risk_score),
            "leak_types": list(set(leaks)),
            "timestamp": datetime.now().isoformat()
        }

detector = LeakDetector()

# ========== TELEGRAM API ==========
def send_telegram_message(chat_id: int, text: str):
    """Отправить сообщение в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=data, timeout=10)
        return response.json().get("ok", False)
    except Exception as e:
        print(f"Send message error: {e}")
        return False

# ========== FLASK APP ==========
app = Flask(__name__)

@app.route('/')
def home():
    stats = {
        "messages": len(storage.messages),
        "users": len(storage.users),
        "chats": len(storage.chats),
        "leaks": len(storage.leaks),
        "last_leak": storage.leaks[-1] if storage.leaks else None
    }
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>🔐 Security Bot</title>
        <style>
            body {{ font-family: Arial; margin: 40px; background: #f5f5f5; }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            .header {{ background: white; padding: 30px; border-radius: 15px; margin-bottom: 20px; }}
            h1 {{ color: #333; }}
            .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
            .stat-box {{ background: white; padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-value {{ font-size: 2em; font-weight: bold; color: #dc3545; }}
            .leaks {{ background: #fff3cd; padding: 20px; border-radius: 10px; margin: 20px 0; }}
            .leak-item {{ background: #f8d7da; padding: 10px; margin: 5px 0; border-radius: 5px; }}
            .api-list {{ background: #e9ecef; padding: 15px; border-radius: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔐 Security Telegram Bot</h1>
                <p>Бот отслеживает утечки и отвечает только разрешённым ID</p>
                <p><strong>Разрешённые ID:</strong> {ALLOWED_IDS}</p>
            </div>
            
            <div class="stats">
                <div class="stat-box">
                    <div>Сообщений</div>
                    <div class="stat-value">{stats['messages']}</div>
                </div>
                <div class="stat-box">
                    <div>Пользователей</div>
                    <div class="stat-value">{stats['users']}</div>
                </div>
                <div class="stat-box">
                    <div>Чатов</div>
                    <div class="stat-value">{stats['chats']}</div>
                </div>
                <div class="stat-box">
                    <div>Утечек</div>
                    <div class="stat-value">{stats['leaks']}</div>
                </div>
            </div>
            
            {f'<div class="leaks"><h3>⚠️ Последняя утечка:</h3><div class="leak-item">{stats["last_leak"]}</div></div>' if stats['last_leak'] else ''}
            
            <div class="api-list">
                <h3>🔧 API Endpoints:</h3>
                <ul>
                    <li><a href="/api/stats">/api/stats</a> - статистика</li>
                    <li><a href="/api/leaks">/api/leaks</a> - все утечки</li>
                    <li><a href="/api/users">/api/users</a> - пользователи</li>
                    <li><a href="/health">/health</a> - проверка работы</li>
                    <li><a href="/setup">/setup</a> - установить вебхук</li>
                </ul>
            </div>
            
            <div style="margin-top: 30px; color: #666;">
                <p>🤖 Бот отвечает только пользователям: {ALLOWED_IDS}</p>
                <p>⚠️ При обнаружении утечки бот сразу отправляет сообщение</p>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/api/stats')
def api_stats():
    stats = {
        "messages": len(storage.messages),
        "users": len(storage.users),
        "chats": len(storage.chats),
        "leaks": len(storage.leaks),
        "last_update": datetime.now().isoformat(),
        "allowed_users": ALLOWED_IDS
    }
    return jsonify(stats)

@app.route('/api/leaks')
def api_leaks():
    return jsonify({
        "leaks": storage.leaks[-50:],  # Последние 50 утечек
        "count": len(storage.leaks)
    })

@app.route('/api/users')
def api_users():
    return jsonify({
        "users": storage.users,
        "count": len(storage.users)
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": "security-telegram-bot",
        "timestamp": datetime.now().isoformat(),
        "webhook_active": True
    })

@app.route('/setup')
def setup():
    """Установка webhook"""
    try:
        webhook_url = os.environ.get("RENDER_EXTERNAL_URL", "https://anti-peresilka.onrender.com")
        webhook_url = f"{webhook_url}/webhook"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {"url": webhook_url}
        response = requests.post(url, json=data)
        
        if response.json().get("ok"):
            return jsonify({
                "ok": True,
                "message": "Webhook установлен",
                "url": webhook_url,
                "note": "Бот отвечает только пользователям с ID: " + str(ALLOWED_IDS)
            })
        else:
            return jsonify({"error": response.json()})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка сообщений от Telegram"""
    try:
        data = request.json
        if not data or "message" not in data:
            return jsonify({"ok": True})
        
        msg = data["message"]
        user_id = msg.get("from", {}).get("id", 0)
        chat_id = msg.get("chat", {}).get("id", 0)
        text = msg.get("text", "") or msg.get("caption", "")
        
        # Сохраняем сообщение
        message_data = {
            "id": msg.get("message_id"),
            "user_id": user_id,
            "chat_id": chat_id,
            "text": text[:500],
            "time": datetime.now().isoformat(),
            "is_forward": "forward_date" in msg
        }
        
        storage.messages.append(message_data)
        
        # Обновляем пользователя
        if user_id not in storage.users:
            storage.users[user_id] = {
                "id": user_id,
                "username": msg.get("from", {}).get("username", ""),
                "first_name": msg.get("from", {}).get("first_name", ""),
                "messages": 0,
                "leaks": 0,
                "first_seen": datetime.now().isoformat()
            }
        
        storage.users[user_id]["messages"] += 1
        storage.users[user_id]["last_seen"] = datetime.now().isoformat()
        
        # Анализируем на утечки
        if text:
            leak_info = detector.detect_leaks(text)
            
            if leak_info["has_leak"]:
                # Сохраняем утечку
                leak_record = {
                    "user_id": user_id,
                    "username": storage.users[user_id]["username"],
                    "text": text[:200],
                    "leak_types": leak_info["leak_types"],
                    "risk_score": leak_info["risk_score"],
                    "timestamp": leak_info["timestamp"],
                    "chat_id": chat_id
                }
                
                storage.leaks.append(leak_record)
                storage.users[user_id]["leaks"] += 1
                
                print(f"⚠️ УТЕЧКА ОБНАРУЖЕНА! User: {user_id}, Risk: {leak_info['risk_score']}%")
                
                # Отправляем сообщение об утечке ТОЛЬКО разрешённым пользователям
                for allowed_id in ALLOWED_IDS:
                    if allowed_id != user_id:  # Не отправляем самому нарушителю
                        alert_message = f"""
⚠️ <b>ОБНАРУЖЕНА УТЕЧКА!</b>

👤 <b>Пользователь:</b> @{storage.users[user_id]['username'] or 'Без username'} (ID: {user_id})
💬 <b>Сообщение:</b> {text[:100]}...
🎯 <b>Типы утечек:</b> {', '.join(leak_info['leak_types'])}
⚠️ <b>Уровень риска:</b> {leak_info['risk_score']}%
🕒 <b>Время:</b> {datetime.now().strftime('%H:%M:%S')}

📊 <i>Всего утечек от этого пользователя: {storage.users[user_id]['leaks']}</i>
"""
                        send_telegram_message(allowed_id, alert_message)
        
        # ОТВЕТ ПОЛЬЗОВАТЕЛЮ - только если он разрешённый
        if user_id in ALLOWED_IDS:
            if text.lower() in ["/start", "/help", "/старт", "/помощь"]:
                welcome_msg = f"""
👋 <b>Привет, {msg.get('from', {}).get('first_name', 'друг')}!</b>

Я - бот безопасности, который отслеживает утечки информации.

🔐 <b>Мои функции:</b>
• Отслеживание пересылок сообщений
• Обнаружение копирования контента
• Выявление упоминаний скриншотов
• Мониторинг утечек данных

📊 <b>Статистика:</b>
• Сообщений: {len(storage.messages)}
• Пользователей: {len(storage.users)}
• Утечек: {len(storage.leaks)}

⚠️ <b>При обнаружении утечки</b> я сразу сообщу всем разрешённым пользователям.

Разрешённые ID: {ALLOWED_IDS}
"""
                send_telegram_message(chat_id, welcome_msg)
            
            elif text.lower() in ["/stats", "/статистика"]:
                stats_msg = f"""
📊 <b>СТАТИСТИКА СИСТЕМЫ</b>

📨 <b>Сообщений:</b> {len(storage.messages)}
👥 <b>Пользователей:</b> {len(storage.users)}
💬 <b>Чатов:</b> {len(storage.chats)}
⚠️ <b>Утечек обнаружено:</b> {len(storage.leaks)}

🕒 <b>Последнее обновление:</b> {datetime.now().strftime('%H:%M:%S')}

<i>Для просмотра подробной статистики перейдите на сайт</i>
"""
                send_telegram_message(chat_id, stats_msg)
            
            elif text.lower() == "/mystats":
                user_stats = storage.users.get(user_id, {})
                mystats_msg = f"""
📊 <b>ВАША СТАТИСТИКА</b>

👤 <b>Вы:</b> @{user_stats.get('username', '')} (ID: {user_id})
📨 <b>Сообщений:</b> {user_stats.get('messages', 0)}
⚠️ <b>Утечек:</b> {user_stats.get('leaks', 0)}
👀 <b>Первое появление:</b> {user_stats.get('first_seen', '')[:16]}
🕒 <b>Последняя активность:</b> {user_stats.get('last_seen', '')[:16] if user_stats.get('last_seen') else 'Нет данных'}

<i>Бот следит за безопасностью ваших чатов</i>
"""
                send_telegram_message(chat_id, mystats_msg)
        
        # Автосохранение
        if len(storage.messages) % 20 == 0:
            storage.save()
        
        return jsonify({"ok": True, "processed": True})
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# Автосохранение каждые 5 минут
def auto_save():
    while True:
        time.sleep(300)
        storage.save()

import threading
thread = threading.Thread(target=auto_save, daemon=True)
thread.start()

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Starting SECURITY bot...")
    print(f"✅ Бот будет отвечать только пользователям: {ALLOWED_IDS}")
    print("⚠️ При обнаружении утечки - немедленное оповещение")
    app.run(host="0.0.0.0", port=PORT, debug=False)
