#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SILENT STATS BOT - Тихо собирает статистику, не пишет в чат
"""

import os
import sys
import json
import time
import hashlib
import logging
import threading
import datetime
import re
import asyncio
from typing import Dict, List, Optional, Set, Any
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from enum import Enum
import aiohttp
from contextlib import suppress

# ========== КОНФИГУРАЦИЯ ==========
class Config:
    """Конфигурация бота"""
    # Обязательные
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
    
    # Опциональные
    DATA_FILE = os.environ.get("DATA_FILE", "bot_stats.json")
    LOG_FILE = os.environ.get("LOG_FILE", "bot_activity.log")
    CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))  # секунд
    SAVE_INTERVAL = int(os.environ.get("SAVE_INTERVAL", "600"))
    
    # Настройки детекции
    DETECT_FORWARDS = os.environ.get("DETECT_FORWARDS", "true").lower() == "true"
    DETECT_COPIES = os.environ.get("DETECT_COPIES", "true").lower() == "true"
    DETECT_SCREENSHOTS = os.environ.get("DETECT_SCREENSHOTS", "true").lower() == "true"
    
    # Минимальная длина для анализа
    MIN_TEXT_LENGTH = int(os.environ.get("MIN_TEXT_LENGTH", "10"))
    
    @classmethod
    def validate(cls):
        if not cls.TELEGRAM_TOKEN:
            raise ValueError("❌ TELEGRAM_TOKEN не установлен")
        if not cls.ALLOWED_USER_IDS:
            raise ValueError("❌ ALLOWED_IDS не установлен (укажите хотя бы один ID через запятую)")
        return True

# ========== МОДЕЛИ ДАННЫХ ==========
@dataclass
class MessageStats:
    """Статистика по одному сообщению"""
    message_id: int
    user_id: int
    chat_id: int
    timestamp: str
    text_length: int = 0
    has_forward: bool = False
    has_reply: bool = False
    has_media: bool = False
    is_copy: bool = False
    screenshot_risk: int = 0  # 0-100
    detected_patterns: List[str] = field(default_factory=list)

@dataclass
class UserStats:
    """Статистика пользователя"""
    user_id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    
    # Счётчики
    total_messages: int = 0
    forwarded_messages: int = 0
    copied_messages: int = 0
    replies_sent: int = 0
    media_sent: int = 0
    
    # Риски
    total_screenshot_risk: int = 0
    high_risk_messages: int = 0
    
    # Временные метки
    first_seen: str = ""
    last_activity: str = ""
    
    # Подробная статистика
    hourly_activity: Dict[int, int] = field(default_factory=lambda: defaultdict(int))  # час -> количество
    daily_activity: Dict[str, int] = field(default_factory=lambda: defaultdict(int))   # дата -> количество
    word_frequency: Dict[str, int] = field(default_factory=lambda: defaultdict(int))   # слово -> частота
    
    def update(self, msg_stats: MessageStats):
        """Обновить статистику на основе нового сообщения"""
        self.total_messages += 1
        
        if msg_stats.has_forward:
            self.forwarded_messages += 1
        if msg_stats.has_reply:
            self.replies_sent += 1
        if msg_stats.has_media:
            self.media_sent += 1
        if msg_stats.is_copy:
            self.copied_messages += 1
            
        self.total_screenshot_risk += msg_stats.screenshot_risk
        if msg_stats.screenshot_risk > 70:
            self.high_risk_messages += 1
            
        # Обновить время
        if not self.first_seen:
            self.first_seen = msg_stats.timestamp
        self.last_activity = msg_stats.timestamp
        
        # Часовую активность
        hour = datetime.datetime.fromisoformat(msg_stats.timestamp.replace('Z', '+00:00')).hour
        self.hourly_activity[hour] += 1
        
        # Дневную активность
        date = msg_stats.timestamp[:10]
        self.daily_activity[date] += 1

@dataclass
class ChatStats:
    """Статистика чата"""
    chat_id: int
    title: str = ""
    
    total_messages: int = 0
    total_users: int = 0
    active_days: Set[str] = field(default_factory=set)
    
    # Топы
    top_posters: Dict[int, int] = field(default_factory=lambda: defaultdict(int))  # user_id -> количество
    top_words: Dict[str, int] = field(default_factory=lambda: defaultdict(int))     # слово -> частота
    
    # Аналитика
    messages_per_day: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    forwarded_percentage: float = 0.0
    copy_percentage: float = 0.0
    
    def update(self, msg_stats: MessageStats):
        """Обновить статистику чата"""
        self.total_messages += 1
        
        # Добавить день активности
        date = msg_stats.timestamp[:10]
        self.active_days.add(date)
        self.messages_per_day[date] += 1
        
        # Обновить топ постеров
        self.top_posters[msg_stats.user_id] += 1
        
        # Рассчитать проценты (раз в 100 сообщений)
        if self.total_messages % 100 == 0:
            self._calculate_percentages()
    
    def _calculate_percentages(self):
        """Рассчитать процентные соотношения"""
        # Это заглушка - реальные проценты считаются на основе данных
        pass

# ========== АНАЛИЗАТОР СООБЩЕНИЙ ==========
class MessageAnalyzer:
    """Тихий анализатор сообщений"""
    
    def __init__(self):
        self.screenshot_keywords = [
            'скрин', 'screenshot', 'снимок экрана', 'заскринил',
            'сохранил себе', 'у меня есть', 'покажу всем',
            'распространил', 'переслал всем', 'разошлю',
            'сохранено', 'сохранилось', 'запомнил',
            'зафиксировал', 'запечатлел', 'снял на фото',
            'фото экрана', 'картинка чата', 'сохрани скрин'
        ]
        
        self.copy_patterns = [
            r'(скопировал|копирую|копипаст|copy|copied|взял|украл)',
            r'(целиком|полностью|весь текст|всё как есть)',
            r'(сохранил|заберу|возьму себе|для себя)'
        ]
        
    def analyze(self, message: Dict) -> MessageStats:
        """Проанализировать сообщение без ответа"""
        msg_stats = MessageStats(
            message_id=message.get('message_id', 0),
            user_id=message.get('from', {}).get('id', 0),
            chat_id=message.get('chat', {}).get('id', 0),
            timestamp=datetime.datetime.now().isoformat()
        )
        
        # Проверка текста
        text = message.get('text') or message.get('caption') or ""
        msg_stats.text_length = len(text)
        
        # Пересылка
        msg_stats.has_forward = 'forward_date' in message
        
        # Ответ
        msg_stats.has_reply = 'reply_to_message' in message
        
        # Медиа
        msg_stats.has_media = any(key in message for key in 
                                 ['photo', 'video', 'document', 'audio', 'voice'])
        
        # Проверка на копирование
        if text and len(text) >= Config.MIN_TEXT_LENGTH:
            msg_stats.is_copy = self._check_copy(text, message)
        
        # Проверка на скриншоты
        if text:
            msg_stats.screenshot_risk = self._check_screenshot_risk(text)
            
        return msg_stats
    
    def _check_copy(self, text: str, message: Dict) -> bool:
        """Проверить, является ли сообщение копией"""
        if not Config.DETECT_COPIES:
            return False
            
        # Если есть reply_to_message, сравниваем тексты
        if 'reply_to_message' in message:
            reply_text = message['reply_to_message'].get('text') or message['reply_to_message'].get('caption') or ""
            if reply_text and self._text_similarity(text, reply_text) > 0.8:
                return True
        
        # Проверка по паттернам
        text_lower = text.lower()
        for pattern in self.copy_patterns:
            if re.search(pattern, text_lower):
                return True
                
        return False
    
    def _check_screenshot_risk(self, text: str) -> int:
        """Оценить риск скриншота (0-100)"""
        if not Config.DETECT_SCREENSHOTS:
            return 0
            
        text_lower = text.lower()
        risk_score = 0
        
        # Проверка ключевых слов
        for keyword in self.screenshot_keywords:
            if keyword in text_lower:
                risk_score += 20
                
        # Проверка контекста
        if any(phrase in text_lower for phrase in 
               ['покажу', 'распростран', 'разошлю', 'всем покажу', 'покажу всем']):
            risk_score += 30
            
        if any(phrase in text_lower for phrase in 
               ['сохрани', 'запомни', 'зафиксировал']):
            risk_score += 25
            
        return min(100, risk_score)
    
    def _text_similarity(self, text1: str, text2: str) -> float:
        """Вычислить схожесть текстов"""
        if not text1 or not text2:
            return 0.0
            
        # Привести к нижнему регистру и убрать лишние пробелы
        t1 = re.sub(r'\s+', ' ', text1.lower().strip())
        t2 = re.sub(r'\s+', ' ', text2.lower().strip())
        
        # Если тексты идентичны
        if t1 == t2:
            return 1.0
            
        # Вычислить схожесть по словам
        words1 = set(t1.split())
        words2 = set(t2.split())
        
        if not words1 or not words2:
            return 0.0
            
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0

# ========== ХРАНИЛИЩЕ ДАННЫХ ==========
class DataStorage:
    """Хранилище статистики"""
    
    def __init__(self):
        self.users: Dict[int, UserStats] = {}
        self.chats: Dict[int, ChatStats] = {}
        self.messages: List[MessageStats] = []
        self.analyzer = MessageAnalyzer()
        
        # Загрузить существующие данные
        self.load()
        
    def add_message(self, message: Dict) -> Optional[MessageStats]:
        """Добавить сообщение в статистику"""
        try:
            # Проверить пользователя
            user_id = message.get('from', {}).get('id', 0)
            if user_id not in Config.ALLOWED_USER_IDS:
                return None  # Игнорируем сообщения от неразрешённых пользователей
            
            # Проанализировать
            msg_stats = self.analyzer.analyze(message)
            
            # Обновить пользователя
            self._update_user_stats(msg_stats, message.get('from', {}))
            
            # Обновить чат
            self._update_chat_stats(msg_stats, message.get('chat', {}))
            
            # Сохранить сообщение
            self.messages.append(msg_stats)
            
            # Автосохранение каждые 100 сообщений
            if len(self.messages) % 100 == 0:
                self.save()
                
            return msg_stats
            
        except Exception as e:
            logging.error(f"Ошибка добавления сообщения: {e}")
            return None
    
    def _update_user_stats(self, msg_stats: MessageStats, user_data: Dict):
        """Обновить статистику пользователя"""
        user_id = msg_stats.user_id
        
        if user_id not in self.users:
            self.users[user_id] = UserStats(
                user_id=user_id,
                username=user_data.get('username', ''),
                first_name=user_data.get('first_name', ''),
                last_name=user_data.get('last_name', ''),
                first_seen=msg_stats.timestamp
            )
        
        self.users[user_id].update(msg_stats)
        
        # Собираем частоту слов (если есть текст)
        # Этот код можно расширить для анализа текста
    
    def _update_chat_stats(self, msg_stats: MessageStats, chat_data: Dict):
        """Обновить статистику чата"""
        chat_id = msg_stats.chat_id
        
        if chat_id not in self.chats:
            self.chats[chat_id] = ChatStats(
                chat_id=chat_id,
                title=chat_data.get('title', f'Chat {chat_id}')
            )
        
        self.chats[chat_id].update(msg_stats)
        self.chats[chat_id].total_users = len({
            msg.user_id for msg in self.messages 
            if msg.chat_id == chat_id
        })
    
    def get_user_report(self, user_id: int) -> Dict:
        """Получить отчёт по пользователю"""
        if user_id not in self.users:
            return {"error": "Пользователь не найден"}
        
        user = self.users[user_id]
        chat_ids = {msg.chat_id for msg in self.messages if msg.user_id == user_id}
        
        return {
            "user_id": user_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "total_messages": user.total_messages,
            "forwarded_messages": user.forwarded_messages,
            "copied_messages": user.copied_messages,
            "replies_sent": user.replies_sent,
            "media_sent": user.media_sent,
            "screenshot_risk_score": user.total_screenshot_risk,
            "high_risk_messages": user.high_risk_messages,
            "first_seen": user.first_seen,
            "last_activity": user.last_activity,
            "active_chats": list(chat_ids),
            "most_active_hour": max(user.hourly_activity.items(), key=lambda x: x[1], default=(None, 0))[0]
        }
    
    def get_chat_report(self, chat_id: int) -> Dict:
        """Получить отчёт по чату"""
        if chat_id not in self.chats:
            return {"error": "Чат не найден"}
        
        chat = self.chats[chat_id]
        chat_messages = [msg for msg in self.messages if msg.chat_id == chat_id]
        
        # Рассчитать проценты
        if chat_messages:
            forwarded = sum(1 for msg in chat_messages if msg.has_forward)
            copied = sum(1 for msg in chat_messages if msg.is_copy)
            
            chat.forwarded_percentage = (forwarded / len(chat_messages)) * 100
            chat.copy_percentage = (copied / len(chat_messages)) * 100
        
        # Топ постеров
        top_posters = sorted(
            [(uid, count) for uid, count in chat.top_posters.items()],
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            "chat_id": chat_id,
            "title": chat.title,
            "total_messages": chat.total_messages,
            "total_users": chat.total_users,
            "active_days": len(chat.active_days),
            "forwarded_percentage": round(chat.forwarded_percentage, 2),
            "copy_percentage": round(chat.copy_percentage, 2),
            "top_posters": [
                {"user_id": uid, "count": count, "username": self.users.get(uid, UserStats(uid)).username}
                for uid, count in top_posters
            ],
            "activity_by_day": dict(sorted(chat.messages_per_day.items()))
        }
    
    def get_overall_stats(self) -> Dict:
        """Общая статистика"""
        total_messages = len(self.messages)
        total_users = len(self.users)
        total_chats = len(self.chats)
        
        # Процент пересланных сообщений
        forwarded = sum(1 for msg in self.messages if msg.has_forward)
        forwarded_pct = (forwarded / total_messages * 100) if total_messages > 0 else 0
        
        # Процент копий
        copied = sum(1 for msg in self.messages if msg.is_copy)
        copied_pct = (copied / total_messages * 100) if total_messages > 0 else 0
        
        # Самый активный пользователь
        most_active = max(
            self.users.items(), 
            key=lambda x: x[1].total_messages,
            default=(None, UserStats(0))
        )
        
        return {
            "total_messages": total_messages,
            "total_users": total_users,
            "total_chats": total_chats,
            "forwarded_percentage": round(forwarded_pct, 2),
            "copied_percentage": round(copied_pct, 2),
            "most_active_user": {
                "user_id": most_active[0],
                "username": most_active[1].username,
                "message_count": most_active[1].total_messages
            } if most_active[0] else None,
            "data_collection_started": min(
                (msg.timestamp for msg in self.messages), 
                default=datetime.datetime.now().isoformat()
            )
        }
    
    def save(self):
        """Сохранить данные в файл"""
        try:
            data = {
                "users": {uid: asdict(user) for uid, user in self.users.items()},
                "chats": {cid: asdict(chat) for cid, chat in self.chats.items()},
                "messages": [asdict(msg) for msg in self.messages[-10000:]],  # Сохраняем последние 10000 сообщений
                "saved_at": datetime.datetime.now().isoformat()
            }
            
            with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            logging.info(f"Данные сохранены: {len(self.messages)} сообщений, {len(self.users)} пользователей")
            
        except Exception as e:
            logging.error(f"Ошибка сохранения данных: {e}")
    
    def load(self):
        """Загрузить данные из файла"""
        try:
            if os.path.exists(Config.DATA_FILE):
                with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Восстановить пользователей
                self.users.clear()
                for uid_str, user_data in data.get("users", {}).items():
                    user = UserStats(**user_data)
                    self.users[user.user_id] = user
                
                # Восстановить чаты
                self.chats.clear()
                for cid_str, chat_data in data.get("chats", {}).items():
                    chat = ChatStats(**chat_data)
                    self.chats[chat.chat_id] = chat
                
                # Восстановить сообщения
                self.messages = [MessageStats(**msg) for msg in data.get("messages", [])]
                
                logging.info(f"Данные загружены: {len(self.messages)} сообщений, {len(self.users)} пользователей")
                
        except Exception as e:
            logging.error(f"Ошибка загрузки данных: {e}")

# ========== TELEGRAM БОТ ==========
class SilentTelegramBot:
    """Тихий бот, который только собирает статистику"""
    
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.storage = DataStorage()
        self.running = False
        
        # Настройка логирования
        logging.basicConfig(
            level=getattr(logging, Config.LOG_LEVEL),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        # Проверка конфигурации
        Config.validate()
        logging.info("Конфигурация проверена успешно")
    
    async def get_updates(self, offset: int = 0, timeout: int = 30) -> List[Dict]:
        """Получить обновления от Telegram"""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "edited_message"]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("result", [])
                    else:
                        logging.error(f"Ошибка API: {response.status}")
                        return []
                        
        except Exception as e:
            logging.error(f"Ошибка получения updates: {e}")
            return []
    
    async def process_updates(self, updates: List[Dict]) -> int:
        """Обработать обновления"""
        last_update_id = 0
        
        for update in updates:
            update_id = update.get("update_id", 0)
            last_update_id = max(last_update_id, update_id)
            
            # Обработка сообщений
            if "message" in update:
                message = update["message"]
                
                # Игнорируем служебные сообщения
                if message.get("new_chat_members") or message.get("left_chat_member"):
                    continue
                    
                # Игнорируем команды боту
                if message.get("text", "").startswith("/"):
                    continue
                
                # Добавить в статистику
                msg_stats = self.storage.add_message(message)
                
                if msg_stats:
                    # Тихо логируем
                    logging.debug(f"Сообщение {msg_stats.message_id} от {msg_stats.user_id} обработано")
        
        return last_update_id + 1 if last_update_id > 0 else 0
    
    async def run(self):
        """Основной цикл бота"""
        self.running = True
        offset = 0
        
        logging.info("🤖 Тихий бот запущен. Собираю статистику...")
        logging.info(f"Разрешённые пользователи: {Config.ALLOWED_USER_IDS}")
        logging.info(f"Детекция пересылок: {Config.DETECT_FORWARDS}")
        logging.info(f"Детекция копирования: {Config.DETECT_COPIES}")
        logging.info(f"Детекция скриншотов: {Config.DETECT_SCREENSHOTS}")
        
        # Автосохранение в фоне
        def auto_save():
            while self.running:
                time.sleep(Config.SAVE_INTERVAL)
                self.storage.save()
        
        save_thread = threading.Thread(target=auto_save, daemon=True)
        save_thread.start()
        
        # Основной цикл обработки
        while self.running:
            try:
                updates = await self.get_updates(offset)
                
                if updates:
                    new_offset = await self.process_updates(updates)
                    if new_offset > offset:
                        offset = new_offset
                
                # Пауза между запросами
                await asyncio.sleep(1)
                
            except KeyboardInterrupt:
                logging.info("Получен сигнал остановки")
                break
                
            except Exception as e:
                logging.error(f"Ошибка в основном цикле: {e}")
                await asyncio.sleep(5)
        
        # Финальное сохранение
        self.storage.save()
        logging.info("Бот остановлен")
    
    def stop(self):
        """Остановить бота"""
        self.running = False

# ========== ВЕБ-ИНТЕРФЕЙС ДЛЯ СТАТИСТИКИ ==========
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
bot_instance = None

# HTML шаблон для веб-интерфейса
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>📊 Статистика Silent Bot</title>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card {
            background: white;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 25px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            transition: transform 0.2s;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-box {
            background: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .stat-value {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }
        .stat-label {
            color: #666;
            font-size: 0.9em;
        }
        .user-list, .chat-list {
            display: grid;
            gap: 15px;
        }
        .user-item, .chat-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
        }
        tr:hover {
            background: #f5f7fa;
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 600;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-warning { background: #fff3cd; color: #856404; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .code {
            font-family: 'Consolas', monospace;
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤫 Silent Telegram Bot</h1>
        <p>Тихая система сбора статистики сообщений</p>
        <p style="opacity: 0.8;">Бот работает в режиме полной тишины, не пишет в чаты</p>
    </div>
    
    {% if overall_stats %}
    <div class="stats-grid">
        <div class="stat-box">
            <div class="stat-label">Всего сообщений</div>
            <div class="stat-value">{{ overall_stats.total_messages }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Пользователей</div>
            <div class="stat-value">{{ overall_stats.total_users }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Чатов</div>
            <div class="stat-value">{{ overall_stats.total_chats }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Пересылок</div>
            <div class="stat-value">{{ overall_stats.forwarded_percentage }}%</div>
        </div>
    </div>
    {% endif %}
    
    <div class="card">
        <h2>📈 Общая статистика</h2>
        {% if overall_stats %}
        <table>
            <tr>
                <th>Показатель</th>
                <th>Значение</th>
            </tr>
            <tr>
                <td>Всего сообщений</td>
                <td>{{ overall_stats.total_messages }}</td>
            </tr>
            <tr>
                <td>Всего пользователей</td>
                <td>{{ overall_stats.total_users }}</td>
            </tr>
            <tr>
                <td>Всего чатов</td>
                <td>{{ overall_stats.total_chats }}</td>
            </tr>
            <tr>
                <td>Процент пересланных</td>
                <td>{{ overall_stats.forwarded_percentage }}%</td>
            </tr>
            <tr>
                <td>Процент скопированных</td>
                <td>{{ overall_stats.copied_percentage }}%</td>
            </tr>
            <tr>
                <td>Сбор данных с</td>
                <td>{{ overall_stats.data_collection_started[:19] }}</td>
            </tr>
        </table>
        {% else %}
        <p>Нет данных для отображения</p>
        {% endif %}
    </div>
    
    <div class="card">
        <h2>👥 Пользователи</h2>
        {% if users %}
        <table>
            <tr>
                <th>ID</th>
                <th>Имя</th>
                <th>Сообщений</th>
                <th>Пересылок</th>
                <th>Копий</th>
                <th>Риск скриншотов</th>
                <th>Активность</th>
            </tr>
            {% for user in users[:20] %}
            <tr>
                <td>{{ user.user_id }}</td>
                <td>{{ user.first_name }} {{ user.last_name }}</td>
                <td>{{ user.total_messages }}</td>
                <td>{{ user.forwarded_messages }}</td>
                <td>{{ user.copied_messages }}</td>
                <td>
                    {% if user.screenshot_risk_score > 100 %}
                    <span class="badge badge-danger">Высокий</span>
                    {% elif user.screenshot_risk_score > 50 %}
                    <span class="badge badge-warning">Средний</span>
                    {% else %}
                    <span class="badge badge-success">Низкий</span>
                    {% endif %}
                </td>
                <td>{{ user.last_activity[:19] }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p>Нет данных о пользователях</p>
        {% endif %}
    </div>
    
    <div class="card">
        <h2>💬 Чаты</h2>
        {% if chats %}
        <table>
            <tr>
                <th>ID</th>
                <th>Название</th>
                <th>Сообщений</th>
                <th>Участников</th>
                <th>Активных дней</th>
                <th>Пересылок</th>
            </tr>
            {% for chat in chats %}
            <tr>
                <td>{{ chat.chat_id }}</td>
                <td>{{ chat.title }}</td>
                <td>{{ chat.total_messages }}</td>
                <td>{{ chat.total_users }}</td>
                <td>{{ chat.active_days }}</td>
                <td>{{ chat.forwarded_percentage }}%</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p>Нет данных о чатах</p>
        {% endif %}
    </div>
    
    <div class="card">
        <h2>⚙️ Конфигурация</h2>
        <div class="code">
TELEGRAM_TOKEN = ********<br>
ALLOWED_USER_IDS = {{ allowed_users }}<br>
DETECT_FORWARDS = {{ detect_forwards }}<br>
DETECT_COPIES = {{ detect_copies }}<br>
DETECT_SCREENSHOTS = {{ detect_screenshots }}<br>
DATA_FILE = {{ data_file }}
        </div>
    </div>
    
    <div class="card">
        <h2>📊 API Endpoints</h2>
        <p>Доступные API endpoints:</p>
        <ul>
            <li><code>/api/stats</code> - Общая статистика</li>
            <li><code>/api/users</code> - Список пользователей</li>
            <li><code>/api/user/&lt;user_id&gt;</code> - Статистика пользователя</li>
            <li><code>/api/chats</code> - Список чатов</li>
            <li><code>/api/chat/&lt;chat_id&gt;</code> - Статистика чата</li>
            <li><code>/api/export</code> - Экспорт всех данных (JSON)</li>
        </ul>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    """Главная страница с статистикой"""
    if not bot_instance:
        return "Бот не запущен"
    
    storage = bot_instance.storage
    
    # Получить данные
    overall_stats = storage.get_overall_stats()
    users = [storage.get_user_report(uid) for uid in storage.users.keys()]
    chats = [storage.get_chat_report(cid) for cid in storage.chats.keys()]
    
    # Отфильтровать ошибки
    users = [u for u in users if "error" not in u]
    chats = [c for c in chats if "error" not in c]
    
    return render_template_string(HTML_TEMPLATE,
        overall_stats=overall_stats,
        users=users[:50],  # Ограничиваем для скорости
        chats=chats[:20],
        allowed_users=Config.ALLOWED_USER_IDS,
        detect_forwards=Config.DETECT_FORWARDS,
        detect_copies=Config.DETECT_COPIES,
        detect_screenshots=Config.DETECT_SCREENSHOTS,
        data_file=Config.DATA_FILE
    )

@app.route('/api/stats')
def api_stats():
    """API: общая статистика"""
    if not bot_instance:
        return jsonify({"error": "Бот не запущен"})
    return jsonify(bot_instance.storage.get_overall_stats())

@app.route('/api/users')
def api_users():
    """API: список пользователей"""
    if not bot_instance:
        return jsonify({"error": "Бот не запущен"})
    
    users = []
    for uid in bot_instance.storage.users.keys():
        user_data = bot_instance.storage.get_user_report(uid)
        if "error" not in user_data:
            users.append(user_data)
    
    return jsonify({"users": users, "count": len(users)})

@app.route('/api/user/<int:user_id>')
def api_user(user_id):
    """API: статистика пользователя"""
    if not bot_instance:
        return jsonify({"error": "Бот не запущен"})
    return jsonify(bot_instance.storage.get_user_report(user_id))

@app.route('/api/chats')
def api_chats():
    """API: список чатов"""
    if not bot_instance:
        return jsonify({"error": "Бот не запущен"})
    
    chats = []
    for cid in bot_instance.storage.chats.keys():
        chat_data = bot_instance.storage.get_chat_report(cid)
        if "error" not in chat_data:
            chats.append(chat_data)
    
    return jsonify({"chats": chats, "count": len(chats)})

@app.route('/api/chat/<int:chat_id>')
def api_chat(chat_id):
    """API: статистика чата"""
    if not bot_instance:
        return jsonify({"error": "Бот не запущен"})
    return jsonify(bot_instance.storage.get_chat_report(chat_id))

@app.route('/api/export')
def api_export():
    """API: экспорт всех данных"""
    if not bot_instance:
        return jsonify({"error": "Бот не запущен"})
    
    data = {
        "overall": bot_instance.storage.get_overall_stats(),
        "users": {},
        "chats": {},
        "exported_at": datetime.datetime.now().isoformat()
    }
    
    for uid in bot_instance.storage.users.keys():
        data["users"][uid] = bot_instance.storage.get_user_report(uid)
    
    for cid in bot_instance.storage.chats.keys():
        data["chats"][cid] = bot_instance.storage.get_chat_report(cid)
    
    return jsonify(data)

# ========== ЗАПУСК ==========
def main():
    """Основная функция запуска"""
    global bot_instance
    
    try:
        # Проверка конфигурации
        Config.validate()
        
        # Создание бота
        bot_instance = SilentTelegramBot()
        
        # Запуск Flask в отдельном потоке
        def run_flask():
            app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Запуск бота
        asyncio.run(bot_instance.run())
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
