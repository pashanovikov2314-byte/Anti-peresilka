import logging
import re
import json
import time
import requests
import asyncio
from datetime import datetime
from typing import Dict, Optional
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import sys

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
API_KEY = os.environ.get("API_KEY", secrets.token_hex(16))

# Режимы работы
ENABLE_ADVANCED_DETECTION = True
ENABLE_REAL_TIME_ALERTS = True
ENABLE_AI_ANALYSIS = True

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class QuantumTelegramListener:
    """Квантовый Telegram листенер с расширенной детекцией"""
    
    def __init__(self):
        self.updater = Updater(TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher
        
        # Кэш пользователей
        self.user_cache = {}
        self.message_cache = {}
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'leaks_detected': 0,
            'users_monitored': 0,
            'api_calls': 0
        }
        
        # Регистрация обработчиков
        self._register_handlers()
        
        logger.info("🔮 Quantum Telegram Listener инициализирован")
    
    def _register_handlers(self):
        """Регистрация всех обработчиков"""
        # Команды админов
        self.dispatcher.add_handler(CommandHandler("start", self.command_start))
        self.dispatcher.add_handler(CommandHandler("help", self.command_help))
        self.dispatcher.add_handler(CommandHandler("stats", self.command_stats))
        self.dispatcher.add_handler(CommandHandler("status", self.command_status))
        self.dispatcher.add_handler(CommandHandler("scan", self.command_scan))
        self.dispatcher.add_handler(CommandHandler("analyze", self.command_analyze))
        self.dispatcher.add_handler(CommandHandler("monitor", self.command_monitor))
        self.dispatcher.add_handler(CommandHandler("config", self.command_config))
        
        # Обработчик всех сообщений
        self.dispatcher.add_handler(MessageHandler(
            Filters.all & ~Filters.command, 
            self.handle_message
        ))
    
    def command_start(self, update: Update, context: CallbackContext):
        """Команда /start"""
        user_id = update.effective_user.id
        
        if user_id not in ALLOWED_USER_IDS:
            update.message.reply_text("❌ Доступ запрещен.")
            return
        
        welcome = """
🚀 **Quantum LeakTracker v3.0**

🔐 *Система мониторинга утечек с ИИ*

**Доступные команды:**
/help - Полная справка
/stats - Статистика системы
/status - Статус мониторинга
/scan - Сканирование сообщения
/analyze - Анализ пользователя
/monitor - Управление мониторингом
/config - Настройки

📊 **Веб-интерфейс:** """ + RENDER_URL + """

🤖 *Бот работает в фоновом режиме*
*Все утечки отправляются админам автоматически*
        """
        
        update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)
    
    def command_help(self, update: Update, context: CallbackContext):
        """Команда /help"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        help_text = """
📖 **Quantum LeakTracker - Справка**

**Основные функции:**
• Автоматический мониторинг чатов
• AI-детекция утечек в реальном времени
• Расширенный анализ текста
• Поведенческий анализ
• Уведомления в реальном времени

**Что детектирует система:**
1. **Финансовые данные:** карты, счета, реквизиты
2. **Персональные данные:** паспорта, снилсы, права
3. **Конфиденциальная информация:** секреты, договоры
4. **Криптоданные:** кошельки, приватные ключи
5. **Учетные данные:** логины, пароли, токены
6. **Код и конфигурации:** исходный код, настройки
7. **Сетевые данные:** IP, порты, доступы

**Уровни угроз:**
🚨 CRITICAL (80-100) - Немедленные действия
⚠️ HIGH (60-79) - Приоритетное расследование
🔶 MEDIUM (40-59) - Детальный анализ
🔶 LOW (20-39) - Мониторинг
✅ MINIMAL (0-19) - Рутовая проверка

**Для анализа сообщения:**
/scan [текст] - AI анализ текста
/analyze @username - Анализ пользователя

**Веб-интерфейс:** """ + RENDER_URL + """
        """
        
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    def command_stats(self, update: Update, context: CallbackContext):
        """Команда /stats - статистика"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        try:
            # Запрос статистики с сервера
            response = requests.get(
                f"{RENDER_URL}/api/v1/stats",
                headers={'X-API-Key': API_KEY},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                stats_text = f"""
📊 **Системная статистика**

**Основные метрики:**
• Всего утечек: {data.get('metrics', {}).get('total_leaks', 0)}
• AI анализов: {data.get('metrics', {}).get('ai_analyses', 0)}
• Заблокировано угроз: {data.get('metrics', {}).get('threats_blocked', 0)}

**Распределение по рискам:**
• Критические: {data.get('distributions', {}).get('risk', {}).get('CRITICAL', 0)}
• Высокие: {data.get('distributions', {}).get('risk', {}).get('HIGH', 0)}
• Средние: {data.get('distributions', {}).get('risk', {}).get('MEDIUM', 0)}
• Низкие: {data.get('distributions', {}).get('risk', {}).get('LOW', 0)}

**Локальная статистика:**
• Обработано сообщений: {self.stats['messages_processed']}
• Обнаружено утечек: {self.stats['leaks_detected']}
• Мониторится пользователей: {self.stats['users_monitored']}

**Статус системы:**
• Аптайм: {int(data.get('system', {}).get('uptime', 0) / 3600)} ч.
• Уровень безопасности: {data.get('system', {}).get('security_level', 0)}/10
• Размер кэша: {data.get('cache_status', {}).get('size', 0)}
                """
                
                update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
            else:
                update.message.reply_text("❌ Ошибка получения статистики")
                
        except Exception as e:
            logger.error(f"Stats error: {e}")
            update.message.reply_text("❌ Ошибка соединения с сервером")
    
    def command_status(self, update: Update, context: CallbackContext):
        """Команда /status - статус"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        status_text = f"""
🔄 **Статус мониторинга**

**Режимы работы:**
• Расширенная детекция: {'🟢 ВКЛ' if ENABLE_ADVANCED_DETECTION else '🔴 ВЫКЛ'}
• Уведомления в реальном времени: {'🟢 ВКЛ' if ENABLE_REAL_TIME_ALERTS else '🔴 ВЫКЛ'}
• AI анализ: {'🟢 ВКЛ' if ENABLE_AI_ANALYSIS else '🔴 ВЫКЛ'}

**Конфигурация:**
• Сервер: {'🟢 ONLINE' if RENDER_URL else '🔴 OFFLINE'}
• Админов: {len(ALLOWED_USER_IDS)}
• API ключ: {'🟢 УСТАНОВЛЕН' if API_KEY else '🔴 ОТСУТСТВУЕТ'}

**Последняя активность:**
• Сообщений обработано: {self.stats['messages_processed']}
• Утечек обнаружено: {self.stats['leaks_detected']}

**Веб-интерфейс:** {RENDER_URL or 'Не настроен'}
        """
        
        update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
    
    def command_scan(self, update: Update, context: CallbackContext):
        """Команда /scan - сканирование текста"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        if not context.args:
            update.message.reply_text("❌ Укажите текст для анализа: /scan [текст]")
            return
        
        text = ' '.join(context.args)
        
        try:
            # Отправка на анализ
            response = requests.post(
                f"{RENDER_URL}/api/v1/analyze",
                json={
                    'text': text,
                    'user_id': user_id,
                    'context': {'source': 'manual_scan'}
                },
                headers={'X-API-Key': API_KEY},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                
                result_text = f"""
🔍 **Результаты анализа**

**Идентификатор:** `{data.get('analysis_id', 'N/A')}`
**Уровень риска:** {data.get('combined_risk', 0)}/100
**Рекомендация:** {data.get('recommendation', 'N/A')}

**Детекции:**
"""
                
                # Добавление детекций
                detections = data.get('quantum_analysis', {}).get('detections', [])
                if detections:
                    for i, det in enumerate(detections[:5], 1):
                        result_text += f"{i}. {det.get('category', 'UNKNOWN')} (уверенность: {det.get('confidence', 0)}%)\n"
                
                if len(detections) > 5:
                    result_text += f"\n... и еще {len(detections) - 5} обнаружений"
                
                update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
                
                # Если высокий риск - дополнительное предупреждение
                if data.get('combined_risk', 0) >= 60:
                    warning = f"""
⚠️ **ВЫСОКИЙ РИСК ОБНАРУЖЕН**

Текст содержит потенциально опасные данные.
Рекомендуется немедленное расследование.
                    """
                    update.message.reply_text(warning, parse_mode=ParseMode.MARKDOWN)
                    
            else:
                update.message.reply_text("❌ Ошибка анализа текста")
                
        except Exception as e:
            logger.error(f"Scan error: {e}")
            update.message.reply_text("❌ Ошибка соединения с сервером анализа")
    
    def command_analyze(self, update: Update, context: CallbackContext):
        """Команда /analyze - анализ пользователя"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        if not context.args:
            update.message.reply_text("❌ Укажите ID пользователя: /analyze [ID]")
            return
        
        try:
            target_id = int(context.args[0])
        except:
            update.message.reply_text("❌ Неверный ID пользователя")
            return
        
        try:
            # Запрос информации о пользователе
            response = requests.get(
                f"{RENDER_URL}/api/v1/user/{target_id}",
                headers={'X-API-Key': API_KEY},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                analysis_text = f"""
👤 **Анализ пользователя**

**ID:** {target_id}
**Имя:** {data.get('profile', {}).get('username', 'N/A')}
**Первое появление:** {data.get('profile', {}).get('first_seen', 'N/A')[:16]}
**Последняя активность:** {data.get('profile', {}).get('last_seen', 'N/A')[:16]}

**Статистика утечек:**
• Всего утечек: {data.get('leak_statistics', {}).get('total', 0)}
• Максимальный риск: {data.get('profile', {}).get('max_risk_score', 0)}/100

**Распределение по типам:**
"""
                
                # Добавление типов утечек
                leak_types = data.get('leak_statistics', {}).get('by_type', {})
                for ltype, count in list(leak_types.items())[:5]:
                    analysis_text += f"• {ltype}: {count}\n"
                
                # Оценка угрозы
                threat_score = data.get('threat_score', 0)
                if threat_score > 0:
                    analysis_text += f"\n**Оценка угрозы:** {threat_score}"
                    
                    if threat_score >= 3:
                        analysis_text += "\n🚨 **ВЫСОКИЙ УРОВЕНЬ УГРОЗЫ**"
                    elif threat_score >= 1:
                        analysis_text += "\n⚠️ **ПОТЕНЦИАЛЬНАЯ УГРОЗА**"
                
                update.message.reply_text(analysis_text, parse_mode=ParseMode.MARKDOWN)
                
            elif response.status_code == 404:
                update.message.reply_text(f"ℹ️ Пользователь {target_id} не найден в базе")
            else:
                update.message.reply_text("❌ Ошибка получения данных")
                
        except Exception as e:
            logger.error(f"Analyze error: {e}")
            update.message.reply_text("❌ Ошибка соединения с сервером")
    
    def command_monitor(self, update: Update, context: CallbackContext):
        """Команда /monitor - управление мониторингом"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        monitor_text = """
🎛️ **Управление мониторингом**

**Текущие чаты в мониторинге:**
• Все групповые чаты
• Все супергруппы
• Каналы (только если бот администратор)

**Доступные действия:**
1. *Добавить чат в исключения*
2. *Установить уровень чувствительности*
3. *Включить/выключить детекцию типов*

**Для настройки через веб:**
""" + RENDER_URL + "/dashboard"

        update.message.reply_text(monitor_text, parse_mode=ParseMode.MARKDOWN)
    
    def command_config(self, update: Update, context: CallbackContext):
        """Команда /config - настройки"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            return
        
        config_text = f"""
⚙️ **Конфигурация системы**

**Основные настройки:**
• Уровень безопасности: {os.environ.get('SECURITY_LEVEL', '9')}/10
• Глубокий анализ: {'ВКЛ' if os.environ.get('DEEP_SCAN', 'true') == 'true' else 'ВЫКЛ'}
• AI поведенческий анализ: {'ВКЛ' if os.environ.get('BEHAVIOR_AI', 'true') == 'true' else 'ВЫКЛ'}

**Настройки хранения:**
• Хранение данных: {os.environ.get('DATA_RETENTION_DAYS', '30')} дней
• Автосохранение: каждые {os.environ.get('AUTO_SAVE_INTERVAL', '300')} сек.
• Самопинг: каждые {os.environ.get('SELF_PING_INTERVAL', '300')} сек.

**Доступ:**
• Админы: {len(ALLOWED_USER_IDS)}
• API ключ: {'****' + API_KEY[-8:] if API_KEY else 'НЕ УСТАНОВЛЕН'}

**Для изменения настроек используйте переменные окружения в панели Render.**
        """
        
        update.message.reply_text(config_text, parse_mode=ParseMode.MARKDOWN)
    
    def _detect_leak_quantum(self, msg) -> Optional[Dict]:
        """Квантовая детекция утечек"""
        leak_type = None
        leak_details = ""
        risk_score = 0
        
        # 1. Проверка пересылок
        if msg.forward_from_chat:
            leak_type = "ПЕРЕСЫЛКА_В_ЧАТ"
            leak_details = f"Чат: {msg.forward_from_chat.title}"
            risk_score = 60
            
        elif msg.forward_from:
            leak_type = "ПЕРЕСЫЛКА_ПОЛЬЗОВАТЕЛЮ"
            target = msg.forward_from.username or f"id{msg.forward_from.id}"
            leak_details = f"Пользователь: {target}"
            risk_score = 50
        
        # 2. Анализ текста
        text = msg.text or msg.caption or ""
        
        if text:
            # Проверка ссылок
            link_patterns = [
                r't\.me/(?:c/)?[a-zA-Z0-9_\-/]+',
                r'(?:https?://)?(?:www\.)?(?:telegram\.me|t\.me)/[a-zA-Z0-9_\-/]+',
                r'(?:discord\.gg|discordapp\.com)/[a-zA-Z0-9]+',
                r'vk\.com/[a-zA-Z0-9_\.]+'
            ]
            
            links_found = []
            for pattern in link_patterns:
                links = re.findall(pattern, text)
                links_found.extend(links)
            
            if links_found:
                leak_type = "КОПИРОВАНИЕ_ССЫЛОК"
                leak_details = f"Ссылки: {', '.join(links_found[:3])}"
                risk_score = max(risk_score, 40)
            
            # Проверка длинных текстов
            if len(text) > 500 and '\n' in text:
                leak_type = "КОПИРОВАНИЕ_ТЕКСТА"
                leak_details = f"Длинный текст: {len(text)} симв."
                risk_score = max(risk_score, 30)
            
            # Проверка конфиденциальных данных
            confidential_patterns = [
                (r'\b\d{16}\b', 'НОМЕР_КАРТЫ', 80),
                (r'\b\d{10,12}\b', 'ПАСПОРТ_ИНН', 70),
                (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}', 'EMAIL', 20),
                (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}\b', 'ТЕЛЕФОН', 30),
            ]
            
            for pattern, ctype, score in confidential_patterns:
                if re.search(pattern, text):
                    leak_type = ctype
                    leak_details = "Конфиденциальные данные"
                    risk_score = max(risk_score, score)
        
        # 3. Проверка медиа
        if msg.photo or msg.video or msg.document:
            if not leak_type:
                leak_type = "СОХРАНЕНИЕ_МЕДИА"
                media_type = "фото" if msg.photo else "видео" if msg.video else "документ"
                leak_details = f"Сохранил {media_type}"
                risk_score = max(risk_score, 25)
        
        # 4. Проверка скриншотов
        if hasattr(msg, 'reply_to_message') and msg.reply_to_message:
            time_diff = (msg.date - msg.reply_to_message.date).total_seconds()
            if time_diff > 60 and time_diff < 300:
                if not leak_type or risk_score < 40:
                    leak_type = "СКРИНШОТ"
                    leak_details = f"Ответ через {int(time_diff)} сек."
                    risk_score = max(risk_score, 35)
        
        if leak_type:
            return {
                'type': leak_type,
                'details': leak_details,
                'risk_score': risk_score,
                'timestamp': datetime.now().isoformat(),
                'chat_id': msg.chat.id,
                'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
                'message_id': msg.message_id
            }
        
        return None
    
    def _send_to_quantum_server(self, user_id: int, leak_data: Dict):
        """Отправка данных на Quantum сервер"""
        try:
            # Подготовка данных пользователя
            user_info = {
                'username': leak_data.get('username', f'id{user_id}'),
                'first_name': leak_data.get('first_name', ''),
                'last_name': leak_data.get('last_name', '')
            }
            
            # Отправка на анализ
            response = requests.post(
                f"{RENDER_URL}/api/v1/report_leak",
                json={
                    'user_id': user_id,
                    'leak_data': leak_data,
                    'context': {
                        'source': 'telegram_listener',
                        'chat_type': leak_data.get('chat_type', 'group'),
                        'message_type': 'text' if leak_data.get('text') else 'media'
                    },
                    'user_info': user_info
                },
                headers={'X-API-Key': API_KEY},
                timeout=10
            )
            
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                logger.info(f"✅ Leak reported for user {user_id}")
                return True
            else:
                logger.error(f"❌ Failed to report leak: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ API error: {e}")
            return False
    
    def handle_message(self, update: Update, context: CallbackContext):
        """Обработка всех сообщений"""
        msg = update.message
        if not msg or msg.chat.type == 'private':
            return
        
        user_id = msg.from_user.id
        
        # Обновление кэша пользователя
        if user_id not in self.user_cache:
            self.user_cache[user_id] = {
                'username': msg.from_user.username or f"id{user_id}",
                'first_name': msg.from_user.first_name or "",
                'last_name': msg.from_user.last_name or "",
                'first_seen': datetime.now().isoformat(),
                'message_count': 0
            }
            self.stats['users_monitored'] += 1
        
        self.user_cache[user_id]['last_seen'] = datetime.now().isoformat()
        self.user_cache[user_id]['message_count'] += 1
        
        self.stats['messages_processed'] += 1
        
        # Детекция утечки
        leak_info = self._detect_leak_quantum(msg)
        
        if leak_info:
            self.stats['leaks_detected'] += 1
            
            # Добавление информации о пользователе
            leak_info.update({
                'username': msg.from_user.username or f"id{user_id}",
                'first_name': msg.from_user.first_name or "",
                'last_name': msg.from_user.last_name or "",
                'chat_type': msg.chat.type,
                'text': msg.text or msg.caption or "",
                'has_media': bool(msg.photo or msg.video or msg.document),
                'is_forward': bool(msg.forward_from or msg.forward_from_chat)
            })
            
            # Отправка на сервер для полного анализа
            if RENDER_URL and API_KEY:
                success = self._send_to_quantum_server(user_id, leak_info)
                
                if success and ENABLE_REAL_TIME_ALERTS:
                    # Немедленное уведомление для высокого риска
                    if leak_info['risk_score'] >= 60:
                        self._send_immediate_alert(user_id, leak_info)
            else:
                logger.warning("⚠️ Server URL or API key not configured")
    
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
                context.bot.send_message(
                    chat_id=admin_id,
                    text=alert_msg,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                logger.info(f"📨 Immediate alert sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"❌ Alert error for {admin_id}: {e}")
    
    def run(self):
        """Запуск бота"""
        logger.info("🚀 Запуск Quantum Telegram Listener...")
        
        # Проверка конфигурации
        if not RENDER_URL:
            logger.warning("⚠️ RENDER_URL не установлен, серверные функции недоступны")
        if not API_KEY:
            logger.warning("⚠️ API_KEY не установлен, API вызовы будут отклонены")
        
        self.updater.start_polling()
        self.updater.idle()

def main():
    listener = QuantumTelegramListener()
    listener.run()

if __name__ == '__main__':
    main()