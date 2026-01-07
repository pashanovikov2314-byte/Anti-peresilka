import os
import json
import time
import re
import hashlib
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import requests
import logging
from typing import Dict, List, Set
import threading

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== ТЕЛЕГРАМ API ==========
class TelegramAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, chat_id, text, parse_mode="HTML"):
        """Отправить сообщение"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if not result.get("ok"):
                logger.error(f"Send message failed: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Send message error: {e}")
            return {"ok": False}
    
    def set_webhook(self, url):
        """Установить вебхук"""
        try:
            webhook_url = f"{self.base_url}/setWebhook"
            data = {
                "url": url,
                "max_connections": 100,
                "allowed_updates": ["message", "edited_message", "channel_post"]
            }
            response = requests.post(webhook_url, json=data)
            result = response.json()
            
            if result.get("ok"):
                logger.info(f"✅ Webhook установлен: {url}")
            else:
                logger.error(f"❌ Webhook ошибка: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return {"ok": False}
    
    def delete_webhook(self):
        """Удалить вебхук"""
        try:
            url = f"{self.base_url}/deleteWebhook"
            response = requests.post(url)
            return response.json()
        except Exception as e:
            logger.error(f"Delete webhook error: {e}")
            return {"ok": False}
    
    def get_me(self):
        """Проверить подключение бота"""
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url)
            return response.json()
        except Exception as e:
            logger.error(f"GetMe error: {e}")
            return {"ok": False}

# ========== МОНИТОРИНГ ==========
class ScreenshotMonitor:
    def __init__(self, token, allowed_ids):
        self.tg = TelegramAPI(token)
        self.allowed_ids = allowed_ids
        self.screenshot_patterns = [
            r'обнаружен[ао]?\s+снимок\s+экрана',
            r'screenshot\s+detected',
            r'скриншот\s+обнаружен',
            r'сделал[аи]?\s+скриншот',
            r'made\s+a\s+screenshot',
            r'снимок\s+экрана\s+сделан'
        ]
        
        # Проверяем бота
        self.check_bot()
    
    def check_bot(self):
        """Проверить доступность бота"""
        result = self.tg.get_me()
        if result.get("ok"):
            bot_info = result["result"]
            logger.info(f"✅ Бот подключен: @{bot_info.get('username')} ({bot_info.get('id')})")
            return True
        else:
            logger.error(f"❌ Бот не доступен: {result.get('description')}")
            return False
    
    def detect_screenshot(self, text):
        """Обнаружить уведомление о скриншоте"""
        if not text:
            return False, None
        
        for pattern in self.screenshot_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True, pattern
        
        return False, None
    
    def extract_user_from_screenshot(self, text):
        """Извлечь пользователя из уведомления о скриншоте"""
        patterns = [
            r'@(\w+)\s+сделал',
            r'@(\w+)\s+made',
            r'пользователь\s+@(\w+)',
            r'user\s+@(\w+)',
            r'(\w+)\s+сделал\s+скриншот'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return "Неизвестно"
    
    def send_alert(self, alert_data):
        """Отправить оповещение всем админам"""
        alert_type = alert_data.get("type", "unknown")
        
        if alert_type == "screenshot":
            message = f"""
🚨 <b>СКРИНШОТ ОБНАРУЖЕН</b>

<b>👤 Пользователь:</b> @{alert_data.get('username', 'Неизвестно')}
<b>🆔 ID:</b> {alert_data.get('user_id', 'N/A')}
<b>💬 Чат:</b> {alert_data.get('chat_title', f"ID: {alert_data.get('chat_id', 'N/A')}")}
<b>🕒 Время:</b> {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}

<b>📝 Уведомление:</b>
{alert_data.get('notification_text', '')[:200]}

<i>⚠️ Пользователь сделал скриншот сообщения</i>
"""
        
        elif alert_type == "forward":
            destination = "личные сообщения" if alert_data.get("is_to_pm") else "другой чат"
            message = f"""
⚠️ <b>ПЕРЕСЫЛКА ОБНАРУЖЕНА</b>

<b>👤 Пользователь:</b> @{alert_data.get('username', 'Неизвестно')}
<b>🆔 ID:</b> {alert_data.get('user_id', 'N/A')}
<b>📨 Направление:</b> {destination}
<b>💬 Исходный чат:</b> {alert_data.get('chat_title', f"ID: {alert_data.get('chat_id', 'N/A')}")}
<b>🕒 Время:</b> {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}

<b>📄 Содержимое:</b>
{alert_data.get('message_content', '')[:150]}

<i>⚠️ Сообщение было переслано из защищённого чата</i>
"""
        
        else:
            message = f"""
⚠️ <b>ПОДОЗРИТЕЛЬНАЯ АКТИВНОСТЬ</b>

<b>Тип:</b> {alert_type}
<b>Пользователь:</b> @{alert_data.get('username', 'Неизвестно')}
<b>Время:</b> {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}
"""
        
        # Отправляем всем админам
        success_count = 0
        for admin_id in self.allowed_ids:
            try:
                result = self.tg.send_message(admin_id, message)
                if result.get("ok"):
                    success_count += 1
                    logger.info(f"✅ Оповещение отправлено админу {admin_id}")
                else:
                    logger.error(f"❌ Ошибка отправки админу {admin_id}: {result}")
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin_id}: {e}")
        
        logger.info(f"📤 Отправлено {success_count}/{len(self.allowed_ids)} оповещений")
        return success_count > 0

# ========== FLASK APP ==========
app = Flask(__name__)
telegram = TelegramAPI(TELEGRAM_TOKEN)
monitor = ScreenshotMonitor(TELEGRAM_TOKEN, ALLOWED_IDS)

# ========== ВАЖНО: ВЕБХУК ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной обработчик вебхука"""
    try:
        update = request.json
        
        # Логируем входящий запрос
        logger.info(f"📥 Получен вебхук: {json.dumps(update, ensure_ascii=False)[:200]}...")
        
        # Проверяем наличие сообщения
        if 'message' not in update:
            logger.info("Сообщение не найдено в update")
            return jsonify({"ok": True})
        
        message = update['message']
        chat = message.get('chat', {})
        user = message.get('from', {})
        
        chat_id = chat.get('id')
        user_id = user.get('id')
        username = user.get('username', '')
        first_name = user.get('first_name', '')
        text = message.get('text', '') or message.get('caption', '')
        
        logger.info(f"💬 Сообщение от @{username} ({user_id}) в чате {chat_id}: {text[:50]}...")
        
        # 1. Проверяем скриншоты
        is_screenshot, pattern = monitor.detect_screenshot(text)
        if is_screenshot:
            logger.info(f"📸 Обнаружен скриншот: {pattern}")
            
            # Извлекаем пользователя
            screenshot_user = monitor.extract_user_from_screenshot(text)
            
            # Отправляем оповещение
            alert_data = {
                "type": "screenshot",
                "user_id": user_id,
                "username": screenshot_user,
                "chat_id": chat_id,
                "chat_title": chat.get('title', f"Chat {chat_id}"),
                "notification_text": text,
                "pattern": pattern
            }
            
            monitor.send_alert(alert_data)
        
        # 2. Проверяем пересылки
        elif 'forward_from_chat' in message or 'forward_from' in message:
            logger.info(f"📨 Обнаружена пересылка от @{username}")
            
            is_to_pm = chat.get('type') == 'private'
            message_content = text[:150] if text else "Медиа-сообщение"
            
            alert_data = {
                "type": "forward",
                "user_id": user_id,
                "username": username or first_name,
                "chat_id": chat_id,
                "chat_title": chat.get('title', f"Chat {chat_id}"),
                "is_to_pm": is_to_pm,
                "message_content": message_content,
                "forward_from": message.get('forward_from_chat', {}).get('title', 'Неизвестно')
            }
            
            monitor.send_alert(alert_data)
        
        # 3. Проверяем команды от админов
        elif user_id in ALLOWED_IDS and text.startswith('/'):
            logger.info(f"⚡ Команда от админа: {text}")
            
            if text == '/start':
                welcome_msg = """
👮 <b>TELEGRAM MONITOR PRO</b>

<b>Система мониторинга активна!</b>

📊 <b>Команды:</b>
/status - статус системы
/stats - статистика
/monitor - информация о мониторинге
/help - помощь

🔍 <b>Отслеживается:</b>
• Скриншоты сообщений
• Пересылки в другие чаты/ЛС
• Подозрительная активность

⚡ <b>Режим:</b> Реальное время
"""
                telegram.send_message(user_id, welcome_msg)
            
            elif text == '/status':
                status_msg = f"""
📊 <b>СТАТУС СИСТЕМЫ</b>

✅ <b>Бот:</b> Активен
✅ <b>Вебхук:</b> Настроен
✅ <b>Мониторинг:</b> Включён
👮 <b>Админы:</b> {len(ALLOWED_IDS)}
🕒 <b>Время:</b> {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}

<i>Система работает в штатном режиме</i>
"""
                telegram.send_message(user_id, status_msg)
            
            elif text == '/help':
                help_msg = """
❓ <b>ПОМОЩЬ ПО СИСТЕМЕ</b>

<b>Как работает система:</b>
1. Добавьте бота в чат как администратора
2. Бот автоматически начнёт мониторинг
3. При обнаружении скриншота или пересылки вы получите оповещение

<b>Что отслеживается:</b>
• Уведомления "Пользователь @username сделал скриншот"
• Пересылки сообщений в другие чаты
• Пересылки в личные сообщения

<b>Настройки:</b>
• ID админов задаются в переменной ALLOWED_IDS
• Все оповещения приходят в ЛС

<b>Поддержка:</b>
Система работает автоматически 24/7
"""
                telegram.send_message(user_id, help_msg)
        
        return jsonify({"ok": True})
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500

# ========== НАСТРОЙКА ВЕБХУКА ==========
@app.route('/setup', methods=['GET'])
def setup_webhook():
    """Настроить вебхук"""
    try:
        # Получаем текущий URL
        if request.headers.get('X-Forwarded-Proto') == 'https':
            base_url = f"https://{request.host}"
        else:
            base_url = f"http://{request.host}"
        
        webhook_url = f"{base_url}/webhook"
        
        logger.info(f"🌐 Настройка вебхука на URL: {webhook_url}")
        
        # Устанавливаем вебхук
        result = telegram.set_webhook(webhook_url)
        
        if result.get("ok"):
            success_msg = f"""
✅ <b>ВЕБХУК УСПЕШНО НАСТРОЕН</b>

<b>URL:</b> {webhook_url}
<b>Статус:</b> Активен
<b>Время:</b> {datetime.now().strftime('%H:%M:%S')}

<i>Система готова к приёму уведомлений</i>
"""
            
            # Отправляем сообщение админам
            for admin_id in ALLOWED_IDS:
                try:
                    telegram.send_message(admin_id, success_msg)
                except Exception as e:
                    logger.error(f"Ошибка отправки админу {admin_id}: {e}")
            
            return jsonify({
                "success": True,
                "webhook_url": webhook_url,
                "message": "Webhook configured successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("description", "Unknown error")
            }), 500
            
    except Exception as e:
        logger.error(f"Ошибка настройки вебхука: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ========== ПРОВЕРКА ВЕБХУКА ==========
@app.route('/check_webhook', methods=['GET'])
def check_webhook():
    """Проверить состояние вебхука"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo"
        response = requests.get(url)
        result = response.json()
        
        return jsonify({
            "webhook_info": result,
            "bot_token_exists": bool(TELEGRAM_TOKEN),
            "allowed_users": ALLOWED_IDS,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== ТЕСТОВЫЙ ВЕБХУК ==========
@app.route('/test_webhook', methods=['POST'])
def test_webhook():
    """Тестовый вебхук для отладки"""
    test_data = {
        "update_id": 100000000,
        "message": {
            "message_id": 1,
            "from": {
                "id": 123456789,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
                "language_code": "ru"
            },
            "chat": {
                "id": -1001234567890,
                "title": "Test Chat",
                "type": "supergroup"
            },
            "date": int(time.time()),
            "text": "Пользователь @username сделал снимок экрана"
        }
    }
    
    # Эмулируем запрос
    with app.test_client() as client:
        response = client.post('/webhook', json=test_data)
    
    return jsonify({
        "test_sent": True,
        "response": response.json,
        "test_data": test_data
    })

# ========== ВЕБ-ИНТЕРФЕЙС ==========
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stats')
def api_stats():
    return jsonify({
        "total_screenshots": 0,  # Заглушка - нужно реализовать БД
        "total_forwards": 0,
        "monitored_chats": 0,
        "suspicious_users": 0,
        "last_update": datetime.now().isoformat(),
        "bot_status": "active",
        "webhook_status": "configured",
        "allowed_admins": len(ALLOWED_IDS)
    })

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("🚀 ЗАПУСК TELEGRAM MONITOR PRO")
    logger.info("=" * 70)
    logger.info(f"🤖 Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
    logger.info(f"👮 Allowed IDs: {ALLOWED_IDS}")
    logger.info(f"🌐 Port: {PORT}")
    logger.info("=" * 70)
    
    # Проверяем бота
    bot_check = telegram.get_me()
    if bot_check.get("ok"):
        bot_info = bot_check["result"]
        logger.info(f"✅ Бот: @{bot_info.get('username')} (ID: {bot_info.get('id')})")
    else:
        logger.error(f"❌ Ошибка бота: {bot_check.get('description')}")
    
    # Автоматическая настройка вебхука при запуске
    try:
        if "RENDER" in os.environ or "HEROKU" in os.environ:
            logger.info("🌍 Обнаружено облачное окружение")
            time.sleep(2)  # Ждём запуск сервера
    except:
        pass
    
    app.run(host="0.0.0.0", port=PORT, debug=False)