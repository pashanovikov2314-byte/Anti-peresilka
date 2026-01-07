import os
import json
import time
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
import requests

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

print("="*60)
print("🛡️  ADVANCED SECURITY TELEGRAM BOT")
print("="*60)
print(f"Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
print(f"Allowed IDs: {ALLOWED_IDS}")
print("="*60)

# ========== ХРАНИЛИЩЕ ==========
class Storage:
    def __init__(self):
        self.messages = []
        self.users = {}
        self.chats = {}
        self.leaks = []
        self.chat_members = {}  # Участники чатов
        self.bot_chats = set()  # Чаты где есть бот
        self.load()
    
    def save(self):
        try:
            data = {
                "messages": self.messages[-5000:],
                "users": self.users,
                "chats": self.chats,
                "leaks": self.leaks[-200:],
                "chat_members": self.chat_members,
                "bot_chats": list(self.bot_chats),
                "saved": datetime.now().isoformat()
            }
            with open("data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"💾 Saved: {len(self.messages)} msgs, {len(self.leaks)} leaks, {len(self.bot_chats)} chats")
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
                self.chat_members = data.get("chat_members", {})
                self.bot_chats = set(data.get("bot_chats", []))
                print(f"📂 Loaded: {len(self.messages)} msgs, {len(self.bot_chats)} chats")
        except Exception as e:
            print(f"Load error: {e}")

storage = Storage()

# ========== УЛУЧШЕННЫЙ АНАЛИЗАТОР ==========
class AdvancedLeakDetector:
    def __init__(self):
        # Многоуровневые паттерны
        self.patterns = {
            "high_risk": {
                "финансы": [r'\b\d{16}\b', r'\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b'],
                "паспорт": [r'паспорт\s*[№#]?\s*\d{6}', r'серия\s*\d{4}\s*номер\s*\d{6}'],
                "логины": [r'логин[:\s]*[\w@\.-]{3,}', r'login[:\s]*[\w@\.-]{3,}'],
                "пароли": [r'пароль[:\s]*[^\s]{6,}', r'password[:\s]*[^\s]{6,}'],
                "токены": [r'токен[:\s]*[a-zA-Z0-9]{10,}', r'token[:\s]*[a-zA-Z0-9]{10,}']
            },
            "medium_risk": {
                "пересылка": ["переслал", "forwarded", "отправил всем", "распространил"],
                "копирование": ["скопировал", "копирую", "copy", "сохранил себе", "взял текст"],
                "скриншот": ["скрин", "screenshot", "снимок экрана", "заскринил", "снял на фото"],
                "утечка": ["слил", "утекло", "слито", "утечка", "просочилось", "выложил"]
            },
            "low_risk": {
                "сохранение": ["сохранил", "запомнил", "зафиксировал", "имею копию"],
                "распространение": ["покажу", "разошлю", "отправлю всем", "скину"],
                "секрет": ["секрет", "конфиденциально", "тайна", "не говори"]
            }
        }
        
        # Контекстные фразы
        self.context_phrases = [
            ("покажу всем", 40),
            ("уже у всех", 35),
            ("разошлю в общий чат", 45),
            ("в открытом доступе", 30),
            ("скину в телеграм", 25),
            ("сохранил на диск", 20),
            ("имею доступ", 25)
        ]
    
    def detect_leaks(self, text: str, is_forwarded: bool = False, has_reply: bool = False) -> dict:
        """Многоуровневая проверка на утечки"""
        if not text:
            return {"has_leak": False, "risk_score": 0, "leak_types": [], "details": []}
        
        text_lower = text.lower()
        leak_types = []
        details = []
        risk_score = 0
        
        # 1. Проверка на пересылку (высокий приоритет)
        if is_forwarded:
            leak_types.append("пересылка_сообщения")
            details.append("Обнаружена пересылка сообщения")
            risk_score += 30
        
        # 2. Проверка высокорисковых паттернов
        for category, patterns in self.patterns["high_risk"].items():
            for pattern in patterns:
                if isinstance(pattern, str):
                    if pattern in text_lower:
                        leak_types.append(f"high_{category}")
                        details.append(f"Обнаружены {category}")
                        risk_score += 40
                        break
                else:  # regex pattern
                    if re.search(pattern, text_lower):
                        leak_types.append(f"high_{category}")
                        details.append(f"Обнаружены {category} (regex)")
                        risk_score += 45
                        break
        
        # 3. Среднерисковые паттерны
        for category, keywords in self.patterns["medium_risk"].items():
            for keyword in keywords:
                if keyword in text_lower:
                    leak_types.append(f"medium_{category}")
                    details.append(f"Обнаружено {category}")
                    risk_score += 25
                    break
        
        # 4. Низкорисковые паттерны
        for category, keywords in self.patterns["low_risk"].items():
            for keyword in keywords:
                if keyword in text_lower:
                    leak_types.append(f"low_{category}")
                    details.append(f"Обнаружено {category}")
                    risk_score += 15
                    break
        
        # 5. Контекстные фразы
        for phrase, score in self.context_phrases:
            if phrase in text_lower:
                leak_types.append(f"context_{phrase[:10]}")
                details.append(f"Обнаружена опасная фраза: {phrase}")
                risk_score += score
        
        # 6. Проверка длины одинакового текста (копирование)
        if len(text) > 50 and has_reply:
            # Проверяем, не является ли это копией предыдущего сообщения
            leak_types.append("возможное_копирование")
            details.append("Длинный текст в ответе - возможное копирование")
            risk_score += 20
        
        # 7. Проверка на скрытые данные
        hidden_patterns = [
            (r'[\w\.-]+@[\w\.-]+\.\w+', "email"),
            (r'(https?://[^\s]+)', "ссылка"),
            (r'\b\d{10,}\b', "длинный_номер")
        ]
        
        for pattern, label in hidden_patterns:
            if re.search(pattern, text):
                leak_types.append(f"hidden_{label}")
                details.append(f"Обнаружен {label}")
                risk_score += 10
        
        return {
            "has_leak": len(leak_types) > 0,
            "risk_score": min(100, risk_score),
            "leak_types": leak_types,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }

detector = AdvancedLeakDetector()

# ========== TELEGRAM API ==========
def send_telegram_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Отправить сообщение в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=10)
        if response.json().get("ok"):
            return True
        else:
            print(f"Send error: {response.json()}")
            return False
    except Exception as e:
        print(f"Send message error: {e}")
        return False

def get_chat_info(chat_id: int):
    """Получить информацию о чате"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getChat"
        data = {"chat_id": chat_id}
        response = requests.post(url, json=data, timeout=10)
        return response.json().get("result", {})
    except:
        return {}

# ========== FLASK APP ==========
app = Flask(__name__)

# HTML шаблоны
@app.route('/')
def home():
    stats = {
        "total_messages": len(storage.messages),
        "total_users": len(storage.users),
        "total_chats": len(storage.chats),
        "total_leaks": len(storage.leaks),
        "bot_chats_count": len(storage.bot_chats),
        "last_leak": storage.leaks[-1] if storage.leaks else None,
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Получаем последние сообщения
    recent_messages = storage.messages[-20:][::-1]
    
    # Получаем чаты с ботом
    bot_chats_info = []
    for chat_id in list(storage.bot_chats)[:10]:
        chat_info = storage.chats.get(str(chat_id), {"title": f"Chat {chat_id}", "id": chat_id})
        bot_chats_info.append(chat_info)
    
    # Получаем последние утечки
    recent_leaks = storage.leaks[-10:][::-1]
    
    # Статистика по дням
    daily_stats = {}
    for msg in storage.messages[-1000:]:
        date = msg.get("time", "")[:10]
        if date:
            daily_stats[date] = daily_stats.get(date, 0) + 1
    
    return render_template('index.html',
                         stats=stats,
                         allowed_ids=ALLOWED_IDS,
                         recent_messages=recent_messages,
                         bot_chats=bot_chats_info,
                         recent_leaks=recent_leaks,
                         daily_stats=sorted(daily_stats.items())[-7:])

@app.route('/api/stats')
def api_stats():
    # Подробная статистика
    stats = {
        "general": {
            "messages": len(storage.messages),
            "users": len(storage.users),
            "chats": len(storage.chats),
            "leaks": len(storage.leaks),
            "bot_chats": len(storage.bot_chats)
        },
        "today": {
            "messages": len([m for m in storage.messages if m.get("time", "").startswith(datetime.now().strftime("%Y-%m-%d"))]),
            "leaks": len([l for l in storage.leaks if l.get("timestamp", "").startswith(datetime.now().strftime("%Y-%m-%d"))])
        },
        "leak_types": {},
        "top_users": sorted(list(storage.users.values()), key=lambda x: x.get("messages", 0), reverse=True)[:10],
        "top_chats": sorted(list(storage.chats.values()), key=lambda x: x.get("messages_count", 0), reverse=True)[:10],
        "bot_active_chats": list(storage.bot_chats)[:20],
        "timestamp": datetime.now().isoformat()
    }
    
    # Анализ типов утечек
    for leak in storage.leaks:
        for leak_type in leak.get("leak_types", []):
            stats["leak_types"][leak_type] = stats["leak_types"].get(leak_type, 0) + 1
    
    return jsonify(stats)

@app.route('/api/leaks')
def api_leaks():
    leaks = storage.leaks[-100:][::-1]
    return jsonify({
        "leaks": leaks,
        "count": len(leaks),
        "high_risk_count": len([l for l in leaks if l.get("risk_score", 0) > 70])
    })

@app.route('/api/users')
def api_users():
    users_list = []
    for user_id, user_data in storage.users.items():
        user_leaks = [l for l in storage.leaks if l.get("user_id") == user_id]
        user_data_copy = user_data.copy()
        user_data_copy["leaks_count"] = len(user_leaks)
        user_data_copy["risk_score"] = sum(l.get("risk_score", 0) for l in user_leaks) / len(user_leaks) if user_leaks else 0
        users_list.append(user_data_copy)
    
    return jsonify({
        "users": sorted(users_list, key=lambda x: x.get("messages", 0), reverse=True),
        "count": len(users_list)
    })

@app.route('/api/chats')
def api_chats():
    chats_list = []
    for chat_id, chat_data in storage.chats.items():
        chat_data_copy = chat_data.copy()
        chat_data_copy["has_bot"] = int(chat_id) in storage.bot_chats
        chat_data_copy["leaks_count"] = len([l for l in storage.leaks if l.get("chat_id") == int(chat_id)])
        chats_list.append(chat_data_copy)
    
    return jsonify({
        "chats": sorted(chats_list, key=lambda x: x.get("messages_count", 0), reverse=True),
        "count": len(chats_list)
    })

@app.route('/api/bot_chats')
def api_bot_chats():
    """Список чатов, где есть бот"""
    bot_chats_detailed = []
    for chat_id in storage.bot_chats:
        chat_info = storage.chats.get(str(chat_id), {"title": f"Chat {chat_id}", "id": chat_id})
        chat_info["has_bot"] = True
        chat_info["messages_in_chat"] = len([m for m in storage.messages if m.get("chat_id") == chat_id])
        chat_info["leaks_in_chat"] = len([l for l in storage.leaks if l.get("chat_id") == chat_id])
        bot_chats_detailed.append(chat_info)
    
    return jsonify({
        "bot_chats": sorted(bot_chats_detailed, key=lambda x: x.get("messages_in_chat", 0), reverse=True),
        "count": len(bot_chats_detailed)
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": "advanced-security-bot",
        "timestamp": datetime.now().isoformat(),
        "database": {
            "messages": len(storage.messages),
            "users": len(storage.users),
            "chats": len(storage.chats)
        },
        "webhook_active": True
    })

@app.route('/setup')
def setup():
    """Установка webhook"""
    try:
        webhook_url = os.environ.get("RENDER_EXTERNAL_URL", "https://anti-peresilka.onrender.com")
        webhook_url = f"{webhook_url}/webhook"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {
            "url": webhook_url,
            "max_connections": 100,
            "allowed_updates": ["message", "edited_message", "chat_member", "my_chat_member"]
        }
        response = requests.post(url, json=data)
        
        if response.json().get("ok"):
            return jsonify({
                "ok": True,
                "message": "Webhook установлен",
                "url": webhook_url,
                "features": "Полный мониторинг включен"
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
        if not data:
            return jsonify({"ok": True})
        
        # Обработка добавления бота в чат
        if "my_chat_member" in data:
            chat_member = data["my_chat_member"]
            chat = chat_member.get("chat", {})
            chat_id = chat.get("id")
            
            if chat_id:
                storage.bot_chats.add(chat_id)
                storage.chats[str(chat_id)] = {
                    "id": chat_id,
                    "title": chat.get("title", f"Chat {chat_id}"),
                    "type": chat.get("type", ""),
                    "username": chat.get("username", ""),
                    "bot_added": datetime.now().isoformat()
                }
                
                print(f"🤖 Бот добавлен в чат: {chat.get('title')} (ID: {chat_id})")
        
        # Обработка сообщений
        if "message" in data:
            msg = data["message"]
            user_id = msg.get("from", {}).get("id", 0)
            chat_id = msg.get("chat", {}).get("id", 0)
            text = msg.get("text", "") or msg.get("caption", "")
            
            # Добавляем чат в список чатов бота
            storage.bot_chats.add(chat_id)
            
            # Сохраняем сообщение
            message_data = {
                "id": msg.get("message_id"),
                "user_id": user_id,
                "chat_id": chat_id,
                "text": text[:1000],
                "time": datetime.now().isoformat(),
                "is_forward": "forward_date" in msg,
                "has_reply": "reply_to_message" in msg,
                "has_media": any(key in msg for key in ["photo", "video", "document"]),
                "chat_title": msg.get("chat", {}).get("title", ""),
                "username": msg.get("from", {}).get("username", ""),
                "first_name": msg.get("from", {}).get("first_name", "")
            }
            
            storage.messages.append(message_data)
            
            # Обновляем информацию о чате
            chat_info = msg.get("chat", {})
            storage.chats[str(chat_id)] = {
                "id": chat_id,
                "title": chat_info.get("title", f"Chat {chat_id}"),
                "type": chat_info.get("type", ""),
                "username": chat_info.get("username", ""),
                "last_activity": datetime.now().isoformat(),
                "messages_count": len([m for m in storage.messages if m.get("chat_id") == chat_id])
            }
            
            # Обновляем пользователя
            if user_id not in storage.users:
                storage.users[user_id] = {
                    "id": user_id,
                    "username": msg.get("from", {}).get("username", ""),
                    "first_name": msg.get("from", {}).get("first_name", ""),
                    "last_name": msg.get("from", {}).get("last_name", ""),
                    "language_code": msg.get("from", {}).get("language_code", ""),
                    "messages": 0,
                    "leaks": 0,
                    "risk_score": 0,
                    "first_seen": datetime.now().isoformat(),
                    "chats": set()
                }
            
            user = storage.users[user_id]
            user["messages"] = user.get("messages", 0) + 1
            user["last_seen"] = datetime.now().isoformat()
            user["chats"] = user.get("chats", set())
            if isinstance(user["chats"], set):
                user["chats"].add(chat_id)
                user["chats"] = list(user["chats"])[:10]
            
            # Многоуровневая проверка на утечки
            leak_info = detector.detect_leaks(
                text=text,
                is_forwarded=message_data["is_forward"],
                has_reply=message_data["has_reply"]
            )
            
            if leak_info["has_leak"]:
                # Сохраняем утечку
                leak_record = {
                    "id": len(storage.leaks) + 1,
                    "user_id": user_id,
                    "username": user.get("username", ""),
                    "chat_id": chat_id,
                    "chat_title": message_data.get("chat_title", ""),
                    "text": text[:300],
                    "leak_types": leak_info["leak_types"],
                    "details": leak_info["details"],
                    "risk_score": leak_info["risk_score"],
                    "timestamp": leak_info["timestamp"],
                    "is_forward": message_data["is_forward"],
                    "message_id": message_data["id"]
                }
                
                storage.leaks.append(leak_record)
                user["leaks"] = user.get("leaks", 0) + 1
                user["risk_score"] = max(user.get("risk_score", 0), leak_info["risk_score"])
                
                print(f"⚠️ УТЕЧКА! Chat: {message_data.get('chat_title', chat_id)}, "
                      f"User: {user_id}, Risk: {leak_info['risk_score']}%, "
                      f"Types: {leak_info['leak_types']}")
                
                # Отправляем сообщение об утечке ТОЛЬКО разрешённым пользователям
                for allowed_id in ALLOWED_IDS:
                    if allowed_id != user_id:
                        # Красивый формат уведомления
                        if leak_info["risk_score"] > 70:
                            emoji = "🔴"
                            level = "ВЫСОКИЙ РИСК"
                        elif leak_info["risk_score"] > 40:
                            emoji = "🟠"
                            level = "СРЕДНИЙ РИСК"
                        else:
                            emoji = "🟡"
                            level = "НИЗКИЙ РИСК"
                        
                        chat_name = message_data.get("chat_title", f"чат ID: {chat_id}")
                        leak_types_str = ", ".join(leak_info["leak_types"][:5])
                        details_str = "\n".join(leak_info["details"][:3])
                        
                        alert_message = f"""
{emoji} <b>{level} - ОБНАРУЖЕНА УТЕЧКА!</b>

<b>📌 Информация об утечке:</b>
├─ Чат: <code>{chat_name}</code>
├─ Пользователь: @{user.get('username', 'без username')}
├─ ID пользователя: <code>{user_id}</code>
├─ Уровень риска: <b>{leak_info['risk_score']}%</b>
└─ Типы утечек: {leak_types_str}

<b>📋 Детали:</b>
{details_str}

<b>💬 Сообщение:</b>
<code>{text[:150]}{'...' if len(text) > 150 else ''}</code>

<b>🕒 Время:</b> {datetime.now().strftime('%H:%M:%S')}
<b>📊 Всего утечек:</b> {len(storage.leaks)}
"""
                        send_telegram_message(allowed_id, alert_message)
            
            # ОТВЕТ ПОЛЬЗОВАТЕЛЮ - только если он разрешённый
            if user_id in ALLOWED_IDS:
                if text.lower() in ["/start", "/старт"]:
                    welcome_msg = f"""
🛡️ <b>ПРИВЕТСТВУЮ, {msg.get('from', {}).get('first_name', 'КОЛЛЕГА')}!</b>

Я — <b>Advanced Security Bot</b>, ваша система мониторинга утечек.

<b>🌟 ВОЗМОЖНОСТИ:</b>
├─ 🔍 <b>Многоуровневая проверка</b> сообщений
├─ ⚠️ <b>Мгновенное оповещение</b> об утечках
├─ 📊 <b>Детальная статистика</b> по чатам
├─ 👥 <b>Мониторинг активности</b> пользователей
└─ 🔐 <b>Защита конфиденциальных данных</b>

<b>📈 ТЕКУЩАЯ СТАТИСТИКА:</b>
├─ 📨 Сообщений: <b>{len(storage.messages)}</b>
├─ 👥 Пользователей: <b>{len(storage.users)}</b>
├─ 💬 Чатов с ботом: <b>{len(storage.bot_chats)}</b>
├─ ⚠️ Обнаружено утечек: <b>{len(storage.leaks)}</b>
└─ 🕒 Активен с: <b>{storage.messages[0]['time'][:10] if storage.messages else 'сегодня'}</b>

<b>🔧 КОМАНДЫ:</b>
├─ /stats — общая статистика
├─ /mystats — ваша статистика
├─ /chats — чаты с ботом
└─ /leaks — последние утечки

<b>🔗 Веб-панель:</b> https://anti-peresilka.onrender.com
"""
                    send_telegram_message(chat_id, welcome_msg)
                
                elif text.lower() in ["/stats", "/статистика"]:
                    stats_msg = f"""
<b>📊 РЕАЛЬНАЯ СТАТИСТИКА СИСТЕМЫ</b>

<b>📋 ОБЩИЕ ДАННЫЕ:</b>
├─ 📨 Сообщений обработано: <b>{len(storage.messages)}</b>
├─ 👥 Уникальных пользователей: <b>{len(storage.users)}</b>
├─ 💬 Чатов под мониторингом: <b>{len(storage.bot_chats)}</b>
└─ ⚠️ Утечек обнаружено: <b>{len(storage.leaks)}</b>

<b>📈 АКТИВНОСТЬ ЗА СЕГОДНЯ:</b>
├─ 📨 Сообщений сегодня: <b>{len([m for m in storage.messages if m.get('time', '').startswith(datetime.now().strftime('%Y-%m-%d'))])}</b>
├─ ⚠️ Утечек сегодня: <b>{len([l for l in storage.leaks if l.get('timestamp', '').startswith(datetime.now().strftime('%Y-%m-%d'))])}</b>
└─ 🕒 Последнее обновление: <b>{datetime.now().strftime('%H:%M:%S')}</b>

<b>🏆 ТОП АКТИВНОСТИ:</b>
├─ 🥇 Самый активный пользователь: <b>@{max(storage.users.values(), key=lambda x: x.get('messages', 0)).get('username', 'N/A')}</b>
├─ 🥈 Самый "утечливый" чат: <b>{max(storage.chats.values(), key=lambda x: len([l for l in storage.leaks if l.get('chat_id') == x.get('id')])).get('title', 'N/A')[:20]}</b>
└─ ⏱️ Время работы системы: <b>{((datetime.now() - datetime.fromisoformat(storage.messages[0]['time'])).days if storage.messages else 0)} дней</b>

<i>🔗 Подробная статистика на веб-панели</i>
"""
                    send_telegram_message(chat_id, stats_msg)
                
                elif text.lower() == "/mystats":
                    user_data = storage.users.get(user_id, {})
                    user_leaks = [l for l in storage.leaks if l.get("user_id") == user_id]
                    
                    mystats_msg = f"""
<b>📊 ВАША ЛИЧНАЯ СТАТИСТИКА</b>

<b>👤 ПРОФИЛЬ:</b>
├─ ID: <code>{user_id}</code>
├─ Username: @{user_data.get('username', 'не установлен')}
├─ Имя: <b>{user_data.get('first_name', 'Неизвестно')}</b>
└─ Активен в: <b>{len(user_data.get('chats', []))} чатах</b>

<b>📈 АКТИВНОСТЬ:</b>
├─ 📨 Всего сообщений: <b>{user_data.get('messages', 0)}</b>
├─ ⚠️ Обнаружено утечек: <b>{user_data.get('leaks', 0)}</b>
├─ 🎯 Общий риск: <b>{user_data.get('risk_score', 0)}%</b>
├─ 👀 Первое появление: <b>{user_data.get('first_seen', '')[:16]}</b>
└─ 🕒 Последняя активность: <b>{user_data.get('last_seen', '')[:16] if user_data.get('last_seen') else 'только что'}</b>

<b>📊 ДЕТАЛИ УТЕЧЕК:</b>
"""
                    if user_leaks:
                        for i, leak in enumerate(user_leaks[-3:], 1):
                            mystats_msg += f"├─ {i}. Риск {leak.get('risk_score', 0)}%: {leak.get('leak_types', [''])[0]}\n"
                    else:
                        mystats_msg += "└─ 🟢 Утечек не обнаружено\n"
                    
                    mystats_msg += f"\n<i>Ваша активность мониторится в {len(storage.bot_chats)} чатах</i>"
                    send_telegram_message(chat_id, mystats_msg)
                
                elif text.lower() in ["/chats", "/чаты"]:
                    if storage.bot_chats:
                        chats_msg = f"""
<b>💬 ЧАТЫ С БОТОМ ({len(storage.bot_chats)})</b>

<b>ТОП-10 по активности:</b>
"""
                        chats_with_stats = []
                        for chat_id in list(storage.bot_chats)[:10]:
                            chat_messages = len([m for m in storage.messages if m.get("chat_id") == chat_id])
                            chat_leaks = len([l for l in storage.leaks if l.get("chat_id") == chat_id])
                            chat_title = storage.chats.get(str(chat_id), {}).get("title", f"Chat {chat_id}")
                            chats_with_stats.append((chat_title, chat_messages, chat_leaks))
                        
                        chats_with_stats.sort(key=lambda x: x[1], reverse=True)
                        
                        for i, (title, msg_count, leak_count) in enumerate(chats_with_stats[:10], 1):
                            chats_msg += f"{i}. <b>{title[:30]}</b>\n"
                            chats_msg += f"   📨 {msg_count} сообщ. | ⚠️ {leak_count} утечек\n"
                        
                        chats_msg += f"\n<i>Полный список на веб-панели</i>"
                    else:
                        chats_msg = "🤖 Бот пока не добавлен ни в один чат"
                    
                    send_telegram_message(chat_id, chats_msg)
                
                elif text.lower() in ["/leaks", "/утечки"]:
                    if storage.leaks:
                        leaks_msg = f"""
<b>⚠️ ПОСЛЕДНИЕ УТЕЧКИ ({min(5, len(storage.leaks))} из {len(storage.leaks)})</b>
"""
                        for i, leak in enumerate(storage.leaks[-5:][::-1], 1):
                            risk_emoji = "🔴" if leak.get("risk_score", 0) > 70 else "🟠" if leak.get("risk_score", 0) > 40 else "🟡"
                            chat_name = leak.get("chat_title", f"чат {leak.get('chat_id')}")
                            leak_type = leak.get("leak_types", ["неизвестно"])[0]
                            
                            leaks_msg += f"\n{i}. {risk_emoji} <b>Риск {leak.get('risk_score', 0)}%</b>\n"
                            leaks_msg += f"   📍 {chat_name[:25]}\n"
                            leaks_msg += f"   👤 @{leak.get('username', 'unknown')}\n"
                            leaks_msg += f"   🔍 {leak_type}\n"
                            leaks_msg += f"   🕒 {leak.get('timestamp', '')[:16]}\n"
                    else:
                        leaks_msg = "🟢 Утечек пока не обнаружено"
                    
                    leaks_msg += f"\n<i>Подробности на веб-панели</i>"
                    send_telegram_message(chat_id, leaks_msg)
        
        # Автосохранение
        if len(storage.messages) % 25 == 0:
            storage.save()
        
        return jsonify({"ok": True, "processed": True})
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# Автосохранение каждые 3 минуты
def auto_save():
    while True:
        time.sleep(180)
        storage.save()

import threading
thread = threading.Thread(target=auto_save, daemon=True)
thread.start()

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Запуск ADVANCED SECURITY BOT...")
    print(f"✅ Отвечает только: {ALLOWED_IDS}")
    print(f"🔍 Многоуровневая проверка включена")
    print(f"📊 Мониторинг чатов: {len(storage.bot_chats)}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
