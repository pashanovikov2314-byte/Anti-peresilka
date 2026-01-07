import logging
import re
import time
import threading
import requests
import hashlib
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict, deque
import json
import os
from typing import Dict, List, Optional, Tuple
import urllib.parse

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", 5000))

SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 600))
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))

# Уровни проверки
VERIFICATION_LEVEL = int(os.environ.get("VERIFICATION_LEVEL", 5))  # 1-10
MAX_BEHAVIOR_HISTORY = 1000
ANALYSIS_DEEP_SCAN = os.environ.get("DEEP_SCAN", "true").lower() == "true"

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

class AdvancedVerificationSystem:
    def __init__(self, level=5):
        self.level = min(max(level, 1), 10)
        self.suspicious_patterns = self._load_patterns()
        self.behavior_baseline = {}
        
    def _load_patterns(self):
        return {
            'phone': [
                r'\+?[78][-\s]?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}',
                r'\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b'
            ],
            'email': [
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            ],
            'crypto': [
                r'\b(0x)?[0-9a-fA-F]{40}\b',  # Ethereum
                r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b',  # Bitcoin
                r'\bT[1-9A-HJ-NP-Za-km-z]{33}\b'  # Tron
            ],
            'credentials': [
                r'(логин|login|пароль|password|pass|pwd)[:\s]*[^\s]{3,}',
                r'(user|username|логин)[:\s]*[^\s]{3,}',
                r'(?:key|ключ)[:\s]*[^\s]{8,}'
            ],
            'ip_address': [
                r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
                r'\b(?:[A-F0-9]{1,4}:){7}[A-F0-9]{1,4}\b'  # IPv6
            ],
            'obfuscated_text': [
                r'[a-zA-Z0-9._%+-]+\[at\][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # email obfuscation
                r'\d{3}\s?[-.]?\s?\d{3}\s?[-.]?\s?\d{4}',  # spaced phone
                r'[a-zA-Z0-9]+\s?[\(\[]\s?(at|dot|точка)\s?[\)\]]\s?[a-zA-Z0-9]+'
            ],
            'code_snippets': [
                r'```[\s\S]*?```',
                r'`[^`\n]+`',
                r'(def|function|class|import|require|select|insert|update|delete)\s+',
                r'(var|let|const|int|string|bool)\s+\w+\s*='
            ],
            'coordinates': [
                r'\b\d{1,3}\.\d{4,},\s*\d{1,3}\.\d{4,}\b',
                r'\b\d{1,3}°\d{1,2}′\d{1,2}″[NS]\s*\d{1,3}°\d{1,2}′\d{1,2}″[EW]\b'
            ],
            'bank_info': [
                r'\b\d{16}\b',  # card number
                r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
                r'(счет|account|card|карта)[:\s№]*[\d\s]{10,}',
                r'\b\d{20}\b'  # account number
            ]
        }
    
    def analyze_text_deep(self, text: str) -> Dict:
        """Углубленный анализ текста"""
        results = {
            'risk_score': 0,
            'detected_patterns': [],
            'extracted_data': [],
            'recommendation': 'NORMAL'
        }
        
        if not text:
            return results
            
        text_lower = text.lower()
        
        # Проверка всех паттернов
        for pattern_type, patterns in self.suspicious_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    matched_text = match.group()
                    if len(matched_text) > 3:  # Игнорируем слишком короткие совпадения
                        results['detected_patterns'].append({
                            'type': pattern_type,
                            'text': matched_text[:50],
                            'position': match.start()
                        })
                        
                        # Расчет риска
                        risk_weights = {
                            'credentials': 30,
                            'bank_info': 25,
                            'crypto': 20,
                            'phone': 15,
                            'email': 10,
                            'ip_address': 15,
                            'coordinates': 10,
                            'code_snippets': 5,
                            'obfuscated_text': 20  # Выше, так как это попытка скрыть
                        }
                        
                        results['risk_score'] += risk_weights.get(pattern_type, 5)
                        
                        # Извлечение данных для отчета
                        if pattern_type in ['phone', 'email', 'crypto', 'ip_address']:
                            results['extracted_data'].append({
                                'type': pattern_type,
                                'value': matched_text,
                                'obfuscated': self._check_obfuscation(matched_text)
                            })
        
        # Дополнительные проверки
        # Проверка на скрытый текст (например, пробелы между буквами)
        if self._check_hidden_text(text):
            results['risk_score'] += 25
            results['detected_patterns'].append({
                'type': 'hidden_text',
                'text': 'Обнаружен скрытый текст',
                'position': 0
            })
        
        # Проверка на кодировки (base64, hex)
        encoded_data = self._check_encoded_data(text)
        if encoded_data:
            results['risk_score'] += 20
            results['detected_patterns'].extend(encoded_data)
        
        # Проверка на структурированные данные (таблицы, списки)
        if self._check_structured_data(text):
            results['risk_score'] += 15
        
        # Нормализация риска (0-100)
        results['risk_score'] = min(100, results['risk_score'] * (self.level / 5))
        
        # Рекомендация на основе уровня риска
        if results['risk_score'] >= 70:
            results['recommendation'] = 'CRITICAL'
        elif results['risk_score'] >= 40:
            results['recommendation'] = 'HIGH'
        elif results['risk_score'] >= 20:
            results['recommendation'] = 'MEDIUM'
        else:
            results['recommendation'] = 'LOW'
        
        return results
    
    def _check_obfuscation(self, text: str) -> bool:
        """Проверка на обфускацию"""
        obfuscation_indicators = [
            r'\[at\]', r'\[dot\]', r'\(at\)', r'\(dot\)',
            r'\s+',  # Множественные пробелы
            r'[a-zA-Z]\.{2,}[a-zA-Z]',  # Много точек между буквами
            r'\d+\s+\d+\s+\d+'  # Разделенные цифры
        ]
        
        for indicator in obfuscation_indicators:
            if re.search(indicator, text):
                return True
        return False
    
    def _check_hidden_text(self, text: str) -> bool:
        """Проверка на скрытый текст (невидимые символы и т.д.)"""
        # Проверка на необычные пробелы
        unusual_spaces = re.findall(r'[\u2000-\u200F\u205F\u3000]', text)
        if unusual_spaces:
            return True
            
        # Проверка на чередование символов (скрытие в обычном тексте)
        if len(text) > 20:
            char_variance = len(set(text.lower())) / len(text)
            if char_variance < 0.3:  # Слишком мало уникальных символов
                return True
        
        return False
    
    def _check_encoded_data(self, text: str) -> List[Dict]:
        """Проверка на закодированные данные"""
        results = []
        
        # Base64
        base64_pattern = r'[A-Za-z0-9+/]{20,}={0,2}'
        base64_matches = re.findall(base64_pattern, text)
        for match in base64_matches:
            if len(match) >= 24:  # Минимальная длина для base64
                try:
                    # Попытка декодирования
                    import base64
                    decoded = base64.b64decode(match + '==').decode('utf-8', errors='ignore')
                    if len(decoded) > 5 and any(c.isprintable() for c in decoded):
                        results.append({
                            'type': 'base64_encoded',
                            'text': match[:30] + '...',
                            'decoded_preview': decoded[:50]
                        })
                except:
                    pass
        
        # Hex
        hex_pattern = r'\b[0-9a-fA-F]{20,}\b'
        hex_matches = re.findall(hex_pattern, text)
        for match in hex_matches:
            if len(match) >= 20:
                try:
                    decoded = bytes.fromhex(match).decode('utf-8', errors='ignore')
                    if len(decoded) > 3:
                        results.append({
                            'type': 'hex_encoded',
                            'text': match[:30] + '...',
                            'decoded_preview': decoded[:50]
                        })
                except:
                    pass
        
        return results
    
    def _check_structured_data(self, text: str) -> bool:
        """Проверка на структурированные данные (таблицы, CSV)"""
        lines = text.split('\n')
        if len(lines) < 3:
            return False
            
        # Проверка на табличный формат
        delimiter_counts = {'|': 0, ',': 0, ';': 0, '\t': 0}
        for line in lines[:10]:  # Проверяем первые 10 строк
            for delim in delimiter_counts:
                delimiter_counts[delim] += line.count(delim)
        
        # Если много разделителей одного типа
        max_count = max(delimiter_counts.values())
        if max_count > len(lines) * 2:  # В среднем 2 разделителя на строку
            return True
            
        # Проверка на регулярные паттерны (даты, числа)
        date_patterns = [
            r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}',
            r'\d{4}[./-]\d{1,2}[./-]\d{1,2}'
        ]
        
        date_count = 0
        for line in lines:
            for pattern in date_patterns:
                if re.search(pattern, line):
                    date_count += 1
                    break
        
        if date_count > len(lines) * 0.5:  # Более 50% строк содержат даты
            return True
            
        return False
    
    def analyze_behavior(self, user_id: int, message_data: Dict) -> Dict:
        """Анализ поведения пользователя"""
        if user_id not in self.behavior_baseline:
            self.behavior_baseline[user_id] = {
                'message_times': deque(maxlen=MAX_BEHAVIOR_HISTORY),
                'message_lengths': deque(maxlen=MAX_BEHAVIOR_HISTORY),
                'activity_hours': defaultdict(int),
                'last_seen': None,
                'first_seen': datetime.now()
            }
        
        baseline = self.behavior_baseline[user_id]
        now = datetime.now()
        
        # Сохраняем данные
        baseline['message_times'].append(now)
        baseline['message_lengths'].append(len(message_data.get('text', '')))
        
        hour = now.hour
        baseline['activity_hours'][hour] += 1
        
        analysis = {
            'behavior_score': 0,
            'anomalies': [],
            'activity_pattern': 'NORMAL'
        }
        
        # Анализ временных паттернов
        if len(baseline['message_times']) > 10:
            # Проверка на всплеск активности
            recent_messages = list(baseline['message_times'])[-10:]
            if len(recent_messages) >= 5:
                time_diffs = []
                for i in range(1, len(recent_messages)):
                    diff = (recent_messages[i] - recent_messages[i-1]).total_seconds()
                    time_diffs.append(diff)
                
                avg_diff = sum(time_diffs) / len(time_diffs)
                if avg_diff < 10:  # Сообщения чаще чем раз в 10 секунд
                    analysis['behavior_score'] += 20
                    analysis['anomalies'].append('message_flood')
            
            # Проверка на необычное время активности
            if hour < 5 or hour > 23:  # Ночное время
                analysis['behavior_score'] += 15
                analysis['anomalies'].append('unusual_hour')
        
        # Анализ длины сообщений
        if len(baseline['message_lengths']) > 5:
            avg_length = sum(baseline['message_lengths']) / len(baseline['message_lengths'])
            current_length = baseline['message_lengths'][-1]
            
            if current_length > avg_length * 3:  # Внезапно длинное сообщение
                analysis['behavior_score'] += 25
                analysis['anomalies'].append('unusually_long')
            elif current_length < 5 and avg_length > 20:  # Внезапно короткое
                analysis['behavior_score'] += 15
                analysis['anomalies'].append('unusually_short')
        
        # Анализ регулярности активности
        if baseline['last_seen']:
            time_since_last = (now - baseline['last_seen']).total_seconds() / 3600  # В часах
            
            if time_since_last > 24 * 7:  # Не был больше недели
                analysis['behavior_score'] += 10
                analysis['anomalies'].append('return_after_long_absence')
            elif time_since_last < 0.1 and len(baseline['message_times']) > 20:  # Слишком часто
                analysis['behavior_score'] += 5
        
        baseline['last_seen'] = now
        
        # Определение паттерна активности
        if analysis['behavior_score'] >= 40:
            analysis['activity_pattern'] = 'SUSPICIOUS'
        elif analysis['behavior_score'] >= 20:
            analysis['activity_pattern'] = 'UNUSUAL'
        
        analysis['behavior_score'] = min(100, analysis['behavior_score'])
        
        return analysis

class TelegramLeakBot:
    def __init__(self):
        self.bot_start_time = datetime.now()
        self.leaks_by_user = defaultdict(list)
        self.user_info = {}
        self.ping_count = 0
        self.last_successful_ping = None
        self.self_ping_enabled = True
        self.is_running = True
        
        # 🔥 Системы проверки
        self.verification_system = AdvancedVerificationSystem(VERIFICATION_LEVEL)
        self.skillup_ultra_mode = False
        self.ultra_detection_level = 5
        
        # Хранилище для глубокого анализа
        self.deep_analysis_cache = {}
        self.behavior_history = defaultdict(lambda: deque(maxlen=MAX_BEHAVIOR_HISTORY))
        
        self.application = Application.builder().token(TOKEN).build()
        
        self.register_handlers()
        self.load_data()
        self.start_background_tasks()
        self.setup_flask_endpoints()
        
        logger.info("🤖 Бот инициализирован с улучшенной системой проверки")
    
    def register_handlers(self):
        # Только базовые команды для неавторизованных
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Приватные команды для авторизованных пользователей
        self.application.add_handler(CommandHandler("leakstats", self.leakstats_command))
        self.application.add_handler(CommandHandler("leakinfo", self.leakinfo_command))
        self.application.add_handler(CommandHandler("pingstatus", self.pingstatus_command))
        self.application.add_handler(CommandHandler("toggleping", self.toggleping_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("skillup", self.skillup_command))
        self.application.add_handler(CommandHandler("deepscan", self.deepscan_command))
        self.application.add_handler(CommandHandler("analyze_user", self.analyze_user_command))
        
        # Обработчик всех сообщений
        self.application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self.monitor_messages))
    
    def setup_flask_endpoints(self):
        @app.route('/')
        def home():
            uptime = (datetime.now() - self.bot_start_time).seconds
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            ultra = "🟢 ВКЛ" if self.skillup_ultra_mode else "🔴 ВЫКЛ"
            deepscan = "🟢 ВКЛ" if ANALYSIS_DEEP_SCAN else "🔴 ВЫКЛ"
            return f"""
            <h1>🤖 LeakTracker Pro</h1>
            <p>✅ Работает! Uptime: {hours}ч {minutes}м</p>
            <p>🔥 SkillUP: {ultra}</p>
            <p>🔍 DeepScan: {deepscan}</p>
            <p>📊 Уровень проверки: {VERIFICATION_LEVEL}/10</p>
            <p>👥 Отслеживаемых пользователей: {len(self.user_info)}</p>
            <p>⚠️ Обнаружено утечек: {sum(len(v) for v in self.leaks_by_user.values())}</p>
            """
        
        @app.route('/health')
        def health():
            return {
                "status": "active",
                "uptime_seconds": (datetime.now() - self.bot_start_time).seconds,
                "ping_count": self.ping_count,
                "leak_count": sum(len(v) for v in self.leaks_by_user.values()),
                "user_count": len(self.user_info),
                "skillup_ultra": self.skillup_ultra_mode,
                "verification_level": VERIFICATION_LEVEL,
                "deep_scan_enabled": ANALYSIS_DEEP_SCAN,
                "allowed_users": len(ALLOWED_USER_IDS)
            }
        
        @app.route('/analysis/<int:user_id>')
        def get_user_analysis(user_id):
            if user_id not in self.user_info:
                return {"error": "User not found"}, 404
            
            leaks = self.leaks_by_user.get(user_id, [])
            user_data = self.user_info[user_id]
            
            # Создаем глубокий анализ
            analysis = {
                "user_info": user_data,
                "leak_count": len(leaks),
                "leaks_by_type": defaultdict(int),
                "risk_score": 0,
                "last_activity": user_data.get('last_seen', 'unknown'),
                "activity_level": "LOW"
            }
            
            for leak in leaks:
                leak_type = leak.get('type', 'UNKNOWN')
                analysis["leaks_by_type"][leak_type] += 1
            
            # Расчет уровня риска
            if len(leaks) > 10:
                analysis["risk_score"] = 80
                analysis["activity_level"] = "CRITICAL"
            elif len(leaks) > 5:
                analysis["risk_score"] = 60
                analysis["activity_level"] = "HIGH"
            elif len(leaks) > 2:
                analysis["risk_score"] = 40
                analysis["activity_level"] = "MEDIUM"
            elif len(leaks) > 0:
                analysis["risk_score"] = 20
                analysis["activity_level"] = "LOW"
            
            return analysis
        
        @app.route('/stats')
        def stats():
            total_leaks = sum(len(v) for v in self.leaks_by_user.values())
            leaks_by_type = defaultdict(int)
            
            for user_leaks in self.leaks_by_user.values():
                for leak in user_leaks:
                    leaks_by_type[leak.get('type', 'UNKNOWN')] += 1
            
            return {
                "total_leaks": total_leaks,
                "unique_users": len(self.leaks_by_user),
                "leaks_by_type": dict(leaks_by_type),
                "top_users": sorted(
                    [(uid, len(leaks)) for uid, leaks in self.leaks_by_user.items()],
                    key=lambda x: x[1],
                    reverse=True
                )[:10]
            }
        
        @app.route('/ping')
        def ping():
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            return {"status": "pong", "ping_number": self.ping_count}
    
    def start_background_tasks(self):
        def self_ping_task():
            while self.is_running:
                if self.self_ping_enabled:
                    self.perform_self_ping()
                time.sleep(SELF_PING_INTERVAL)
        
        def auto_save_task():
            while self.is_running:
                time.sleep(AUTO_SAVE_INTERVAL)
                self.save_data()
                logger.debug("💾 Данные автосохранены")
        
        def cleanup_task():
            while self.is_running:
                time.sleep(3600)  # Каждый час
                self.cleanup_old_data()
        
        threading.Thread(target=self_ping_task, daemon=True).start()
        threading.Thread(target=auto_save_task, daemon=True).start()
        threading.Thread(target=cleanup_task, daemon=True).start()
    
    def perform_self_ping(self):
        try:
            endpoints = [RENDER_URL, f"{RENDER_URL}/health", f"{RENDER_URL}/ping"]
            for endpoint in endpoints:
                response = requests.get(endpoint, timeout=15)
                if response.status_code == 200:
                    logger.debug(f"✅ Пинг {endpoint}")
            
            self.ping_count += 1
            self.last_successful_ping = datetime.now()
            
            if self.ping_count % 50 == 0:
                logger.info(f"✅ Самопинг #{self.ping_count} выполнен")
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка самопинга: {str(e)[:100]}")
    
    def cleanup_old_data(self):
        """Очистка старых данных"""
        cutoff_date = datetime.now() - timedelta(days=30)
        cleaned = 0
        
        for user_id in list(self.leaks_by_user.keys()):
            new_leaks = []
            for leak in self.leaks_by_user[user_id]:
                leak_date = datetime.fromisoformat(leak['timestamp'])
                if leak_date > cutoff_date:
                    new_leaks.append(leak)
                else:
                    cleaned += 1
            
            if new_leaks:
                self.leaks_by_user[user_id] = new_leaks
            else:
                del self.leaks_by_user[user_id]
        
        if cleaned > 0:
            logger.info(f"🧹 Очищено {cleaned} старых записей")
    
    async def is_user_allowed(self, user_id: int) -> bool:
        """Проверка прав доступа"""
        return user_id in ALLOWED_USER_IDS
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        
        if not await self.is_user_allowed(user_id):
            await update.message.reply_text("❌ Бот временно не работает.")
            return
        
        welcome = """
🔒 **LeakTracker Pro** активирован

Доступные команды:
/help - Справка
/leakstats - Статистика утечек
/leakinfo [ID] - Инфо по утечке
/pingstatus - Статус самопинга
/toggleping - Вкл/Выкл самопинг
/status - Общий статус
/clear - Очистить данные
/skillup - Режим повышенной детекции
/deepscan - Глубокий анализ текста
/analyze_user [ID] - Анализ пользователя

🤖 Бот работает в фоновом режиме.
Все обнаруженные утечки будут отправлены вам в ЛС.
        """
        await update.message.reply_text(welcome, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not await self.is_user_allowed(user_id):
            return
        
        help_text = """
📖 **LeakTracker Pro - Помощь**

Бот отслеживает потенциальные утечки информации в чатах:

🔍 **Что детектирует:**
• Пересылки сообщений
• Ссылки на Telegram
• Длинные тексты (копирование)
• Подозрительные медиафайлы
• Конфиденциальные данные (телефоны, emails, крипто)
• Кодированные/скрытые сообщения

⚡ **Режимы работы:**
• NORMAL - Базовая детекция
• ULTRA (/skillup) - Усиленная проверка
• DEEP SCAN - Анализ скрытых данных

📊 **Команды анализа:**
/leakstats - Общая статистика
/leakinfo [ID] - Детали утечки
/analyze_user [ID] - Полный анализ пользователя

🔧 **Управление:**
/status - Статус системы
/toggleping - Управление самопингом
/clear - Очистка данных

🤫 **Примечание:** Бот не отвечает в чатах, только в ЛС.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def deepscan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Активация глубокого анализа"""
        user_id = update.effective_user.id
        if not await self.is_user_allowed(user_id):
            return
        
        global ANALYSIS_DEEP_SCAN
        ANALYSIS_DEEP_SCAN = not ANALYSIS_DEEP_SCAN
        
        status = "активирован" if ANALYSIS_DEEP_SCAN else "деактивирован"
        await update.message.reply_text(f"🔍 Глубокий анализ {status}!")
    
    async def analyze_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Анализ конкретного пользователя"""
        user_id = update.effective_user.id
        if not await self.is_user_allowed(user_id):
            return
        
        if context.args:
            try:
                target_id = int(context.args[0])
            except:
                await update.message.reply_text("❌ Неверный ID пользователя")
                return
        else:
            await update.message.reply_text("❌ Укажите ID пользователя: /analyze_user [ID]")
            return
        
        # Получаем данные пользователя
        user_data = self.user_info.get(target_id)
        if not user_data:
            await update.message.reply_text("❌ Пользователь не найден в базе")
            return
        
        leaks = self.leaks_by_user.get(target_id, [])
        
        # Формируем отчет
        report = f"""
📊 **Анализ пользователя**
        
👤 ID: {target_id}
📛 Имя: {user_data.get('first_name', 'N/A')} {user_data.get('last_name', '')}
📱 Юзернейм: @{user_data.get('username', 'N/A')}
        
📈 **Активность:**
• Сообщений: {user_data.get('message_count', 0)}
• Первый раз: {user_data.get('first_seen', 'N/A')[:16]}
• Последний раз: {user_data.get('last_seen', 'N/A')[:16]}
        
⚠️ **Утечки:**
• Всего: {len(leaks)}
• За последние 7 дней: {len([l for l in leaks if self._is_recent(l, 7)])}
        
🔍 **Типы утечек:"""
        
        # Группируем по типам
        leak_types = defaultdict(int)
        for leak in leaks[-10:]:  # Последние 10
            leak_types[leak.get('type', 'UNKNOWN')] += 1
        
        for ltype, count in leak_types.items():
            report += f"\n• {ltype}: {count}"
        
        if len(leaks) > 0:
            last_leak = leaks[-1]
            report += f"\n\n🕒 **Последняя утечка:**"
            report += f"\nТип: {last_leak.get('type')}"
            report += f"\nВремя: {last_leak.get('timestamp', '')[:16]}"
            report += f"\nЧат: {last_leak.get('chat_title', 'N/A')}"
            report += f"\nРежим: {last_leak.get('detection_mode', 'NORMAL')}"
        
        # Расчет уровня риска
        risk_level = "НИЗКИЙ"
        if len(leaks) > 10:
            risk_level = "КРИТИЧЕСКИЙ 🔴"
        elif len(leaks) > 5:
            risk_level = "ВЫСОКИЙ 🟠"
        elif len(leaks) > 2:
            risk_level = "СРЕДНИЙ 🟡"
        
        report += f"\n\n📊 **Уровень риска:** {risk_level}"
        
        if len(leaks) > 15:
            report += "\n\n🚨 **ВНИМАНИЕ:** Пользователь представляет высокий риск!"
        
        await update.message.reply_text(report, parse_mode='Markdown')
    
    def _is_recent(self, leak, days):
        """Проверка, была ли утечка в последние N дней"""
        try:
            leak_date = datetime.fromisoformat(leak['timestamp'])
            cutoff = datetime.now() - timedelta(days=days)
            return leak_date > cutoff
        except:
            return False
    
    async def monitor_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Мониторинг всех сообщений"""
        msg = update.message
        if not msg or msg.chat.type == 'private':
            return
        
        user_id = msg.from_user.id
        
        # Обновляем информацию о пользователе
        if user_id not in self.user_info:
            self.user_info[user_id] = {
                'username': msg.from_user.username or f"id{user_id}",
                'first_name': msg.from_user.first_name or "",
                'last_name': msg.from_user.last_name or "",
                'last_seen': datetime.now().isoformat(),
                'first_seen': datetime.now().isoformat(),
                'message_count': 0
            }
        else:
            self.user_info[user_id]['last_seen'] = datetime.now().isoformat()
            self.user_info[user_id]['message_count'] = self.user_info[user_id].get('message_count', 0) + 1
        
        # 🔥 Усиленный анализ
        leak_info = self.detect_leak_ultra(msg) if self.skillup_ultra_mode else self.detect_leak(msg)
        
        # Глубокий анализ текста при включенном режиме
        if ANALYSIS_DEEP_SCAN and (msg.text or msg.caption):
            text = msg.text or msg.caption
            deep_analysis = self.verification_system.analyze_text_deep(text)
            
            if deep_analysis['risk_score'] > 30:
                # Добавляем результат глубокого анализа к утечке
                if leak_info:
                    leak_info['deep_analysis'] = deep_analysis
                else:
                    # Создаем новую запись, если обычная детекция ничего не нашла
                    leak_info = {
                        'type': 'DEEP_SCAN_DETECTION',
                        'details': f"Обнаружены подозрительные паттерны: {deep_analysis['recommendation']}",
                        'timestamp': datetime.now().isoformat(),
                        'chat_id': msg.chat.id,
                        'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
                        'message_id': msg.message_id,
                        'detection_mode': 'DEEP_SCAN',
                        'deep_analysis': deep_analysis
                    }
        
        # Анализ поведения
        behavior_data = {
            'text': msg.text or msg.caption or '',
            'has_media': bool(msg.photo or msg.video or msg.document),
            'is_forward': bool(msg.forward_from or msg.forward_from_chat),
            'chat_type': msg.chat.type
        }
        
        behavior_analysis = self.verification_system.analyze_behavior(user_id, behavior_data)
        
        # Если анализ поведения показал аномалии
        if behavior_analysis['behavior_score'] > 40:
            if leak_info:
                leak_info['behavior_anomalies'] = behavior_analysis['anomalies']
                leak_info['behavior_score'] = behavior_analysis['behavior_score']
            else:
                leak_info = {
                    'type': 'BEHAVIOR_ANOMALY',
                    'details': f"Аномалии в поведении: {', '.join(behavior_analysis['anomalies'])}",
                    'timestamp': datetime.now().isoformat(),
                    'chat_id': msg.chat.id,
                    'chat_title': msg.chat.title or f"Чат {msg.chat.id}",
                    'message_id': msg.message_id,
                    'detection_mode': 'BEHAVIOR_ANALYSIS',
                    'behavior_analysis': behavior_analysis
                }
        
        if leak_info:
            await self.handle_leak(user_id, leak_info, msg, context)
    
    # [Остальные методы остаются такими же как в предыдущей версии:
    # detect_leak, detect_leak_ultra, calculate_screenshot_score, 
    # calculate_screenshot_score_ultra, handle_leak, send_leak_alert,
    # leakstats_command, leakinfo_command, pingstatus_command,
    # toggleping_command, status_command, clear_command, skillup_command,
    # save_data, load_data, run]
    
    # Для краткости не дублирую их здесь, но они должны быть в полном коде

def main():
    bot = TelegramLeakBot()
    
    @app.route('/webhook', methods=['POST'])
    def webhook():
        # Обработка вебхуков для Flask
        return {"status": "ok"}
    
    # Запуск Flask в отдельном потоке
    flask_thread = threading.Thread(
        target=lambda: app.run(
            host='0.0.0.0',
            port=PORT,
            debug=False,
            use_reloader=False
        ),
        daemon=True
    )
    flask_thread.start()
    
    # Запуск бота
    bot.application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()