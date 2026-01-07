import logging
import re
import time
import threading
import requests
from datetime import datetime
from flask import Flask
import json
import os
import sys

# ========== ЗАГЛУШКА ДЛЯ IMGHDR ==========
class ImghdrStub:
    def what(self, file, h=None):
        return None

sys.modules['imghdr'] = ImghdrStub()

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", 5000))

SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 600))
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не установлен")
if not ALLOWED_USER_IDS:
    raise ValueError("ALLOWED_IDS не установлен")

app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== ПРОСТОЙ БОТ БЕЗ СЛОЖНЫХ ЗАВИСИМОСТЕЙ ==========
class SimpleTelegramBot:
    def __init__(self):
        self.bot_start_time = datetime.now()
        self.leaks_by_user = {}
        self.user_info = {}
        self.ping_count = 0
        self.last_successful_ping = None
        self.self_ping_enabled = True
        self.is_running = True
        
        self.skillup_ultra_mode = False
        self.ultra_detection_level = 5
        
        self.load_data()
        self.start_background_tasks()
        self.setup_flask_endpoints()
        
        logger.info("🤖 Простой бот инициализирован")

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
                "leak_count": sum(len(v) for v in self.leaks_by_user.values()),
                "user_count": len(self.user_info),
                "skillup_ultra": self.skillup_ultra_mode
            }
        
        @app.route('/ping')
        def ping():
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            return {"status": "pong", "ping_number": self.ping_count}
        
        @app.route('/api/leak/<int:user_id>', methods=['POST'])
        def report_leak(user_id):
            try:
                data = request.json
                if not data:
                    return {"error": "No data"}, 400
                
                leak_info = {
                    'type': data.get('type', 'UNKNOWN'),
                    'details': data.get('details', ''),
                    'timestamp': datetime.now().isoformat(),
                    'chat_id': data.get('chat_id', 0),
                    'chat_title': data.get('chat_title', 'Unknown'),
                    'message_id': data.get('message_id', 0),
                    'detection_mode': data.get('detection_mode', 'NORMAL')
                }
                
                if user_id not in self.leaks_by_user:
                    self.leaks_by_user[user_id] = []
                
                self.leaks_by_user[user_id].append(leak_info)
                
                if len(self.leaks_by_user[user_id]) > 50:
                    self.leaks_by_user[user_id] = self.leaks_by_user[user_id][-50:]
                
                self.save_data()
                logger.info(f"📨 Получена утечка от пользователя {user_id}: {leak_info['type']}")
                
                # Отправка уведомления админам (через Telegram API напрямую)
                self.send_leak_alert_to_admins(user_id, leak_info)
                
                return {"status": "success", "leak_id": len(self.leaks_by_user[user_id])}
                
            except Exception as e:
                logger.error(f"❌ Ошибка обработки утечки: {e}")
                return {"error": str(e)}, 500
    
    def start_background_tasks(self):
        def self_ping_task():
            while self.is_running:
                if self.self_ping_enabled and RENDER_URL:
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
            response = requests.get(f"{RENDER_URL}/ping", timeout=15)
            if response.status_code == 200:
                self.ping_count += 1
                self.last_successful_ping = datetime.now()
                
                if self.ping_count % 50 == 0:
                    logger.info(f"✅ Самопинг #{self.ping_count} выполнен")
                    
        except Exception as e:
            logger.warning(f"⚠️ Ошибка самопинга: {str(e)[:100]}")

    def send_leak_alert_to_admins(self, user_id, leak_info):
        """Отправка уведомления админам напрямую через Telegram Bot API"""
        try:
            user = self.user_info.get(user_id, {'username': f'id{user_id}', 'first_name': ''})
            
            mode_icon = "🔥" if leak_info.get('detection_mode') == 'ULTRA' else "⚠️"
            alert = f"{mode_icon} ОБНАРУЖЕНА УТЕЧКА\n\n"
            alert += f"👤 Нарушитель: @{user['username']}\n"
            alert += f"📛 Имя: {user['first_name']}\n"
            alert += f"🆔 ID: {user_id}\n\n"
            alert += f"📊 Тип: {leak_info['type']}\n"
            alert += f"📝 Детали: {leak_info['details']}\n"
            alert += f"⏰ Время: {leak_info['timestamp'][11:16]}\n"
            alert += f"💬 Чат: {leak_info['chat_title']}\n"
            
            if leak_info.get('detection_score'):
                alert += f"🎯 Оценка: {leak_info['detection_score']}/100\n"
            
            alert += f"📈 Всего утечек от этого пользователя: {len(self.leaks_by_user.get(user_id, []))}"
            
            # Отправка каждому админу через Telegram API
            for admin_id in ALLOWED_USER_IDS:
                try:
                    telegram_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                    payload = {
                        'chat_id': admin_id,
                        'text': alert,
                        'parse_mode': 'Markdown',
                        'disable_web_page_preview': True
                    }
                    
                    response = requests.post(telegram_url, json=payload, timeout=10)
                    if response.status_code == 200:
                        logger.info(f"📨 Отправлено оповещение админу {admin_id}")
                    else:
                        logger.error(f"❌ Ошибка отправки админу {admin_id}: {response.text}")
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка формирования уведомления: {e}")

    def save_data(self):
        try:
            data = {
                'leaks_by_user': {str(k): v for k, v in self.leaks_by_user.items()},
                'user_info': {str(k): v for k, v in self.user_info.items()},
                'ping_count': self.ping_count,
                'skillup_ultra_mode': self.skillup_ultra_mode
            }
            
            with open('bot_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")

    def load_data(self):
        try:
            if os.path.exists('bot_data.json'):
                with open('bot_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.leaks_by_user = {int(k): v for k, v in data.get('leaks_by_user', {}).items()}
                self.user_info = {int(k): v for k, v in data.get('user_info', {}).items()}
                self.ping_count = data.get('ping_count', 0)
                self.skillup_ultra_mode = data.get('skillup_ultra_mode', False)
                
                logger.info(f"✅ Данные загружены: {len(self.leaks_by_user)} пользователей с утечками")
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")

def main():
    bot = SimpleTelegramBot()
    
    # Запуск Flask
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False
    )

if __name__ == '__main__':
    main()
