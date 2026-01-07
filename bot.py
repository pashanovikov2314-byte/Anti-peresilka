#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SILENT STATS BOT v2.0 - Тихо собирает статистику с использованием aiohttp
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
import traceback

# Проверка импортов
try:
    import aiohttp
    from aiohttp import ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("❌ Установите aiohttp: pip install aiohttp")

try:
    from flask import Flask, jsonify, render_template_string
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("❌ Установите Flask: pip install Flask")

# ========== КОНФИГУРАЦИЯ ==========
class Config:
    """Конфигурация бота"""
    
    # Обязательные
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    ALLOWED_USER_IDS = [
        int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") 
        if x.strip()
    ]
    
    # Опциональные
    DATA_FILE = os.environ.get("DATA_FILE", "telegram_stats.json")
    LOG_FILE = os.environ.get("LOG_FILE", "bot.log")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    
    # Настройки запросов
    UPDATE_TIMEOUT = int(os.environ.get("UPDATE_TIMEOUT", "30"))
    UPDATE_LIMIT = int(os.environ.get("UPDATE_LIMIT", "100"))
    
    # Детекция
    DETECT_FORWARDS = os.environ.get("DETECT_FORWARDS", "true").lower() == "true"
    DETECT_COPIES = os.environ.get("DETECT_COPIES", "true").lower() == "true"
    DETECT_SCREENSHOTS = os.environ.get("DETECT_SCREENSHOTS", "true").lower() == "true"
    
    # Веб-интерфейс
    WEB_PORT = int(os.environ.get("PORT", "5000"))
    WEB_HOST = os.environ.get("HOST", "0.0.0.0")
    
    @classmethod
    def validate(cls):
        """Проверить конфигурацию"""
        errors = []
        
        if not cls.TELEGRAM_TOKEN:
            errors.append("❌ TELEGRAM_TOKEN не установлен")
        
        if not cls.ALLOWED_USER_IDS:
            errors.append("❌ ALLOWED_IDS не установлен (укажите ID через запятую)")
        
        if not AIOHTTP_AVAILABLE:
            errors.append("❌ aiohttp не установлен")
        
        if not FLASK_AVAILABLE:
            errors.append("❌ Flask не установлен")
        
        if errors:
            for error in errors:
                print(error)
            return False
        
        return True
    
    @classmethod
    def log_config(cls):
        """Логировать конфигурацию"""
        print("\n" + "="*50)
        print("⚙️  КОНФИГУРАЦИЯ БОТА")
        print("="*50)
        print(f"🤖 Токен: {'Установлен' if cls.TELEGRAM_TOKEN else 'НЕТ!'}")
        print(f"👥 Разрешённые ID: {cls.ALLOWED_USER_IDS}")
        print(f"📊 Файл данных: {cls.DATA_FILE}")
        print(f"📝 Лог файл: {cls.LOG_FILE}")
        print(f"🔍 Детекция пересылок: {cls.DETECT_FORWARDS}")
        print(f"🔍 Детекция копий: {cls.DETECT_COPIES}")
        print(f"🔍 Детекция скриншотов: {cls.DETECT_SCREENSHOTS}")
        print(f"🌐 Веб-порт: {cls.WEB_PORT}")
        print("="*50 + "\n")

# ========== МОДЕЛИ ДАННЫХ ==========
@dataclass
class MessageData:
    """Данные одного сообщения"""
    message_id: int
    user_id: int
    chat_id: int
    timestamp: str
    text: str = ""
    is_forwarded: bool = False
    is_copy: bool = False
    screenshot_risk: int = 0
    has_media: bool = False
    reply_to: Optional[int] = None

@dataclass
class UserStats:
    """Статистика пользователя"""
    user_id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    
    # Счётчики
    messages_count: int = 0
    forwarded_count: int = 0
    copied_count: int = 0
    media_count: int = 0
    replies_count: int = 0
    
    # Временные метки
    first_seen: str = ""
    last_seen: str = ""
    
    # Активность
    daily_stats: Dict[str, int] = field(default_factory=lambda: defaultdict(int))  # дата -> количество
    
    def update(self, message: MessageData):
        """Обновить статистику на основе сообщения"""
        self.messages_count += 1
        
        if message.is_forwarded:
            self.forwarded_count += 1
        
        if message.is_copy:
            self.copied_count += 1
        
        if message.has_media:
            self.media_count += 1
        
        if message.reply_to:
            self.replies_count += 1
        
        # Временные метки
        if not self.first_seen:
            self.first_seen = message.timestamp
        
        self.last_seen = message.timestamp
        
        # Дневная статистика
        date = message.timestamp[:10]  # YYYY-MM-DD
        self.daily_stats[date] += 1

@dataclass
class ChatStats:
    """Статистика чата"""
    chat_id: int
    title: str = "Unknown Chat"
    
    messages_count: int = 0
    users_count: int = 0
    active_days: Set[str] = field(default_factory=set)
    
    # Проценты
    forwarded_percent: float = 0.0
    copied_percent: float = 0.0
    
    def update(self, message: MessageData, users_in_chat: Set[int]):
        """Обновить статистику чата"""
        self.messages_count += 1
        self.users_count = len(users_in_chat)
        
        # Активные дни
        date = message.timestamp[:10]
        self.active_days.add(date)

# ========== АНАЛИЗАТОР СООБЩЕНИЙ ==========
class MessageAnalyzer:
    """Анализатор сообщений для детекции"""
    
    def __init__(self):
        # Ключевые слова для скриншотов
        self.screenshot_keywords = [
            'скрин', 'screenshot', 'снимок экрана', 'заскринил',
            'сохранил себе', 'у меня есть скрин', 'я сделал скрин',
            'запомнил', 'зафиксировал', 'снял на фото',
            'фото экрана', 'картинка чата', 'сохранено',
            'распространил', 'покажу всем', 'разошлю'
        ]
        
        # Паттерны копирования
        self.copy_patterns = [
            r'скопировал',
            r'копирую',
            r'copy',
            r'взял текст',
            r'украл сообщение',
            r'целиком',
            r'полностью как есть'
        ]
        
        # Стоп-слова (игнорировать)
        self.stop_words = {'привет', 'пока', 'ок', 'спасибо', 'да', 'нет', 'ладно'}
    
    def analyze(self, message_json: Dict) -> MessageData:
        """Проанализировать сообщение Telegram"""
        # Базовые данные
        msg_data = MessageData(
            message_id=message_json.get('message_id', 0),
            user_id=message_json.get('from', {}).get('id', 0),
            chat_id=message_json.get('chat', {}).get('id', 0),
            timestamp=datetime.datetime.now().isoformat()
        )
        
        # Текст сообщения
        text = message_json.get('text') or message_json.get('caption') or ""
        msg_data.text = text
        
        # Проверка на пересылку
        if 'forward_date' in message_json and Config.DETECT_FORWARDS:
            msg_data.is_forwarded = True
        
        # Проверка на медиа
        msg_data.has_media = any(key in message_json 
                                for key in ['photo', 'video', 'audio', 'document', 'voice', 'sticker'])
        
        # Проверка на ответ
        if 'reply_to_message' in message_json:
            msg_data.reply_to = message_json['reply_to_message'].get('message_id')
        
        # Анализ текста
        if text and len(text.strip()) > 3:
            # Проверка на копирование
            if Config.DETECT_COPIES:
                msg_data.is_copy = self._check_copy(text, message_json)
            
            # Проверка на скриншоты
            if Config.DETECT_SCREENSHOTS:
                msg_data.screenshot_risk = self._check_screenshot_risk(text)
        
        return msg_data
    
    def _check_copy(self, text: str, message_json: Dict) -> bool:
        """Проверить, является ли сообщение копией"""
        text_lower = text.lower()
        
        # Проверка по паттернам
        for pattern in self.copy_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        # Проверка на копирование из ответа
        if 'reply_to_message' in message_json:
            reply_text = (message_json['reply_to_message'].get('text') or 
                         message_json['reply_to_message'].get('caption') or "")
            
            if reply_text and self._calculate_similarity(text, reply_text) > 0.7:
                return True
        
        return False
    
    def _check_screenshot_risk(self, text: str) -> int:
        """Оценить риск скриншота (0-100)"""
        if not text:
            return 0
        
        text_lower = text.lower()
        risk_score = 0
        
        # Проверка ключевых слов
        for keyword in self.screenshot_keywords:
            if keyword in text_lower:
                risk_score += 20
        
        # Проверка контекстных фраз
        dangerous_phrases = [
            ('покажу', 'всем'),
            ('распростран', ''),
            ('разошлю', ''),
            ('сохран', 'себе'),
            ('запомн', 'навсегда')
        ]
        
        for phrase, context in dangerous_phrases:
            if phrase in text_lower:
                risk_score += 15
                if context and context in text_lower:
                    risk_score += 10
        
        return min(100, risk_score)
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Вычислить схожесть двух текстов"""
        if not text1 or not text2:
            return 0.0
        
        # Очистка текста
        clean1 = re.sub(r'\s+', ' ', text1.strip().lower())
        clean2 = re.sub(r'\s+', ' ', text2.strip().lower())
        
        if clean1 == clean2:
            return 1.0
        
        # Разделить на слова
        words1 = set(clean1.split())
        words2 = set(clean2.split())
        
        # Удалить стоп-слова
        words1 = words1 - self.stop_words
        words2 = words2 - self.stop_words
        
        if not words1 or not words2:
            return 0.0
        
        # Коэффициент Жаккара
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0

# ========== ХРАНИЛИЩЕ ДАННЫХ ==========
class DataStorage:
    """Хранилище статистики"""
    
    def __init__(self):
        self.messages: List[MessageData] = []
        self.users: Dict[int, UserStats] = {}
        self.chats: Dict[int, ChatStats] = {}
        self.analyzer = MessageAnalyzer()
        
        # Для быстрого доступа
        self.chat_users: Dict[int, Set[int]] = defaultdict(set)
        
        # Загрузить сохранённые данные
        self.load()
    
    def add_message(self, message_json: Dict) -> Optional[MessageData]:
        """Добавить сообщение в хранилище"""
        try:
            # Проверить пользователя
            user_id = message_json.get('from', {}).get('id', 0)
            if user_id not in Config.ALLOWED_USER_IDS:
                return None  # Игнорируем неразрешённых пользователей
            
            # Проанализировать сообщение
            message_data = self.analyzer.analyze(message_json)
            
            # Добавить в список сообщений
            self.messages.append(message_data)
            
            # Обновить пользователя
            self._update_user_stats(message_data, message_json.get('from', {}))
            
            # Обновить чат
            self._update_chat_stats(message_data, message_json.get('chat', {}))
            
            # Сохранить каждые 50 сообщений
            if len(self.messages) % 50 == 0:
                self.save()
            
            return message_data
            
        except Exception as e:
            print(f"❌ Ошибка добавления сообщения: {e}")
            return None
    
    def _update_user_stats(self, message: MessageData, user_info: Dict):
        """Обновить статистику пользователя"""
        user_id = message.user_id
        
        if user_id not in self.users:
            self.users[user_id] = UserStats(
                user_id=user_id,
                username=user_info.get('username', ''),
                first_name=user_info.get('first_name', ''),
                last_name=user_info.get('last_name', '')
            )
        
        self.users[user_id].update(message)
    
    def _update_chat_stats(self, message: MessageData, chat_info: Dict):
        """Обновить статистику чата"""
        chat_id = message.chat_id
        
        if chat_id not in self.chats:
            self.chats[chat_id] = ChatStats(
                chat_id=chat_id,
                title=chat_info.get('title', f'Chat {chat_id}')
            )
        
        # Добавить пользователя в чат
        self.chat_users[chat_id].add(message.user_id)
        
        # Обновить статистику чата
        self.chats[chat_id].update(message, self.chat_users[chat_id])
        
        # Пересчитать проценты раз в 50 сообщений
        if self.chats[chat_id].messages_count % 50 == 0:
            self._recalculate_percentages(chat_id)
    
    def _recalculate_percentages(self, chat_id: int):
        """Пересчитать проценты для чата"""
        chat_messages = [m for m in self.messages if m.chat_id == chat_id]
        
        if not chat_messages:
            return
        
        total = len(chat_messages)
        forwarded = sum(1 for m in chat_messages if m.is_forwarded)
        copied = sum(1 for m in chat_messages if m.is_copy)
        
        self.chats[chat_id].forwarded_percent = (forwarded / total) * 100 if total > 0 else 0
        self.chats[chat_id].copied_percent = (copied / total) * 100 if total > 0 else 0
    
    # ========== API МЕТОДЫ ==========
    
    def get_overall_stats(self) -> Dict:
        """Получить общую статистику"""
        total_messages = len(self.messages)
        total_users = len(self.users)
        total_chats = len(self.chats)
        
        # Рассчитать проценты
        forwarded_pct = 0
        copied_pct = 0
        
        if total_messages > 0:
            forwarded = sum(1 for m in self.messages if m.is_forwarded)
            copied = sum(1 for m in self.messages if m.is_copy)
            
            forwarded_pct = (forwarded / total_messages) * 100
            copied_pct = (copied / total_messages) * 100
        
        # Самый активный пользователь
        most_active = max(
            self.users.values(),
            key=lambda u: u.messages_count,
            default=None
        )
        
        # Самый активный чат
        most_active_chat = max(
            self.chats.values(),
            key=lambda c: c.messages_count,
            default=None
        )
        
        return {
            "status": "ok",
            "timestamp": datetime.datetime.now().isoformat(),
            "total_messages": total_messages,
            "total_users": total_users,
            "total_chats": total_chats,
            "forwarded_percentage": round(forwarded_pct, 2),
            "copied_percentage": round(copied_pct, 2),
            "most_active_user": {
                "user_id": most_active.user_id if most_active else None,
                "username": most_active.username if most_active else "",
                "messages": most_active.messages_count if most_active else 0
            },
            "most_active_chat": {
                "chat_id": most_active_chat.chat_id if most_active_chat else None,
                "title": most_active_chat.title if most_active_chat else "",
                "messages": most_active_chat.messages_count if most_active_chat else 0
            },
            "data_since": self.messages[0].timestamp[:10] if self.messages else "Нет данных"
        }
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Получить статистику пользователя"""
        if user_id not in self.users:
            return {"error": "Пользователь не найден"}
        
        user = self.users[user_id]
        
        # Сообщения пользователя
        user_messages = [m for m in self.messages if m.user_id == user_id]
        
        # Чаты пользователя
        user_chats = {m.chat_id for m in user_messages}
        
        # Активность по дням
        daily_activity = dict(sorted(
            user.daily_stats.items(),
            key=lambda x: x[0],
            reverse=True
        ))
        
        return {
            "user_id": user_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "messages_total": user.messages_count,
            "messages_forwarded": user.forwarded_count,
            "messages_copied": user.copied_count,
            "messages_with_media": user.media_count,
            "replies_sent": user.replies_count,
            "first_seen": user.first_seen[:19] if user.first_seen else "",
            "last_seen": user.last_seen[:19] if user.last_seen else "",
            "active_chats": list(user_chats),
            "daily_activity": daily_activity,
            "screenshot_risk_total": sum(m.screenshot_risk for m in user_messages),
            "screenshot_high_risk_messages": sum(1 for m in user_messages if m.screenshot_risk > 50)
        }
    
    def get_chat_stats(self, chat_id: int) -> Dict:
        """Получить статистику чата"""
        if chat_id not in self.chats:
            return {"error": "Чат не найден"}
        
        chat = self.chats[chat_id]
        chat_messages = [m for m in self.messages if m.chat_id == chat_id]
        
        # Топ пользователей в чате
        user_counts = defaultdict(int)
        for msg in chat_messages:
            user_counts[msg.user_id] += 1
        
        top_users = sorted(
            [(uid, count) for uid, count in user_counts.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Детализация по пользователям
        top_users_detailed = []
        for uid, count in top_users:
            user = self.users.get(uid)
            if user:
                top_users_detailed.append({
                    "user_id": uid,
                    "username": user.username,
                    "first_name": user.first_name,
                    "messages": count
                })
        
        # Активность по дням
        daily_counts = defaultdict(int)
        for msg in chat_messages:
            date = msg.timestamp[:10]
            daily_counts[date] += 1
        
        daily_activity = dict(sorted(
            daily_counts.items(),
            key=lambda x: x[0],
            reverse=True
        ))
        
        return {
            "chat_id": chat_id,
            "title": chat.title,
            "messages_total": chat.messages_count,
            "users_total": chat.users_count,
            "active_days": len(chat.active_days),
            "forwarded_percentage": round(chat.forwarded_percent, 2),
            "copied_percentage": round(chat.copied_percent, 2),
            "top_users": top_users_detailed,
            "daily_activity": daily_activity,
            "first_message": chat_messages[0].timestamp[:19] if chat_messages else "",
            "last_message": chat_messages[-1].timestamp[:19] if chat_messages else ""
        }
    
    def get_all_users(self) -> List[Dict]:
        """Получить список всех пользователей"""
        users_list = []
        for user_id in self.users:
            user_data = self.get_user_stats(user_id)
            if "error" not in user_data:
                users_list.append(user_data)
        
        # Сортировка по количеству сообщений
        users_list.sort(key=lambda x: x.get("messages_total", 0), reverse=True)
        return users_list
    
    def get_all_chats(self) -> List[Dict]:
        """Получить список всех чатов"""
        chats_list = []
        for chat_id in self.chats:
            chat_data = self.get_chat_stats(chat_id)
            if "error" not in chat_data:
                chats_list.append(chat_data)
        
        # Сортировка по количеству сообщений
        chats_list.sort(key=lambda x: x.get("messages_total", 0), reverse=True)
        return chats_list
    
    def export_all_data(self) -> Dict:
        """Экспорт всех данных"""
        return {
            "exported_at": datetime.datetime.now().isoformat(),
            "overall_stats": self.get_overall_stats(),
            "users": self.get_all_users(),
            "chats": self.get_all_chats(),
            "total_messages_stored": len(self.messages),
            "config": {
                "allowed_users": Config.ALLOWED_USER_IDS,
                "detect_forwards": Config.DETECT_FORWARDS,
                "detect_copies": Config.DETECT_COPIES,
                "detect_screenshots": Config.DETECT_SCREENSHOTS
            }
        }
    
    def save(self):
        """Сохранить данные в файл"""
        try:
            data = {
                "messages": [asdict(m) for m in self.messages[-1000:]],  # Последние 1000 сообщений
                "users": {uid: asdict(user) for uid, user in self.users.items()},
                "chats": {cid: asdict(chat) for cid, chat in self.chats.items()},
                "saved_at": datetime.datetime.now().isoformat()
            }
            
            with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"💾 Данные сохранены: {len(self.messages)} сообщений, {len(self.users)} пользователей")
            
        except Exception as e:
            print(f"❌ Ошибка сохранения: {e}")
    
    def load(self):
        """Загрузить данные из файла"""
        try:
            if os.path.exists(Config.DATA_FILE):
                with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Загрузить сообщения
                self.messages = [MessageData(**msg) for msg in data.get("messages", [])]
                
                # Загрузить пользователей
                self.users = {}
                for uid_str, user_data in data.get("users", {}).items():
                    user = UserStats(**user_data)
                    self.users[user.user_id] = user
                
                # Загрузить чаты
                self.chats = {}
                for cid_str, chat_data in data.get("chats", {}).items():
                    chat = ChatStats(**chat_data)
                    self.chats[chat.chat_id] = chat
                
                # Восстановить chat_users
                self.chat_users.clear()
                for msg in self.messages:
                    self.chat_users[msg.chat_id].add(msg.user_id)
                
                print(f"📂 Данные загружены: {len(self.messages)} сообщений, {len(self.users)} пользователей")
                
        except Exception as e:
            print(f"⚠️ Не удалось загрузить данные: {e}")

# ========== TELEGRAM БОТ ==========
class SilentTelegramBot:
    """Тихий бот для сбора статистики"""
    
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.storage = DataStorage()
        self.running = False
        self.last_update_id = 0
        
        # Настройка логирования
        logging.basicConfig(
            level=getattr(logging, Config.LOG_LEVEL),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger(__name__)
    
    async def fetch_updates(self) -> List[Dict]:
        """Получить обновления от Telegram API"""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": Config.UPDATE_TIMEOUT,
                "limit": Config.UPDATE_LIMIT,
                "allowed_updates": ["message", "edited_message"]
            }
            
            timeout = ClientTimeout(total=Config.UPDATE_TIMEOUT + 10)
            
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("ok"):
                            return data.get("result", [])
                    else:
                        self.logger.error(f"API Error: {response.status}")
                        
        except asyncio.TimeoutError:
            self.logger.debug("Таймаут запроса обновлений")
        except Exception as e:
            self.logger.error(f"Ошибка получения обновлений: {e}")
        
        return []
    
    async def process_updates(self, updates: List[Dict]):
        """Обработать полученные обновления"""
        for update in updates:
            update_id = update.get("update_id", 0)
            
            if update_id > self.last_update_id:
                self.last_update_id = update_id
            
            # Обработка сообщений
            if "message" in update:
                await self._process_message(update["message"])
            elif "edited_message" in update:
                await self._process_message(update["edited_message"], edited=True)
    
    async def _process_message(self, message: Dict, edited: bool = False):
        """Обработать одно сообщение"""
        try:
            # Игнорировать служебные сообщения
            if any(key in message for key in 
                  ['new_chat_members', 'left_chat_member', 'new_chat_title', 'new_chat_photo']):
                return
            
            # Игнорировать команды
            if message.get('text', '').startswith('/'):
                return
            
            # Добавить в статистику
            message_data = self.storage.add_message(message)
            
            if message_data:
                user = message.get('from', {})
                username = user.get('username', user.get('first_name', 'Unknown'))
                
                log_msg = f"📨 Сообщение {message_data.message_id} от {username} (ID: {message_data.user_id})"
                
                if edited:
                    log_msg += " [РЕДАКТИРОВАНО]"
                
                if message_data.is_forwarded:
                    log_msg += " [ПЕРЕСЛАНО]"
                
                if message_data.is_copy:
                    log_msg += " [КОПИЯ]"
                
                if message_data.screenshot_risk > 50:
                    log_msg += f" [СКРИНШОТ РИСК: {message_data.screenshot_risk}%]"
                
                self.logger.info(log_msg)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки сообщения: {e}")
    
    async def run(self):
        """Основной цикл работы бота"""
        self.running = True
        
        # Показать конфигурацию
        Config.log_config()
        
        # Проверить соединение
        await self._test_connection()
        
        self.logger.info("🤖 Тихий бот запущен. Собираю статистику...")
        self.logger.info(f"👥 Разрешённые пользователи: {Config.ALLOWED_USER_IDS}")
        self.logger.info("📊 Бот работает в тихом режиме (не пишет в чаты)")
        
        # Автосохранение в фоновом потоке
        def auto_save():
            while self.running:
                time.sleep(300)  # Каждые 5 минут
                self.storage.save()
        
        save_thread = threading.Thread(target=auto_save, daemon=True)
        save_thread.start()
        
        # Основной цикл
        while self.running:
            try:
                updates = await self.fetch_updates()
                
                if updates:
                    await self.process_updates(updates)
                else:
                    # Пауза между запросами
                    await asyncio.sleep(1)
                    
            except KeyboardInterrupt:
                self.logger.info("🛑 Остановка по запросу пользователя")
                break
                
            except Exception as e:
                self.logger.error(f"Ошибка в основном цикле: {e}")
                await asyncio.sleep(5)
        
        # Финальное сохранение
        self.storage.save()
        self.logger.info("Бот остановлен")
    
    async def _test_connection(self):
        """Проверить соединение с Telegram API"""
        try:
            url = f"{self.base_url}/getMe"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("ok"):
                            bot_info = data.get("result", {})
                            self.logger.info(f"✅ Бот @{bot_info.get('username')} подключён")
                            return True
            
            self.logger.error("❌ Не удалось подключиться к Telegram API")
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка подключения: {e}")
            return False
    
    def stop(self):
        """Остановить бота"""
        self.running = False

# ========== ВЕБ-ИНТЕРФЕЙС ==========
def setup_web_interface(bot_instance: SilentTelegramBot):
    """Настройка Flask веб-интерфейса"""
    if not FLASK_AVAILABLE:
        print("❌ Flask не установлен, веб-интерфейс недоступен")
        return None
    
    app = Flask(__name__)
    
    # HTML шаблон
    HTML_TEMPLATE = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>📊 Silent Stats Bot</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #333;
                min-height: 100vh;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                background: rgba(255, 255, 255, 0.95);
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                text-align: center;
            }
            .header h1 {
                color: #667eea;
                margin-bottom: 10px;
                font-size: 2.5em;
            }
            .header p {
                color: #666;
                font-size: 1.1em;
                opacity: 0.9;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: rgba(255, 255, 255, 0.95);
                padding: 25px;
                border-radius: 15px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                transition: transform 0.3s, box-shadow 0.3s;
            }
            .stat-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 15px 30px rgba(0,0,0,0.15);
            }
            .stat-card .value {
                font-size: 2.5em;
                font-weight: bold;
                color: #667eea;
                margin: 10px 0;
            }
            .stat-card .label {
                color: #666;
                font-size: 0.9em;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .section {
                background: rgba(255, 255, 255, 0.95);
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 30px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }
            .section h2 {
                color: #667eea;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px
