# Исправленные импорты (добавить в начало)
import secrets  # Добавить эту строку
from flask import Flask, request  # Добавить для web-интерфейса

# Исправление строки 9:
API_KEY = os.environ.get("API_KEY", secrets.token_hex(16) if 'secrets' in dir() else "default_api_key_123456")

# Исправление метода _send_immediate_alert:
def _send_immediate_alert(self, user_id: int, leak_info: Dict):
    """Немедленное уведомление админов"""
    alert_msg = f"""
⚠️ **УТЕЧКА ОБНАРУЖЕНА**

👤 **Пользователь:** @{leak_info.get('username', f'id{user_id}')}
📊 **Тип:** {leak_info.get('type')}
🎯 **Риск:** {leak_info.get('risk_score')}/100
💬 **Чат:** {leak_info.get('chat_title')}
⏰ **Время:** {datetime.now().strftime('%H:%M:%S')}

📝 **Детали:** {leak_info.get('details', '')[:100]}

📍 **ID сообщения:** {leak_info.get('message_id')}
    """
    
    for admin_id in ALLOWED_USER_IDS:
        try:
            # Используем self.updater.bot вместо context.bot
            self.updater.bot.send_message(
                chat_id=admin_id,
                text=alert_msg,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            logger.info(f"📨 Immediate alert sent to admin {admin_id}")
        except Exception as e:
            logger.error(f"❌ Alert error for {admin_id}: {e}")
