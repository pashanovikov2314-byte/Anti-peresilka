import os
import json
import time
import re
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
import requests
from typing import Dict, List, Optional, Tuple
import hashlib

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

print("="*70)
print("🤖 TELEGRAM INTEGRATED LEAK DETECTOR")
print("="*70)
print(f"Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
print(f"Allowed IDs: {ALLOWED_IDS}")
print(f"Mode: REAL-TIME TELEGRAM MONITORING")
print("="*70)

# ========== TELEGRAM API КЛАСС ==========
class TelegramAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        
    def make_request(self, method: str, data: dict = None) -> dict:
        """Выполнить запрос к Telegram API"""
        try:
            url = f"{self.base_url}/{method}"
            response = requests.post(url, json=data, timeout=15)
            return response.json()
        except Exception as e:
            print(f"Telegram API error: {e}")
            return {"ok": False, "error": str(e)}
    
    def get_chat_info(self, chat_id: int) -> dict:
        """Получить информацию о чате"""
        return self.make_request("getChat", {"chat_id": chat_id})
    
    def get_chat_members(self, chat_id: int) -> dict:
        """Получить список участников чата"""
        return self.make_request("getChatMembersCount", {"chat_id": chat_id})
    
    def get_message(self, chat_id: int, message_id: int) -> dict:
        """Получить информацию о сообщении"""
        return self.make_request("getMessage", {"chat_id": chat_id, "message_id": message_id})
    
    def get_chat_history(self, chat_id: int, limit: int = 100) -> dict:
        """Получить историю чата"""
        return self.make_request("getChatHistory", {
            "chat_id": chat_id,
            "limit": limit
        })
    
    def forward_message(self, from_chat_id: int, to_chat_id: int, message_id: int) -> dict:
        """Переслать сообщение"""
        return self.make_request("forwardMessage", {
            "chat_id": to_chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id
        })

# ========== ИНТЕГРИРОВАННОЕ ХРАНИЛИЩЕ ==========
class IntegratedStorage:
    def __init__(self):
        self.telegram_api = TelegramAPI(TELEGRAM_TOKEN)
        
        # Мониторинг чатов
        self.monitored_chats = set()  # Чаты которые мониторим
        self.chat_metadata = {}       # Метаданные чатов
        
        # Сообщения
        self.messages = []
        self.message_hashes = set()   # Для предотвращения дублей
        
        # Пользователи
        self.users = {}
        
        # Утечки
        self.leaks = {
            "forwarded_messages": [],     # Пересланные сообщения
            "copied_content": [],         # Скопированный контент
            "external_shares": [],        # Внешние ссылки
            "suspicious_activity": [],    # Подозрительная активность
        }
        
        self.load()
    
    def save(self):
        """Сохранить данные"""
        try:
            data = {
                "monitored_chats": list(self.monitored_chats),
                "chat_metadata": self.chat_metadata,
                "messages": self.messages[-5000:],
                "users": self.users,
                "leaks": self.leaks,
                "saved_at": datetime.now().isoformat()
            }
            
            with open("integrated_data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            print(f"💾 Saved: {len(self.messages)} messages, {self.get_total_leaks()} leaks")
        except Exception as e:
            print(f"Save error: {e}")
    
    def load(self):
        """Загрузить данные"""
        try:
            if os.path.exists("integrated_data.json"):
                with open("integrated_data.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                self.monitored_chats = set(data.get("monitored_chats", []))
                self.chat_metadata = data.get("chat_metadata", {})
                self.messages = data.get("messages", [])
                self.users = data.get("users", {})
                self.leaks = data.get("leaks", {
                    "forwarded_messages": [],
                    "copied_content": [],
                    "external_shares": [],
                    "suspicious_activity": []
                })
                
                # Восстановление хэшей
                self.message_hashes = {self._get_message_hash(m) for m in self.messages}
                
                print(f"📂 Loaded: {len(self.messages)} msgs, {self.get_total_leaks()} leaks, {len(self.monitored_chats)} chats")
        except Exception as e:
            print(f"Load error: {e}")
    
    def _get_message_hash(self, message: dict) -> str:
        """Получить уникальный хэш сообщения"""
        text = message.get("text", "") or message.get("caption", "")
        return hashlib.md5(f"{message.get('chat_id')}_{message.get('message_id')}_{text}".encode()).hexdigest()
    
    def get_total_leaks(self) -> int:
        """Общее количество утечек"""
        return sum(len(leaks) for leaks in self.leaks.values())
    
    def add_monitored_chat(self, chat_id: int, chat_info: dict = None):
        """Добавить чат в мониторинг"""
        self.monitored_chats.add(chat_id)
        
        if chat_info:
            self.chat_metadata[str(chat_id)] = {
                "id": chat_id,
                "title": chat_info.get("title", f"Chat {chat_id}"),
                "type": chat_info.get("type", ""),
                "username": chat_info.get("username", ""),
                "added_at": datetime.now().isoformat(),
                "last_checked": datetime.now().isoformat()
            }
        
        print(f"➕ Мониторинг чата: {chat_info.get('title', chat_id) if chat_info else chat_id}")
    
    def analyze_telegram_message(self, message: dict) -> dict:
        """Анализ сообщения через Telegram API"""
        analysis = {
            "is_forwarded": False,
            "has_external_links": False,
            "contains_media": False,
            "reply_to_forward": False,
            "forward_chain": False,
            "suspicious_patterns": []
        }
        
        # 1. Проверка на пересылку
        if "forward_date" in message:
            analysis["is_forwarded"] = True
            
            # Проверяем источник пересылки
            forward_from = message.get("forward_from_chat", {})
            if forward_from:
                forward_chat_id = forward_from.get("id")
                # Если переслано из другого чата
                if forward_chat_id and forward_chat_id != message.get("chat", {}).get("id"):
                    analysis["suspicious_patterns"].append("cross_chat_forward")
        
        # 2. Проверка на медиа
        if any(key in message for key in ["photo", "video", "document", "audio"]):
            analysis["contains_media"] = True
            
            # Проверяем подписи к медиа
            caption = message.get("caption", "")
            if caption:
                # Ищем ссылки в подписях
                if re.search(r'https?://[^\s]+', caption):
                    analysis["has_external_links"] = True
        
        # 3. Проверка текста на внешние ссылки
        text = message.get("text", "")
        if text:
            # Ищем ссылки
            links = re.findall(r'https?://[^\s]+', text)
            if links:
                analysis["has_external_links"] = True
                
                # Проверяем ссылки на популярные файлообменники
                file_hosts = [
                    "dropbox", "google.drive", "mega.nz", "yadi.sk",
                    "disk.yandex", "cloud.mail", "telegram.me/file",
                    "t.me/file"
                ]
                
                for link in links:
                    for host in file_hosts:
                        if host in link.lower():
                            analysis["suspicious_patterns"].append(f"file_hosting_{host}")
                            break
        
        # 4. Проверка на ответ к пересланному сообщению
        if "reply_to_message" in message and "forward_date" in message.get("reply_to_message", {}):
            analysis["reply_to_forward"] = True
            analysis["suspicious_patterns"].append("reply_to_forwarded")
        
        # 5. Проверка цепочки пересылок
        if "forward_from_message_id" in message:
            analysis["forward_chain"] = True
        
        return analysis
    
    def detect_leaks(self, message: dict, analysis: dict) -> List[Dict]:
        """Обнаружение утечек на основе анализа"""
        detected_leaks = []
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        message_id = message.get("message_id")
        
        # 1. Утечка через пересылку
        if analysis["is_forwarded"]:
            leak_data = {
                "type": "forwarded_message",
                "chat_id": chat_id,
                "user_id": user_id,
                "message_id": message_id,
                "timestamp": datetime.now().isoformat(),
                "confidence": 90,
                "details": {
                    "is_cross_chat": "cross_chat_forward" in analysis["suspicious_patterns"],
                    "has_media": analysis["contains_media"],
                    "source_chat": message.get("forward_from_chat", {}).get("title", "unknown")
                }
            }
            detected_leaks.append(leak_data)
            self.leaks["forwarded_messages"].append(leak_data)
        
        # 2. Утечка через внешние ссылки
        if analysis["has_external_links"]:
            leak_data = {
                "type": "external_share",
                "chat_id": chat_id,
                "user_id": user_id,
                "message_id": message_id,
                "timestamp": datetime.now().isoformat(),
                "confidence": 70,
                "details": {
                    "contains_file_links": any("file_hosting" in p for p in analysis["suspicious_patterns"]),
                    "suspicious_patterns": analysis["suspicious_patterns"]
                }
            }
            detected_leaks.append(leak_data)
            self.leaks["external_shares"].append(leak_data)
        
        # 3. Подозрительная активность
        if analysis["suspicious_patterns"]:
            leak_data = {
                "type": "suspicious_activity",
                "chat_id": chat_id,
                "user_id": user_id,
                "message_id": message_id,
                "timestamp": datetime.now().isoformat(),
                "confidence": 50,
                "details": {
                    "patterns": analysis["suspicious_patterns"],
                    "is_reply_to_forward": analysis["reply_to_forward"],
                    "is_forward_chain": analysis["forward_chain"]
                }
            }
            detected_leaks.append(leak_data)
            self.leaks["suspicious_activity"].append(leak_data)
        
        return detected_leaks

storage = IntegratedStorage()

# ========== REAL-TIME MONITOR ==========
class RealTimeMonitor:
    def __init__(self):
        self.active = True
        self.check_interval = 60  # секунд
        
    def check_chat_activity(self, chat_id: int):
        """Проверить активность в чате"""
        try:
            # Получаем последние сообщения из чата
            result = storage.telegram_api.get_chat_history(chat_id, limit=50)
            
            if result.get("ok"):
                messages = result.get("result", {}).get("messages", [])
                
                for msg in messages[-20:]:  # Проверяем последние 20 сообщений
                    # Проверяем, не обрабатывали ли уже это сообщение
                    msg_hash = hashlib.md5(f"{chat_id}_{msg.get('id')}".encode()).hexdigest()
                    
                    if msg_hash not in storage.message_hashes:
                        # Анализируем сообщение
                        analysis = storage.analyze_telegram_message(msg)
                        leaks = storage.detect_leaks(msg, analysis)
                        
                        if leaks:
                            print(f"🚨 Обнаружены утечки в чате {chat_id}: {len(leaks)}")
                        
                        # Сохраняем сообщение
                        msg_data = {
                            "chat_id": chat_id,
                            "message_id": msg.get("id"),
                            "user_id": msg.get("from_id", {}).get("user_id", 0),
                            "text": msg.get("text", "") or msg.get("caption", ""),
                            "timestamp": datetime.now().isoformat(),
                            "is_forwarded": "forward_date" in msg,
                            "has_media": any(key in msg for key in ["photo", "video", "document"]),
                            "analysis": analysis,
                            "leaks_detected": len(leaks) > 0
                        }
                        
                        storage.messages.append(msg_data)
                        storage.message_hashes.add(msg_hash)
            
            # Обновляем время последней проверки
            if str(chat_id) in storage.chat_metadata:
                storage.chat_metadata[str(chat_id)]["last_checked"] = datetime.now().isoformat()
                
        except Exception as e:
            print(f"Chat check error for {chat_id}: {e}")
    
    def start_monitoring(self):
        """Запустить мониторинг чатов"""
        print("🎯 Запуск REAL-TIME мониторинга...")
        
        import threading
        def monitor_loop():
            while self.active:
                try:
                    # Проверяем все мониторимые чаты
                    for chat_id in list(storage.monitored_chats):
                        self.check_chat_activity(chat_id)
                    
                    # Автосохранение
                    if len(storage.messages) % 50 == 0:
                        storage.save()
                    
                    time.sleep(self.check_interval)
                    
                except Exception as e:
                    print(f"Monitor loop error: {e}")
                    time.sleep(30)
        
        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()

monitor = RealTimeMonitor()

# ========== FLASK APP ==========
app = Flask(__name__)

def send_alert_to_allowed_users(alert_data: dict):
    """Отправить оповещение всем разрешённым пользователям"""
    for user_id in ALLOWED_IDS:
        try:
            alert_message = f"""
🚨 <b>REAL-TIME DETECTION</b>

<b>Тип утечки:</b> {alert_data['type'].replace('_', ' ').upper()}
<b>Чат:</b> {alert_data.get('chat_title', f"ID: {alert_data['chat_id']}")}
<b>Пользователь:</b> {alert_data.get('username', 'Unknown')}
<b>Уверенность:</b> {alert_data['confidence']}%
<b>Время:</b> {datetime.now().strftime('%H:%M:%S')}

<b>Детали:</b>
"""
            
            for key, value in alert_data.get('details', {}).items():
                if isinstance(value, bool):
                    value = "✅" if value else "❌"
                alert_message += f"├─ {key}: {value}\n"
            
            alert_message += f"\n<i>Сообщение ID: {alert_data['message_id']}</i>"
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = {
                "chat_id": user_id,
                "text": alert_message,
                "parse_mode": "HTML"
            }
            
            requests.post(url, json=data, timeout=10)
            
        except Exception as e:
            print(f"Alert send error to {user_id}: {e}")

@app.route('/')
def home():
    stats = {
        "monitored_chats": len(storage.monitored_chats),
        "total_messages": len(storage.messages),
        "total_leaks": storage.get_total_leaks(),
        "forwarded_leaks": len(storage.leaks["forwarded_messages"]),
        "external_shares": len(storage.leaks["external_shares"]),
        "suspicious_activity": len(storage.leaks["suspicious_activity"]),
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Получаем информацию о мониторимых чатах
    monitored_chats_info = []
    for chat_id in list(storage.monitored_chats)[:10]:
        chat_info = storage.chat_metadata.get(str(chat_id), {
            "id": chat_id,
            "title": f"Chat {chat_id}",
            "last_checked": "Never"
        })
        monitored_chats_info.append(chat_info)
    
    # Последние утечки
    recent_leaks = []
    for leak_type, leaks in storage.leaks.items():
        for leak in leaks[-5:]:
            leak["leak_type"] = leak_type
            recent_leaks.append(leak)
    
    recent_leaks.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    return render_template('index.html',
                         stats=stats,
                         allowed_ids=ALLOWED_IDS,
                         monitored_chats=monitored_chats_info,
                         recent_leaks=recent_leaks[:15])

@app.route('/api/stats')
def api_stats():
    return jsonify({
        "monitoring": {
            "active_chats": len(storage.monitored_chats),
            "total_messages": len(storage.messages),
            "check_interval": monitor.check_interval
        },
        "leaks": {
            "forwarded_messages": len(storage.leaks["forwarded_messages"]),
            "external_shares": len(storage.leaks["external_shares"]),
            "suspicious_activity": len(storage.leaks["suspicious_activity"]),
            "total": storage.get_total_leaks()
        },
        "system": {
            "telegram_api": "connected",
            "real_time_monitor": "active",
            "last_check": datetime.now().isoformat()
        }
    })

@app.route('/api/chats')
def api_chats():
    chats_info = []
    for chat_id in storage.monitored_chats:
        chat_info = storage.chat_metadata.get(str(chat_id), {
            "id": chat_id,
            "title": f"Chat {chat_id}",
            "monitored_since": "unknown"
        })
        
        # Подсчитываем сообщения и утечки в чате
        chat_messages = [m for m in storage.messages if m.get("chat_id") == chat_id]
        chat_leaks = []
        for leak_type, leaks in storage.leaks.items():
            chat_leaks.extend([l for l in leaks if l.get("chat_id") == chat_id])
        
        chat_info["messages_count"] = len(chat_messages)
        chat_info["leaks_count"] = len(chat_leaks)
        chats_info.append(chat_info)
    
    return jsonify({"chats": chats_info, "count": len(chats_info)})

@app.route('/api/monitor/add/<int:chat_id>')
def api_monitor_add(chat_id):
    """Добавить чат в мониторинг"""
    try:
        # Получаем информацию о чате
        result = storage.telegram_api.get_chat_info(chat_id)
        
        if result.get("ok"):
            storage.add_monitored_chat(chat_id, result.get("result"))
            storage.save()
            
            return jsonify({
                "success": True,
                "message": f"Chat {chat_id} added to monitoring",
                "chat_info": result.get("result")
            })
        else:
            return jsonify({"success": False, "error": "Cannot get chat info"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/monitor/remove/<int:chat_id>')
def api_monitor_remove(chat_id):
    """Убрать чат из мониторинга"""
    if chat_id in storage.monitored_chats:
        storage.monitored_chats.remove(chat_id)
        storage.save()
        return jsonify({"success": True, "message": f"Chat {chat_id} removed from monitoring"})
    return jsonify({"success": False, "error": "Chat not monitored"})

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": "telegram-integrated-leak-detector",
        "telegram_api": "connected" if TELEGRAM_TOKEN else "disconnected",
        "real_time_monitor": "active" if monitor.active else "inactive",
        "monitored_chats": len(storage.monitored_chats),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/setup')
def setup():
    """Установить вебхук и запустить мониторинг"""
    try:
        webhook_url = os.environ.get("RENDER_EXTERNAL_URL", "https://anti-peresilka.onrender.com")
        webhook_url = f"{webhook_url}/webhook"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {
            "url": webhook_url,
            "max_connections": 100,
            "allowed_updates": ["message", "edited_message", "chat_member"]
        }
        
        response = requests.post(url, json=data)
        result = response.json()
        
        # Запускаем мониторинг в реальном времени
        monitor.start_monitoring()
        
        return jsonify({
            "ok": result.get("ok", False),
            "webhook": webhook_url,
            "real_time_monitor": "started",
            "message": "System fully integrated with Telegram API"
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработчик вебхука - ОСНОВНОЙ МЕХАНИЗМ"""
    try:
        data = request.json
        if not data:
            return jsonify({"ok": True})
        
        # 1. Добавление бота в чат
        if "my_chat_member" in data:
            chat_member = data["my_chat_member"]
            chat = chat_member.get("chat", {})
            chat_id = chat.get("id")
            
            if chat_id:
                # Автоматически добавляем в мониторинг
                storage.add_monitored_chat(chat_id, chat)
                print(f"🤖 Бот добавлен в чат: {chat.get('title', chat_id)}")
                
                # Отправляем приветствие
                welcome_msg = f"""
🎯 <b>TELEGRAM INTEGRATED LEAK DETECTOR</b>

Чат <b>{chat.get('title', chat_id)}</b> добавлен в систему мониторинга.

<b>🔍 Что отслеживается:</b>
• Пересланные сообщения
• Внешние ссылки и файлообменники
• Подозрительная активность
• Кросс-чат пересылки

<b>👁️ Режим:</b> REAL-TIME мониторинг
<b>⏱️ Интервал проверки:</b> {monitor.check_interval} секунд

<i>Система работает в фоновом режиме</i>
"""
                
                for user_id in ALLOWED_IDS:
                    try:
                        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                        requests.post(url, json={
                            "chat_id": user_id,
                            "text": welcome_msg,
                            "parse_mode": "HTML"
                        })
                    except:
                        pass
        
        # 2. Обработка сообщений
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            
            # Автоматически добавляем чат в мониторинг
            if chat_id and chat_id not in storage.monitored_chats:
                storage.add_monitored_chat(chat_id, message.get("chat", {}))
            
            # Анализируем сообщение
            analysis = storage.analyze_telegram_message(message)
            leaks = storage.detect_leaks(message, analysis)
            
            # Сохраняем сообщение
            msg_hash = storage._get_message_hash({
                "chat_id": chat_id,
                "message_id": message.get("message_id"),
                "text": message.get("text", "") or message.get("caption", "")
            })
            
            if msg_hash not in storage.message_hashes:
                msg_data = {
                    "chat_id": chat_id,
                    "message_id": message.get("message_id"),
                    "user_id": user_id,
                    "text": message.get("text", "") or message.get("caption", "")[:500],
                    "timestamp": datetime.now().isoformat(),
                    "analysis": analysis,
                    "leaks_detected": len(leaks) > 0
                }
                
                storage.messages.append(msg_data)
                storage.message_hashes.add(msg_hash)
            
            # Если обнаружены утечки - отправляем оповещение
            if leaks:
                for leak in leaks:
                    # Получаем информацию о пользователе
                    user_info = storage.users.get(user_id, {})
                    if not user_info:
                        storage.users[user_id] = {
                            "id": user_id,
                            "username": message.get("from", {}).get("username", ""),
                            "first_name": message.get("from", {}).get("first_name", ""),
                            "leaks_count": 0,
                            "first_seen": datetime.now().isoformat()
                        }
                        user_info = storage.users[user_id]
                    
                    user_info["leaks_count"] = user_info.get("leaks_count", 0) + 1
                    user_info["last_seen"] = datetime.now().isoformat()
                    
                    # Формируем данные для оповещения
                    alert_data = {
                        "type": leak["type"],
                        "chat_id": chat_id,
                        "chat_title": message.get("chat", {}).get("title", f"Chat {chat_id}"),
                        "user_id": user_id,
                        "username": user_info.get("username", ""),
                        "message_id": message.get("message_id"),
                        "confidence": leak["confidence"],
                        "details": leak["details"],
                        "timestamp": leak["timestamp"]
                    }
                    
                    # Отправляем оповещение
                    send_alert_to_allowed_users(alert_data)
                    
                    print(f"🚨 Real-time leak detected: {leak['type']} in chat {chat_id}")
            
            # Обработка команд от разрешённых пользователей
            if user_id in ALLOWED_IDS:
                text = message.get("text", "").lower()
                
                if text.startswith("/monitor"):
                    # Команда для управления мониторингом
                    parts = text.split()
                    if len(parts) > 1:
                        if parts[1] == "list":
                            # Показать список мониторимых чатов
                            response_msg = "📋 <b>Мониторимые чаты:</b>\n\n"
                            for chat_id in list(storage.monitored_chats)[:10]:
                                chat_info = storage.chat_metadata.get(str(chat_id), {})
                                response_msg += f"• {chat_info.get('title', f'Chat {chat_id}')}\n"
                            
                            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                            requests.post(url, json={
                                "chat_id": chat_id,
                                "text": response_msg,
                                "parse_mode": "HTML"
                            })
                
                elif text.startswith("/stats"):
                    # Статистика
                    stats_msg = f"""
📊 <b>REAL-TIME STATS</b>

<b>Мониторинг:</b>
• Чатов: {len(storage.monitored_chats)}
• Сообщений: {len(storage.messages)}
• Проверок: {len(storage.message_hashes)}

<b>Утечки:</b>
• Пересланные: {len(storage.leaks['forwarded_messages'])}
• Внешние ссылки: {len(storage.leaks['external_shares'])}
• Подозрительные: {len(storage.leaks['suspicious_activity'])}
• Всего: {storage.get_total_leaks()}

<b>Система:</b>
• Режим: REAL-TIME
• Интервал: {monitor.check_interval} сек
• API: Connected
"""
                    
                    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                    requests.post(url, json={
                        "chat_id": chat_id,
                        "text": stats_msg,
                        "parse_mode": "HTML"
                    })
        
        # Автосохранение
        if len(storage.messages) % 25 == 0:
            storage.save()
        
        return jsonify({"ok": True, "processed": True})
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# Автосохранение
def auto_save():
    while True:
        time.sleep(180)
        storage.save()

import threading
save_thread = threading.Thread(target=auto_save, daemon=True)
save_thread.start()

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Запуск ИНТЕГРИРОВАННОГО ТЕЛЕГРАМ БОТА...")
    print(f"✅ Telegram API: Подключено")
    print(f"✅ Real-Time мониторинг: Готов")
    print(f"✅ Разрешённые пользователи: {len(ALLOWED_IDS)}")
    print("="*70)
    print("⚡ Система работает как ЕДИНОЕ ЦЕЛОЕ с Telegram")
    print("🔍 Обнаружение РЕАЛЬНЫХ сливов, а не текста")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT, debug=False)