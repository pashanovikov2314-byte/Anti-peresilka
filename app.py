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
from typing import Dict, List, Set, Optional, Tuple
import threading
from dataclasses import dataclass, asdict
from enum import Enum

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== ENUMS ==========
class AlertType(Enum):
    SCREENSHOT = "SCREENSHOT"
    FORWARD = "FORWARD"
    COPY = "COPY"
    SUSPICIOUS = "SUSPICIOUS"
    MEDIA_LEAK = "MEDIA_LEAK"

class Severity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

# ========== МОДЕЛИ ДАННЫХ ==========
@dataclass
class UserProfile:
    user_id: int
    username: str
    first_name: str
    is_bot: bool = False
    first_seen: str = None
    last_seen: str = None
    total_screenshots: int = 0
    total_forwards: int = 0
    total_copies: int = 0
    trust_score: int = 100
    warnings: int = 0

@dataclass
class ChatInfo:
    chat_id: int
    title: str
    username: Optional[str]
    type: str
    participant_count: int = 0
    is_protected: bool = False
    added_to_monitoring: str = None

@dataclass
class Alert:
    alert_id: str
    type: AlertType
    severity: Severity
    user_id: int
    username: str
    chat_id: int
    chat_title: str
    message_id: int
    timestamp: str
    details: Dict
    confidence: int
    is_resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: Optional[int] = None

# ========== ТЕЛЕГРАМ API ==========
class TelegramAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()
    
    def _make_request(self, method: str, data: Dict = None) -> Dict:
        """Универсальный метод запроса"""
        try:
            url = f"{self.base_url}/{method}"
            response = self.session.post(url, json=data, timeout=15)
            return response.json()
        except Exception as e:
            logger.error(f"API request error: {e}")
            return {"ok": False, "error": str(e)}
    
    def send_alert(self, user_id: int, alert: Alert) -> bool:
        """Отправить детальное оповещение"""
        try:
            # Создаём детальное сообщение
            message = self._format_alert_message(alert)
            
            data = {
                "chat_id": user_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": False
            }
            
            result = self._make_request("sendMessage", data)
            
            if result.get("ok"):
                logger.info(f"✅ Alert sent to {user_id} - {alert.type.value}")
                
                # Отправляем дополнительные данные если есть
                if alert.details.get("preview_text"):
                    self._send_message_preview(user_id, alert)
                
                return True
            else:
                logger.error(f"❌ Failed to send alert: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Alert send error: {e}")
            return False
    
    def _format_alert_message(self, alert: Alert) -> str:
        """Форматировать сообщение оповещения"""
        
        # Эмодзи для типов
        type_emojis = {
            AlertType.SCREENSHOT: "📸",
            AlertType.FORWARD: "📨",
            AlertType.COPY: "📋",
            AlertType.SUSPICIOUS: "⚠️",
            AlertType.MEDIA_LEAK: "🎬"
        }
        
        # Эмодзи для серьёзности
        severity_emojis = {
            Severity.LOW: "🔵",
            Severity.MEDIUM: "🟡",
            Severity.HIGH: "🟠",
            Severity.CRITICAL: "🔴"
        }
        
        # Цвета для серьёзности
        severity_colors = {
            Severity.LOW: "#4CAF50",
            Severity.MEDIUM: "#FF9800",
            Severity.HIGH: "#F44336",
            Severity.CRITICAL: "#D32F2F"
        }
        
        emoji = type_emojis.get(alert.type, "🔔")
        severity_emoji = severity_emojis.get(alert.severity, "⚪")
        color = severity_colors.get(alert.severity, "#2196F3")
        
        # Форматируем детали
        details_html = ""
        for key, value in alert.details.items():
            if isinstance(value, bool):
                display_value = "✅ Да" if value else "❌ Нет"
            elif isinstance(value, list):
                display_value = ", ".join(str(v) for v in value[:3])
                if len(value) > 3:
                    display_value += f" ... (+{len(value)-3})"
            else:
                display_value = str(value)
            
            # Форматируем ключи
            formatted_key = key.replace("_", " ").title()
            details_html += f"<b>├ {formatted_key}:</b> {display_value}\n"
        
        # Форматируем время
        alert_time = datetime.fromisoformat(alert.timestamp.replace('Z', '+00:00'))
        formatted_time = alert_time.strftime("%d.%m.%Y %H:%M:%S")
        
        # Создаём сообщение
        message = f"""
{emoji} <b>🚨 СИСТЕМА ОБНАРУЖЕНИЯ УТЕЧЕК</b>
{severity_emoji} <b>Тип:</b> {alert.type.value}
⚡ <b>Серьёзность:</b> {alert.severity.value}
🎯 <b>Уверенность:</b> {alert.confidence}%

━━━━━━━━━━━━━━━━━━━━━━

<b>👤 ПОЛЬЗОВАТЕЛЬ</b>
├ <b>Username:</b> @{alert.username}
├ <b>User ID:</b> <code>{alert.user_id}</code>
├ <b>Доверие:</b> {alert.details.get('user_trust_score', 'N/A')}/100

<b>💬 КОНТЕКСТ</b>
├ <b>Чат:</b> {alert.chat_title}
├ <b>Chat ID:</b> <code>{alert.chat_id}</code>
├ <b>Message ID:</b> <code>{alert.message_id}</code>
├ <b>Время события:</b> {formatted_time}

<b>📊 ДЕТАЛИ ИНЦИДЕНТА</b>
{details_html}
━━━━━━━━━━━━━━━━━━━━━━

<b>🔍 СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ</b>
├ 📸 Скриншотов: {alert.details.get('user_screenshots', 0)}
├ 📨 Пересылок: {alert.details.get('user_forwards', 0)}
├ 📋 Копирований: {alert.details.get('user_copies', 0)}
├ ⚠️ Предупреждений: {alert.details.get('user_warnings', 0)}

<b>⏰ ВРЕМЯ РЕАКЦИИ</b>
├ Обнаружено: {alert.details.get('detection_time', 'Мгновенно')}
├ Отправлено: Сразу после обнаружения

<b>🎯 РЕКОМЕНДАЦИИ</b>
{self._get_recommendations(alert)}

<code>⚠️ Инцидент #{alert.alert_id[:8]}</code>
"""
        return message.strip()
    
    def _get_recommendations(self, alert: Alert) -> str:
        """Получить рекомендации для инцидента"""
        recommendations = {
            AlertType.SCREENSHOT: [
                "• Проверить, какие сообщения были на экране",
                "• Поговорить с пользователем о политике безопасности",
                "• Увеличить уровень мониторинга для этого пользователя"
            ],
            AlertType.FORWARD: [
                "• Проверить содержание пересланного сообщения",
                "• Установить, была ли это утечка конфиденциальной информации",
                "• При необходимости ограничить права пользователя"
            ],
            AlertType.COPY: [
                "• Проверить, какой текст был скопирован",
                "• Оценить важность скопированной информации",
                "• Рассмотреть возможность шифрования чувствительных данных"
            ],
            AlertType.MEDIA_LEAK: [
                "• Проверить, какое медиа было переслано",
                "• Установить источник медиа-файла",
                "• При необходимости удалить медиа из чата"
            ]
        }
        
        base_recs = recommendations.get(alert.type, [
            "• Внимательно изучить детали инцидента",
            "• Принять решение о дальнейших действиях",
            "• Обновить политики безопасности при необходимости"
        ])
        
        # Добавляем рекомендации по серьёзности
        if alert.severity == Severity.CRITICAL:
            base_recs.insert(0, "🚨 ТРЕБУЕТСЯ НЕМЕДЛЕННОЕ ВМЕШАТЕЛЬСТВО!")
            base_recs.append("• Рассмотреть временное исключение пользователя")
        
        elif alert.severity == Severity.HIGH:
            base_recs.insert(0, "⚠️ ВЫСОКИЙ РИСК - ТРЕБУЕТ ВНИМАНИЯ")
            base_recs.append("• Установить наблюдение за пользователем")
        
        return "\n".join(base_recs)
    
    def _send_message_preview(self, user_id: int, alert: Alert):
        """Отправить превью сообщения"""
        try:
            preview_text = alert.details.get("preview_text", "")
            if preview_text:
                # Отправляем оригинальное сообщение (если доступно)
                if alert.details.get("has_original_message", False):
                    preview_msg = f"""
📄 <b>ПРЕВЬЮ СООБЩЕНИЯ</b>

<b>Содержимое:</b>
<code>{preview_text[:300]}{'...' if len(preview_text) > 300 else ''}</code>

<b>Детали:</b>
├ Тип: {alert.details.get('message_type', 'Текст')}
├ Длина: {len(preview_text)} символов
├ Время отправки: {alert.details.get('message_time', 'Неизвестно')}
└ Содержит медиа: {alert.details.get('has_media', False)}
"""
                    self._make_request("sendMessage", {
                        "chat_id": user_id,
                        "text": preview_msg,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True
                    })
        except Exception as e:
            logger.error(f"Preview send error: {e}")

# ========== СИСТЕМА МОНИТОРИНГА ==========
class AdvancedMonitor:
    def __init__(self, token: str, allowed_ids: List[int]):
        self.tg = TelegramAPI(token)
        self.allowed_ids = allowed_ids
        self.users: Dict[int, UserProfile] = {}
        self.chats: Dict[int, ChatInfo] = {}
        self.alerts: List[Alert] = []
        self.alert_counter = 0
        
        # Загружаем существующие данные
        self._load_data()
    
    def _load_data(self):
        """Загрузить данные из файла"""
        try:
            if os.path.exists("monitor_data.json"):
                with open("monitor_data.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Здесь будет загрузка данных
        except Exception as e:
            logger.error(f"Load data error: {e}")
    
    def _save_data(self):
        """Сохранить данные в файл"""
        try:
            data = {
                "users": {uid: asdict(user) for uid, user in self.users.items()},
                "chats": {cid: asdict(chat) for cid, chat in self.chats.items()},
                "alerts": [asdict(alert) for alert in self.alerts[-100:]],
                "alert_counter": self.alert_counter
            }
            
            with open("monitor_data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Save data error: {e}")
    
    def process_message(self, message: Dict) -> Optional[Alert]:
        """Обработать сообщение и создать оповещение если нужно"""
        try:
            chat = message.get("chat", {})
            user = message.get("from", {})
            
            chat_id = chat.get("id")
            user_id = user.get("id")
            username = user.get("username", "")
            first_name = user.get("first_name", "")
            message_id = message.get("message_id")
            text = message.get("text", "") or message.get("caption", "")
            
            # Обновляем информацию о пользователе
            self._update_user_profile(user_id, username, first_name)
            
            # Обновляем информацию о чате
            self._update_chat_info(chat_id, chat)
            
            # Анализируем сообщение
            analysis = self._analyze_message(message)
            
            # Проверяем на утечки
            alert = self._check_for_leaks(
                chat_id, user_id, username, 
                message_id, text, analysis
            )
            
            if alert:
                # Отправляем оповещения всем админам
                self._send_alerts_to_admins(alert)
                
                # Сохраняем оповещение
                self.alerts.append(alert)
                self.alert_counter += 1
                
                # Обновляем статистику пользователя
                self._update_user_stats(user_id, alert.type)
                
                # Сохраняем данные
                self._save_data()
                
                return alert
            
            return None
            
        except Exception as e:
            logger.error(f"Process message error: {e}")
            return None
    
    def _update_user_profile(self, user_id: int, username: str, first_name: str):
        """Обновить профиль пользователя"""
        if user_id not in self.users:
            self.users[user_id] = UserProfile(
                user_id=user_id,
                username=username,
                first_name=first_name,
                first_seen=datetime.now().isoformat(),
                last_seen=datetime.now().isoformat()
            )
        else:
            self.users[user_id].last_seen = datetime.now().isoformat()
            if username and not self.users[user_id].username:
                self.users[user_id].username = username
    
    def _update_chat_info(self, chat_id: int, chat_data: Dict):
        """Обновить информацию о чате"""
        if chat_id not in self.chats:
            self.chats[chat_id] = ChatInfo(
                chat_id=chat_id,
                title=chat_data.get("title", f"Chat {chat_id}"),
                username=chat_data.get("username"),
                type=chat_data.get("type", "unknown"),
                added_to_monitoring=datetime.now().isoformat()
            )
    
    def _analyze_message(self, message: Dict) -> Dict:
        """Анализировать сообщение на признаки утечек"""
        analysis = {
            "is_screenshot_notification": False,
            "is_forward": False,
            "has_external_links": False,
            "contains_sensitive_keywords": False,
            "message_type": "text",
            "has_media": False,
            "media_type": None,
            "forward_details": {},
            "screenshot_details": {}
        }
        
        text = message.get("text", "") or message.get("caption", "")
        
        # Проверка на уведомление о скриншоте
        screenshot_patterns = [
            r'снимок\s+экрана',
            r'скриншот',
            r'screenshot',
            r'сделал(а)?\s+скрин',
            r'заскринил(а)?',
            r'обнаружен\s+снимок'
        ]
        
        for pattern in screenshot_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                analysis["is_screenshot_notification"] = True
                analysis["screenshot_details"] = {
                    "pattern_found": pattern,
                    "notification_text": text,
                    "detected_user": self._extract_screenshot_user(text)
                }
                break
        
        # Проверка на пересылку
        if "forward_from_chat" in message:
            analysis["is_forward"] = True
            analysis["forward_details"] = {
                "from_chat_id": message["forward_from_chat"].get("id"),
                "from_chat_title": message["forward_from_chat"].get("title"),
                "is_cross_chat": True,
                "is_to_pm": message.get("chat", {}).get("type") == "private"
            }
        
        # Проверка на медиа
        if "photo" in message:
            analysis["has_media"] = True
            analysis["media_type"] = "photo"
            analysis["message_type"] = "photo"
        elif "video" in message:
            analysis["has_media"] = True
            analysis["media_type"] = "video"
            analysis["message_type"] = "video"
        elif "document" in message:
            analysis["has_media"] = True
            analysis["media_type"] = "document"
            analysis["message_type"] = "document"
        
        # Проверка на внешние ссылки
        if re.search(r'https?://[^\s]+', text):
            analysis["has_external_links"] = True
        
        # Проверка на чувствительные ключевые слова
        sensitive_keywords = [
            r'парол', r'логин', r'доступ', r'конфиденц',
            r'секрет', r'утек', r'слив', r'data leak',
            r'private', r'confidential'
        ]
        
        for keyword in sensitive_keywords:
            if re.search(keyword, text, re.IGNORECASE):
                analysis["contains_sensitive_keywords"] = True
                break
        
        return analysis
    
    def _extract_screenshot_user(self, text: str) -> str:
        """Извлечь username из уведомления о скриншоте"""
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
    
    def _check_for_leaks(self, chat_id: int, user_id: int, username: str,
                         message_id: int, text: str, analysis: Dict) -> Optional[Alert]:
        """Проверить на наличие утечек и создать оповещение"""
        
        user_profile = self.users.get(user_id)
        chat_info = self.chats.get(chat_id)
        
        if analysis["is_screenshot_notification"]:
            # ОПОВЕЩЕНИЕ О СКРИНШОТЕ
            screenshot_user = analysis["screenshot_details"]["detected_user"]
            
            alert_details = {
                "detection_method": "Системное уведомление Telegram",
                "screenshot_user": screenshot_user,
                "notification_text": analysis["screenshot_details"]["notification_text"],
                "pattern_detected": analysis["screenshot_details"]["pattern_found"],
                "user_trust_score": user_profile.trust_score if user_profile else 100,
                "user_screenshots": user_profile.total_screenshots if user_profile else 0,
                "user_forwards": user_profile.total_forwards if user_profile else 0,
                "user_copies": user_profile.total_copies if user_profile else 0,
                "user_warnings": user_profile.warnings if user_profile else 0,
                "detection_time": "Мгновенно",
                "chat_type": chat_info.type if chat_info else "unknown",
                "has_original_message": bool(text),
                "preview_text": text[:500] if text else "",
                "message_type": analysis["message_type"],
                "has_media": analysis["has_media"],
                "message_time": datetime.now().strftime("%H:%M:%S")
            }
            
            # Определяем серьёзность
            severity = Severity.HIGH
            confidence = 95
            
            # Если пользователь уже делал скриншоты - повышаем серьёзность
            if user_profile and user_profile.total_screenshots > 0:
                severity = Severity.CRITICAL
                confidence = 98
                alert_details["user_history"] = f"Пользователь уже делал {user_profile.total_screenshots} скриншотов"
            
            return Alert(
                alert_id=f"SCR_{self.alert_counter:08d}",
                type=AlertType.SCREENSHOT,
                severity=severity,
                user_id=user_id,
                username=screenshot_user,
                chat_id=chat_id,
                chat_title=chat_info.title if chat_info else f"Chat {chat_id}",
                message_id=message_id,
                timestamp=datetime.now().isoformat(),
                details=alert_details,
                confidence=confidence
            )
        
        elif analysis["is_forward"]:
            # ПЕРЕСЫЛКА СООБЩЕНИЯ
            forward_details = analysis["forward_details"]
            
            alert_details = {
                "detection_method": "Анализ пересылки сообщения",
                "source_chat": forward_details["from_chat_title"],
                "source_chat_id": forward_details["from_chat_id"],
                "is_cross_chat": forward_details["is_cross_chat"],
                "is_to_pm": forward_details["is_to_pm"],
                "destination": "Личные сообщения" if forward_details["is_to_pm"] else "Другой чат",
                "user_trust_score": user_profile.trust_score if user_profile else 100,
                "user_screenshots": user_profile.total_screenshots if user_profile else 0,
                "user_forwards": user_profile.total_forwards if user_profile else 0,
                "user_copies": user_profile.total_copies if user_profile else 0,
                "user_warnings": user_profile.warnings if user_profile else 0,
                "detection_time": "Мгновенно",
                "message_content_preview": text[:200] if text else "Медиа-сообщение",
                "message_length": len(text) if text else 0,
                "contains_media": analysis["has_media"],
                "media_type": analysis["media_type"],
                "has_external_links": analysis["has_external_links"],
                "contains_sensitive_keywords": analysis["contains_sensitive_keywords"],
                "message_time": datetime.now().strftime("%H:%M:%S"),
                "forward_timestamp": datetime.now().isoformat()
            }
            
            # Определяем серьёзность
            if forward_details["is_to_pm"]:
                severity = Severity.HIGH
                confidence = 90
                alert_details["risk_factor"] = "Высокий (пересылка в ЛС)"
            else:
                severity = Severity.MEDIUM
                confidence = 80
                alert_details["risk_factor"] = "Средний (пересылка в другой чат)"
            
            # Если есть чувствительные ключевые слова - повышаем серьёзность
            if analysis["contains_sensitive_keywords"]:
                severity = Severity.CRITICAL
                confidence = 95
                alert_details["additional_risk"] = "Обнаружены чувствительные ключевые слова"
            
            return Alert(
                alert_id=f"FWD_{self.alert_counter:08d}",
                type=AlertType.FORWARD,
                severity=severity,
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                chat_title=chat_info.title if chat_info else f"Chat {chat_id}",
                message_id=message_id,
                timestamp=datetime.now().isoformat(),
                details=alert_details,
                confidence=confidence
            )
        
        elif analysis["contains_sensitive_keywords"] and analysis["has_external_links"]:
            # ПОДОЗРИТЕЛЬНАЯ АКТИВНОСТЬ
            alert_details = {
                "detection_method": "Анализ содержания сообщения",
                "suspicious_keywords_found": True,
                "external_links_found": True,
                "message_content_preview": text[:150] if text else "",
                "user_trust_score": user_profile.trust_score if user_profile else 100,
                "user_screenshots": user_profile.total_screenshots if user_profile else 0,
                "user_forwards": user_profile.total_forwards if user_profile else 0,
                "user_copies": user_profile.total_copies if user_profile else 0,
                "user_warnings": user_profile.warnings if user_profile else 0,
                "detection_time": "Мгновенно",
                "message_type": analysis["message_type"],
                "contains_media": analysis["has_media"],
                "risk_indicators": ["Чувствительные ключевые слова", "Внешние ссылки"],
                "recommended_action": "Проверить содержание сообщения",
                "message_time": datetime.now().strftime("%H:%M:%S")
            }
            
            return Alert(
                alert_id=f"SUS_{self.alert_counter:08d}",
                type=AlertType.SUSPICIOUS,
                severity=Severity.MEDIUM,
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                chat_title=chat_info.title if chat_info else f"Chat {chat_id}",
                message_id=message_id,
                timestamp=datetime.now().isoformat(),
                details=alert_details,
                confidence=75
            )
        
        return None
    
    def _update_user_stats(self, user_id: int, alert_type: AlertType):
        """Обновить статистику пользователя"""
        if user_id in self.users:
            user = self.users[user_id]
            
            if alert_type == AlertType.SCREENSHOT:
                user.total_screenshots += 1
                user.trust_score = max(0, user.trust_score - 15)
                user.warnings += 1
                
            elif alert_type == AlertType.FORWARD:
                user.total_forwards += 1
                user.trust_score = max(0, user.trust_score - 10)
                
            elif alert_type == AlertType.COPY:
                user.total_copies += 1
                user.trust_score = max(0, user.trust_score - 5)
    
    def _send_alerts_to_admins(self, alert: Alert):
        """Отправить оповещения всем администраторам"""
        success_count = 0
        
        for admin_id in self.allowed_ids:
            try:
                if self.tg.send_alert(admin_id, alert):
                    success_count += 1
                    logger.info(f"✅ Детальное оповещение отправлено админу {admin_id}")
                else:
                    logger.error(f"❌ Не удалось отправить оповещение админу {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin_id}: {e}")
        
        logger.info(f"📤 Отправлено {success_count}/{len(self.allowed_ids)} детальных оповещений")

# ========== FLASK APP ==========
app = Flask(__name__)
monitor = AdvancedMonitor(TELEGRAM_TOKEN, ALLOWED_IDS)

# ========== ВЕБХУК ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной обработчик вебхука"""
    try:
        update = request.json
        
        # Логируем входящий запрос
        logger.info(f"📥 Получен вебхук")
        
        if 'message' in update:
            message = update['message']
            
            # Обрабатываем сообщение
            alert = monitor.process_message(message)
            
            if alert:
                logger.info(f"🚨 Обнаружена утечка: {alert.type.value} (Severity: {alert.severity.value})")
                
                # Также отправляем быстрые оповещения
                for admin_id in ALLOWED_IDS:
                    try:
                        quick_msg = f"""
🔔 <b>БЫСТРОЕ ОПОВЕЩЕНИЕ</b>

{['📸', '📨', '⚠️', '🎬'][list(AlertType).index(alert.type)]} <b>{alert.type.value}</b>
👤 Пользователь: @{alert.username}
💬 Чат: {alert.chat_title}
🕒 Время: {datetime.now().strftime('%H:%M:%S')}
⚡ Серьёзность: {alert.severity.value}

<i>Подробности в детальном отчёте</i>
"""
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                            json={
                                "chat_id": admin_id,
                                "text": quick_msg,
                                "parse_mode": "HTML"
                            }
                        )
                    except:
                        pass
        
        return jsonify({"ok": True})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ========== КОМАНДЫ ==========
@app.route('/api/command', methods=['POST'])
def handle_command():
    """Обработчик команд"""
    try:
        data = request.json
        command = data.get('command', '')
        user_id = data.get('user_id')
        
        if not user_id or user_id not in ALLOWED_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        if command == '/monitor':
            response = f"""
📊 <b>СИСТЕМА МОНИТОРИНГА</b>

<b>Статус:</b> ✅ Активен
<b>Мониторится чатов:</b> {len(monitor.chats)}
<b>Всего пользователей:</b> {len(monitor.users)}
<b>Оповещений сегодня:</b> {len([a for a in monitor.alerts if a.timestamp.startswith(datetime.now().date().isoformat())])}

<b>Последние оповещения:</b>
{chr(10).join([f'• {a.type.value} от @{a.username} ({a.timestamp[11:16]})' for a in monitor.alerts[-3:]])}

<b>Команды:</b>
/monitor - эта информация
/stats - детальная статистика
/users - список пользователей
/alerts - последние оповещения
"""
            
        elif command == '/stats':
            total_screenshots = sum(u.total_screenshots for u in monitor.users.values())
            total_forwards = sum(u.total_forwards for u in monitor.users.values())
            
            response = f"""
📈 <b>ДЕТАЛЬНАЯ СТАТИСТИКА</b>

<b>Общая статистика:</b>
├ 📸 Скриншотов: {total_screenshots}
├ 📨 Пересылок: {total_forwards}
├ 👥 Пользователей: {len(monitor.users)}
├ 💬 Чатов: {len(monitor.chats)}
└ 🚨 Оповещений: {len(monitor.alerts)}

<b>Активность сегодня:</b>
├ Обнаружено утечек: {len([a for a in monitor.alerts if a.timestamp.startswith(datetime.now().date().isoformat())])}
├ Активных пользователей: {len([u for u in monitor.users.values() if u.last_seen.startswith(datetime.now().date().isoformat())])}
└ Часов работы: {int((time.time() - monitor.start_time) / 3600)}ч

<b>Топ подозрительных:</b>
{chr(10).join([f'• @{u.username} ({u.trust_score}/100)' for u in sorted(monitor.users.values(), key=lambda x: 100 - x.trust_score)[:3]])}
"""
        
        else:
            response = "❌ Неизвестная команда"
        
        return jsonify({"response": response})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== ВЕБ-ИНТЕРФЕЙС ==========
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/dashboard')
def dashboard_data():
    """Данные для дашборда"""
    total_screenshots = sum(u.total_screenshots for u in monitor.users.values())
    total_forwards = sum(u.total_forwards for u in monitor.users.values())
    
    recent_alerts = []
    for alert in monitor.alerts[-10:]:
        recent_alerts.append({
            'id': alert.alert_id,
            'type': alert.type.value,
            'user': alert.username,
            'chat': alert.chat_title,
            'time': alert.timestamp[11:16],
            'severity': alert.severity.value,
            'confidence': alert.confidence
        })
    
    suspicious_users = []
    for user in sorted(monitor.users.values(), key=lambda x: 100 - x.trust_score)[:5]:
        suspicious_users.append({
            'username': user.username or f"ID: {user.user_id}",
            'trust_score': user.trust_score,
            'screenshots': user.total_screenshots,
            'forwards': user.total_forwards,
            'last_seen': user.last_seen[11:16] if user.last_seen else "N/A"
        })
    
    return jsonify({
        'stats': {
            'screenshots': total_screenshots,
            'forwards': total_forwards,
            'chats': len(monitor.chats),
            'users': len(monitor.users),
            'alerts': len(monitor.alerts)
        },
        'recent_alerts': recent_alerts,
        'suspicious_users': suspicious_users,
        'system_status': 'active',
        'last_update': datetime.now().isoformat()
    })

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("🚀 ЗАПУСК ADVANCED TELEGRAM MONITOR")
    logger.info("=" * 70)
    logger.info(f"🤖 Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
    logger.info(f"👮 Allowed IDs: {len(ALLOWED_IDS)} users")
    logger.info(f"🌐 Port: {PORT}")
    logger.info("=" * 70)
    
    # Проверяем бота
    try:
        response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
        if response.json().get("ok"):
            bot = response.json()["result"]
            logger.info(f"✅ Бот: @{bot.get('username')} (ID: {bot.get('id')})")
        else:
            logger.error(f"❌ Ошибка бота: {response.json().get('description')}")
    except Exception as e:
        logger.error(f"❌ Не удалось подключиться к боту: {e}")
    
    app.run(host="0.0.0.0", port=PORT, debug=False)