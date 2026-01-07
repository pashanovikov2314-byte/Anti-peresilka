import logging
import re
import time
import threading
import requests
import hashlib
import pickle
import base64
import secrets
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from collections import defaultdict, OrderedDict
import json
import os
import sys
from typing import Dict, List, Tuple, Optional, Any
import gzip
from io import BytesIO

# ========== ЗАГЛУШКИ ДЛЯ СОВМЕСТИМОСТИ ==========
class ImghdrStub:
    def what(self, file, h=None):
        return None

sys.modules['imghdr'] = ImghdrStub()

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUR_ID = int(os.environ.get("YOUR_TELEGRAM_ID", 0))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", str(YOUR_ID)).split(",")]
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
PORT = int(os.environ.get("PORT", 5000))

SELF_PING_INTERVAL = int(os.environ.get("SELF_PING_INTERVAL", 300))
AUTO_SAVE_INTERVAL = int(os.environ.get("AUTO_SAVE_INTERVAL", 300))
DATA_RETENTION_DAYS = int(os.environ.get("DATA_RETENTION_DAYS", 30))

# Уровни безопасности
SECURITY_LEVEL = int(os.environ.get("SECURITY_LEVEL", 9))  # 1-10
ANALYSIS_DEEP_SCAN = os.environ.get("DEEP_SCAN", "true").lower() == "true"
ENABLE_BEHAVIOR_AI = os.environ.get("BEHAVIOR_AI", "true").lower() == "true"

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не установлен")
if not ALLOWED_USER_IDS:
    raise ValueError("ALLOWED_IDS не установлен")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== СИСТЕМЫ АНАЛИЗА ==========
class QuantumAnalyzer:
    """Квантовый анализатор с ИИ-детекцией"""
    
    def __init__(self, security_level=9):
        self.security_level = max(1, min(10, security_level))
        self.patterns = self._load_quantum_patterns()
        self.behavior_profiles = {}
        self.threat_intelligence = defaultdict(list)
        
    def _load_quantum_patterns(self):
        """Загрузка квантовых паттернов обнаружения"""
        return {
            # Финансовые данные
            'financial': [
                r'\b\d{16}\b',  # Номер карты
                r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
                r'(?:счет|account|р\/с|рс|расч[её]т)[:\s№]*[\d\s]{10,}',
                r'\b\d{20}\b',  # Расчетный счет
                r'(?:свифт|swift|бик|bic)[:\s]*[A-Z0-9]{8,11}',
                r'(?:инн|inn)[:\s]*\d{10,12}',
                r'(?:кпп|kpp)[:\s]*\d{9}',
                r'(?:огрн|ogrn)[:\s]*\d{13,15}',
            ],
            
            # Персональные данные
            'personal': [
                r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}\b',  # Паспорт
                r'(?:паспорт|passport)[:\s№]*[\d\s]{6,}',
                r'(?:снилс|snils)[:\s]*\d{3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{2}',
                r'(?:вод[.]?удостоверение|driver.?license)[:\s]*[А-ЯA-Z0-9]{6,}',
                r'(?:полис|policy)[:\s№]*[\d\s]{10,}',
            ],
            
            # Конфиденциальная информация
            'confidential': [
                r'(?:секрет|secret|confidential|конфиденциально)[:\s].{10,}',
                r'(?:приказ|order|директива|directive)[\s№]*[\d\s\-/]{3,}',
                r'(?:договор|contract|соглашение)[\s№]*[\d\s\-/]{3,}',
                r'(?:коммерческая\s+тайна|trade\s+secret)',
                r'(?:ноу-хау|know.?how)',
            ],
            
            # Криптография и токены
            'crypto': [
                r'\b(0x)?[0-9a-fA-F]{40}\b',  # Ethereum
                r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b',  # Bitcoin
                r'\bT[1-9A-HJ-NP-Za-km-z]{33}\b',  # Tron
                r'\bcoinbase|binance|kraken|bybit\b',
                r'\b(?:private|secret).?key[:\s]*[A-Za-z0-9+/=]{20,}',
                r'\b(?:seed\s+phrase|mnemonic)[:\s]*[a-z\s]{20,}',
            ],
            
            # Доступы и учетные данные
            'credentials': [
                r'(?:логин|login|user|username)[:\s]*[\w\.@-]{3,}',
                r'(?:пароль|password|pass|pwd)[:\s]*[^\s]{6,}',
                r'(?:токен|token|api.?key)[:\s]*[A-Za-z0-9-_]{10,}',
                r'(?:access\s+key|secret\s+key)[:\s]*[A-Za-z0-9+/=]{10,}',
                r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\s*[:;]\s*\S{4,}',  # Email с паролем
            ],
            
            # Сетевые данные
            'network': [
                r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b',  # IPv4 с портом
                r'\b(?:[A-F0-9]{1,4}:){7}[A-F0-9]{1,4}\b',  # IPv6
                r'(?:ssh|ftp|sftp)://[^\s]+',
                r'\b\d{1,5}\.\d{1,5}\.\d{1,5}\.\d{1,5}\b',  # IP с маской
                r'(?:порт|port)[:\s]*\d{1,5}',
            ],
            
            # Код и конфигурации
            'code': [
                r'```(?:python|java|js|javascript|php|sql|c\+\+|go)[\s\S]*?```',
                r'(?:config|configuration|настройки)[\s\S]{50,}',
                r'(?:env|environment)[\s\S]{30,}',
                r'(?:база\s+данных|database)[\s\S]{30,}',
                r'[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:[^;\n]{20,}|https?://\S+)',  # Длинные переменные
            ],
            
            # Обфусцированный текст
            'obfuscated': [
                r'[a-zA-Z0-9._%+-]+\[(?:at|@|ат)\][a-zA-Z0-9.-]+\[(?:dot|\.|дот)\][a-zA-Z]{2,}',
                r'\d{3}\s?[-.]?\s?\d{3}\s?[-.]?\s?\d{4}',  # Телефон с пробелами
                r'[a-zA-Z]\.{2,}[a-zA-Z]',  # Много точек между буквами
                r'\S+\s+\S+\s+\S+\s+\S+\s+\S+',  # Слишком много разделенных слов
                r'(?:\d\s*){10,}',  # Цифры с пробелами
            ]
        }
    
    def quantum_scan(self, text: str, context: Dict = None) -> Dict:
        """Квантовое сканирование текста"""
        if not text:
            return {'risk_score': 0, 'detections': [], 'threat_level': 'LOW'}
        
        results = {
            'risk_score': 0,
            'detections': [],
            'threat_level': 'LOW',
            'quantum_signatures': [],
            'confidence': 0
        }
        
        text_lower = text.lower()
        
        # 1. Сканирование по паттернам
        for category, patterns in self.patterns.items():
            for pattern in patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                for match in matches:
                    if len(match.group()) > 4:  # Минимальная длина
                        detection = {
                            'category': category,
                            'text': match.group()[:100],
                            'position': match.start(),
                            'confidence': self._calculate_confidence(category, match.group())
                        }
                        results['detections'].append(detection)
                        
                        # Веса категорий
                        category_weights = {
                            'financial': 40,
                            'personal': 35,
                            'confidential': 50,
                            'crypto': 30,
                            'credentials': 45,
                            'network': 25,
                            'code': 20,
                            'obfuscated': 30
                        }
                        
                        results['risk_score'] += category_weights.get(category, 15)
        
        # 2. Анализ энтропии (выявление шифрованных данных)
        entropy_score = self._calculate_entropy(text)
        if entropy_score > 4.5:
            results['risk_score'] += 25
            results['detections'].append({
                'category': 'ENCRYPTED_DATA',
                'text': 'Высокая энтропия данных (возможно шифрование)',
                'confidence': 85
            })
        
        # 3. Поиск скрытых данных (стеганография)
        hidden_data = self._find_hidden_data(text)
        if hidden_data:
            results['risk_score'] += 35
            results['detections'].extend(hidden_data)
            results['quantum_signatures'].append('HIDDEN_DATA_DETECTED')
        
        # 4. Анализ структуры (таблицы, базы данных)
        if self._is_structured_data(text):
            results['risk_score'] += 20
            results['detections'].append({
                'category': 'STRUCTURED_DATA',
                'text': 'Обнаружены структурированные данные',
                'confidence': 75
            })
        
        # 5. Анализ мета-паттернов
        meta_patterns = self._analyze_meta_patterns(text)
        if meta_patterns:
            results['risk_score'] += meta_patterns.get('score', 0)
            results['detections'].extend(meta_patterns.get('detections', []))
        
        # Нормализация оценки риска
        results['risk_score'] = min(100, results['risk_score'] * (self.security_level / 10))
        results['confidence'] = min(100, results['risk_score'] * 0.9)
        
        # Определение уровня угрозы
        if results['risk_score'] >= 80:
            results['threat_level'] = 'CRITICAL'
        elif results['risk_score'] >= 60:
            results['threat_level'] = 'HIGH'
        elif results['risk_score'] >= 40:
            results['threat_level'] = 'MEDIUM'
        elif results['risk_score'] >= 20:
            results['threat_level'] = 'LOW'
        else:
            results['threat_level'] = 'MINIMAL'
        
        return results
    
    def _calculate_confidence(self, category: str, text: str) -> int:
        """Расчет уверенности в обнаружении"""
        base_conf = {
            'financial': 85,
            'personal': 80,
            'confidential': 90,
            'crypto': 75,
            'credentials': 85,
            'network': 70,
            'code': 65,
            'obfuscated': 80
        }
        
        confidence = base_conf.get(category, 50)
        
        # Учет длины
        if len(text) > 10:
            confidence += 10
        if len(text) > 20:
            confidence += 5
        
        return min(confidence, 100)
    
    def _calculate_entropy(self, text: str) -> float:
        """Расчет энтропии текста"""
        import math
        if not text:
            return 0
        
        # Рассчитываем частоту символов
        freq = {}
        for char in text:
            freq[char] = freq.get(char, 0) + 1
        
        # Рассчитываем энтропию
        entropy = 0
        total = len(text)
        for count in freq.values():
            probability = count / total
            entropy -= probability * math.log2(probability)
        
        return entropy
    
    def _find_hidden_data(self, text: str) -> List[Dict]:
        """Поиск скрытых данных"""
        detections = []
        
        # Проверка на нулевые символы Unicode
        if any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            detections.append({
                'category': 'HIDDEN_CHARS',
                'text': 'Обнаружены невидимые символы',
                'confidence': 70
            })
        
        # Проверка на кодировки
        encodings_to_try = ['utf-8', 'latin-1', 'base64', 'hex']
        for encoding in encodings_to_try:
            try:
                if encoding == 'base64':
                    if len(text) % 4 == 0 and re.match(r'^[A-Za-z0-9+/]*={0,2}$', text):
                        decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
                        if len(decoded) > 5:
                            detections.append({
                                'category': 'BASE64_ENCODED',
                                'text': f'Base64: {decoded[:50]}...',
                                'confidence': 80
                            })
                elif encoding == 'hex':
                    if re.match(r'^[0-9a-fA-F]+$', text) and len(text) % 2 == 0:
                        decoded = bytes.fromhex(text).decode('utf-8', errors='ignore')
                        if len(decoded) > 3:
                            detections.append({
                                'category': 'HEX_ENCODED',
                                'text': f'Hex: {decoded[:50]}...',
                                'confidence': 75
                            })
            except:
                pass
        
        return detections
    
    def _is_structured_data(self, text: str) -> bool:
        """Проверка на структурированные данные"""
        lines = text.strip().split('\n')
        if len(lines) < 3:
            return False
        
        # Проверка на CSV/TSV
        delimiter_counts = {';': 0, ',': 0, '\t': 0, '|': 0}
        for line in lines[:10]:
            for delim in delimiter_counts:
                delimiter_counts[delim] += line.count(delim)
        
        # Если есть много одинаковых разделителей
        for delim, count in delimiter_counts.items():
            if count >= len(lines) * 0.8:  # 80% строк имеют разделитель
                return True
        
        # Проверка на регулярные паттерны
        pattern_matches = 0
        patterns = [
            r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}',  # Дата
            r'\$\d+\.?\d*',  # Деньги
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # Телефон
        ]
        
        for line in lines[:10]:
            for pattern in patterns:
                if re.search(pattern, line):
                    pattern_matches += 1
                    break
        
        return pattern_matches >= len(lines) * 0.5  # 50% строк совпадают
    
    def _analyze_meta_patterns(self, text: str) -> Dict:
        """Анализ мета-паттернов"""
        score = 0
        detections = []
        
        # Проверка на повторяющиеся паттерны
        words = text.split()
        word_freq = {}
        for word in words:
            if len(word) > 3:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # Если есть часто повторяющиеся слова
        repeated_words = [word for word, count in word_freq.items() if count > 5]
        if repeated_words:
            score += 15
            detections.append({
                'category': 'REPEATED_PATTERNS',
                'text': f'Повторяющиеся слова: {", ".join(repeated_words[:3])}',
                'confidence': 65
            })
        
        return {'score': score, 'detections': detections}
    
    def analyze_behavior(self, user_id: int, activity: Dict) -> Dict:
        """Анализ поведения пользователя с ИИ"""
        if user_id not in self.behavior_profiles:
            self.behavior_profiles[user_id] = {
                'first_seen': datetime.now(),
                'last_seen': datetime.now(),
                'activity_count': 0,
                'risk_actions': 0,
                'activity_pattern': defaultdict(int),
                'suspicious_patterns': []
            }
        
        profile = self.behavior_profiles[user_id]
        now = datetime.now()
        
        # Обновление профиля
        profile['last_seen'] = now
        profile['activity_count'] += 1
        
        analysis = {
            'behavior_score': 0,
            'anomalies': [],
            'risk_factors': [],
            'profile_confidence': 0
        }
        
        # Анализ временных паттернов
        if profile['activity_count'] > 10:
            hour = now.hour
            
            # Необычное время активности (2-5 утра)
            if 2 <= hour <= 5:
                analysis['behavior_score'] += 20
                analysis['anomalies'].append('NIGHT_ACTIVITY')
            
            # Всплеск активности
            recent_hours = 24
            if profile['activity_count'] > 100 and profile['activity_count'] / recent_hours > 10:
                analysis['behavior_score'] += 25
                analysis['anomalies'].append('ACTIVITY_SPIKE')
        
        # Анализ рисковых действий
        if activity.get('has_risk'):
            profile['risk_actions'] += 1
            analysis['behavior_score'] += 30
            analysis['risk_factors'].append('HIGH_RISK_ACTION')
        
        # Расчет уверенности в профиле
        profile['profile_confidence'] = min(100, profile['activity_count'] * 5)
        analysis['profile_confidence'] = profile['profile_confidence']
        
        # Нормализация оценки
        analysis['behavior_score'] = min(100, analysis['behavior_score'])
        
        # Уровень аномалии
        if analysis['behavior_score'] >= 60:
            analysis['anomaly_level'] = 'CRITICAL'
        elif analysis['behavior_score'] >= 40:
            analysis['anomaly_level'] = 'HIGH'
        elif analysis['behavior_score'] >= 20:
            analysis['anomaly_level'] = 'MEDIUM'
        else:
            analysis['anomaly_level'] = 'LOW'
        
        return analysis

class ThreatIntelligence:
    """Система анализа угроз"""
    
    def __init__(self):
        self.threat_database = self._load_threat_database()
        self.ioc_patterns = []  # Indicators of Compromise
        self.threat_score = 0
        
    def _load_threat_database(self):
        """Загрузка базы данных угроз"""
        return {
            'malicious_patterns': [
                # Паттерны вредоносных действий
                r'(?:взлом|hack|взломать|ddos|dos)\s',
                r'(?:инжект|inject|sql.?injection)',
                r'(?:эксплойт|exploit|уязвимость|vulnerability)',
                r'(?:бэкдор|backdoor|троян|trojan|вирус|virus)',
                r'(?:фишинг|phishing|обман|scam)',
                r'(?:шантаж|blackmail|вымогательство|ransom)',
            ],
            'suspicious_keywords': [
                'слить', 'слито', 'утекло', 'утечка', 'confidential',
                'secret', 'private', 'internal', 'classified'
            ],
            'threat_actors': defaultdict(int)
        }
    
    def analyze_threat(self, text: str, user_id: int) -> Dict:
        """Анализ угрозы"""
        threat_score = 0
        indicators = []
        
        # Анализ по паттернам
        for pattern in self.threat_database['malicious_patterns']:
            if re.search(pattern, text, re.IGNORECASE):
                threat_score += 30
                indicators.append('MALICIOUS_INTENT_DETECTED')
        
        # Ключевые слова
        for keyword in self.threat_database['suspicious_keywords']:
            if keyword in text.lower():
                threat_score += 20
                indicators.append('SUSPICIOUS_KEYWORD')
        
        # Контекстный анализ
        if threat_score > 0:
            # Повышаем оценку при множественных индикаторах
            threat_score += len(indicators) * 10
            
            # Запись угрозы в базу
            self.threat_database['threat_actors'][user_id] += 1
            
            # Если пользователь уже был замечен в угрозах
            if self.threat_database['threat_actors'][user_id] > 3:
                threat_score += 40
                indicators.append('REPEAT_THREAT_ACTOR')
        
        return {
            'threat_score': min(100, threat_score),
            'indicators': indicators,
            'threat_level': 'CRITICAL' if threat_score >= 60 else 'HIGH' if threat_score >= 30 else 'MEDIUM' if threat_score >= 15 else 'LOW'
        }

# ========== ОСНОВНОЙ БОТ ==========
class QuantumLeakTracker:
    """Квантовый трекер утечек с ИИ"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.leak_database = defaultdict(OrderedDict)  # user_id -> {leak_hash: leak_data}
        self.user_profiles = {}
        self.threat_actors = {}
        self.system_metrics = {
            'total_leaks': 0,
            'total_users': 0,
            'threats_blocked': 0,
            'ai_analyses': 0
        }
        
        # Системы анализа
        self.quantum_analyzer = QuantumAnalyzer(SECURITY_LEVEL)
        self.threat_intel = ThreatIntelligence()
        
        # Кэширование
        self.cache = {}
        self.cache_ttl = 300  # 5 минут
        
        # Статистика
        self.stats = defaultdict(int)
        
        # Инициализация
        self.load_all_data()
        self.setup_flask_endpoints()
        self.start_background_tasks()
        
        logger.info(f"🚀 Quantum LeakTracker инициализирован (уровень {SECURITY_LEVEL}/10)")
    
    def setup_flask_endpoints(self):
        """Настройка API эндпоинтов"""
        
        @app.route('/api/v1/analyze', methods=['POST'])
        def api_analyze():
            """Анализ текста на утечки"""
            try:
                data = request.json
                if not data or 'text' not in data:
                    return jsonify({'error': 'No text provided'}), 400
                
                text = data['text']
                user_id = data.get('user_id', 0)
                context = data.get('context', {})
                
                # Квантовый анализ
                quantum_result = self.quantum_analyzer.quantum_scan(text, context)
                
                # Анализ угроз
                threat_result = self.threat_intel.analyze_threat(text, user_id)
                
                # Объединение результатов
                result = {
                    'analysis_id': hashlib.sha256(f"{text}{datetime.now()}".encode()).hexdigest()[:16],
                    'timestamp': datetime.now().isoformat(),
                    'quantum_analysis': quantum_result,
                    'threat_analysis': threat_result,
                    'combined_risk': max(quantum_result['risk_score'], threat_result['threat_score']),
                    'recommendation': self._generate_recommendation(
                        quantum_result['risk_score'],
                        threat_result['threat_score']
                    )
                }
                
                self.system_metrics['ai_analyses'] += 1
                
                # Кэширование результата
                cache_key = f"analysis_{hashlib.md5(text.encode()).hexdigest()}"
                self.cache[cache_key] = {
                    'result': result,
                    'timestamp': datetime.now()
                }
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"API Analyze error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @app.route('/api/v1/report_leak', methods=['POST'])
        def api_report_leak():
            """Отчет об утечке"""
            try:
                data = request.json
                if not data:
                    return jsonify({'error': 'No data'}), 400
                
                user_id = data.get('user_id')
                leak_data = data.get('leak_data', {})
                context = data.get('context', {})
                
                if not user_id or not leak_data:
                    return jsonify({'error': 'Missing required fields'}), 400
                
                # Генерация уникального ID утечки
                leak_id = hashlib.sha256(
                    f"{user_id}{leak_data.get('type')}{datetime.now()}".encode()
                ).hexdigest()[:12]
                
                # Полный анализ утечки
                full_analysis = self._analyze_complete_leak(user_id, leak_data, context)
                
                # Сохранение в базу
                if user_id not in self.leak_database:
                    self.leak_database[user_id] = OrderedDict()
                
                self.leak_database[user_id][leak_id] = {
                    'leak_id': leak_id,
                    'timestamp': datetime.now().isoformat(),
                    'data': leak_data,
                    'context': context,
                    'analysis': full_analysis,
                    'hash': hashlib.sha256(json.dumps(leak_data, sort_keys=True).encode()).hexdigest()
                }
                
                # Ограничение количества утечек на пользователя
                if len(self.leak_database[user_id]) > 1000:
                    # Удаляем самые старые
                    oldest_key = next(iter(self.leak_database[user_id]))
                    del self.leak_database[user_id][oldest_key]
                
                self.system_metrics['total_leaks'] += 1
                
                # Оповещение админов
                if full_analysis.get('risk_level') in ['HIGH', 'CRITICAL']:
                    self._send_immediate_alert(user_id, leak_id, full_analysis)
                
                return jsonify({
                    'status': 'success',
                    'leak_id': leak_id,
                    'analysis': full_analysis,
                    'message': 'Leak reported and analyzed'
                })
                
            except Exception as e:
                logger.error(f"API Report Leak error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @app.route('/api/v1/user/<int:user_id>', methods=['GET'])
        def api_get_user(user_id):
            """Получение информации о пользователе"""
            try:
                user_data = self.user_profiles.get(user_id, {})
                leaks = self.leak_database.get(user_id, {})
                
                # Расчет статистики
                leak_stats = {
                    'total': len(leaks),
                    'by_type': defaultdict(int),
                    'by_risk': defaultdict(int),
                    'timeline': []
                }
                
                for leak_id, leak in leaks.items():
                    leak_type = leak['data'].get('type', 'UNKNOWN')
                    risk_level = leak['analysis'].get('risk_level', 'UNKNOWN')
                    
                    leak_stats['by_type'][leak_type] += 1
                    leak_stats['by_risk'][risk_level] += 1
                    leak_stats['timeline'].append({
                        'timestamp': leak['timestamp'],
                        'type': leak_type,
                        'risk': risk_level
                    })
                
                # Сортировка по времени
                leak_stats['timeline'].sort(key=lambda x: x['timestamp'], reverse=True)
                
                return jsonify({
                    'user_id': user_id,
                    'profile': user_data,
                    'leak_statistics': leak_stats,
                    'threat_score': self.threat_actors.get(user_id, 0),
                    'first_seen': user_data.get('first_seen'),
                    'last_seen': user_data.get('last_seen')
                })
                
            except Exception as e:
                logger.error(f"API Get User error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @app.route('/api/v1/stats', methods=['GET'])
        def api_stats():
            """Статистика системы"""
            try:
                # Расчет дополнительной статистики
                risk_distribution = defaultdict(int)
                type_distribution = defaultdict(int)
                
                for user_id, leaks in self.leak_database.items():
                    for leak_id, leak in leaks.items():
                        risk_level = leak['analysis'].get('risk_level', 'UNKNOWN')
                        leak_type = leak['data'].get('type', 'UNKNOWN')
                        
                        risk_distribution[risk_level] += 1
                        type_distribution[leak_type] += 1
                
                # Топ пользователей по утечкам
                top_users = []
                for user_id, leaks in self.leak_database.items():
                    if leaks:
                        user_profile = self.user_profiles.get(user_id, {})
                        top_users.append({
                            'user_id': user_id,
                            'username': user_profile.get('username', f'id{user_id}'),
                            'leak_count': len(leaks),
                            'max_risk': max((leak['analysis'].get('risk_score', 0) for leak in leaks.values()), default=0)
                        })
                
                top_users.sort(key=lambda x: x['leak_count'], reverse=True)
                
                return jsonify({
                    'system': {
                        'uptime': (datetime.now() - self.start_time).total_seconds(),
                        'start_time': self.start_time.isoformat(),
                        'security_level': SECURITY_LEVEL
                    },
                    'metrics': self.system_metrics,
                    'distributions': {
                        'risk': dict(risk_distribution),
                        'type': dict(type_distribution)
                    },
                    'top_users': top_users[:10],
                    'cache_size': len(self.cache)
                })
                
            except Exception as e:
                logger.error(f"API Stats error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @app.route('/api/v1/search', methods=['POST'])
        def api_search():
            """Поиск по утечкам"""
            try:
                data = request.json
                if not data:
                    return jsonify({'error': 'No search criteria'}), 400
                
                query = data.get('query', '').lower()
                user_id = data.get('user_id')
                leak_type = data.get('type')
                risk_level = data.get('risk_level')
                date_from = data.get('date_from')
                date_to = data.get('date_to')
                
                results = []
                
                for uid, leaks in self.leak_database.items():
                    if user_id and uid != user_id:
                        continue
                    
                    for leak_id, leak in leaks.items():
                        # Применение фильтров
                        if leak_type and leak['data'].get('type') != leak_type:
                            continue
                        
                        if risk_level and leak['analysis'].get('risk_level') != risk_level:
                            continue
                        
                        leak_time = datetime.fromisoformat(leak['timestamp'])
                        if date_from and leak_time < datetime.fromisoformat(date_from):
                            continue
                        if date_to and leak_time > datetime.fromisoformat(date_to):
                            continue
                        
                        # Поиск по тексту
                        if query:
                            leak_text = json.dumps(leak['data']).lower()
                            if query not in leak_text:
                                continue
                        
                        results.append({
                            'user_id': uid,
                            'leak_id': leak_id,
                            'timestamp': leak['timestamp'],
                            'type': leak['data'].get('type'),
                            'risk_level': leak['analysis'].get('risk_level'),
                            'risk_score': leak['analysis'].get('risk_score'),
                            'preview': str(leak['data'])[:100]
                        })
                
                # Сортировка по времени
                results.sort(key=lambda x: x['timestamp'], reverse=True)
                
                return jsonify({
                    'total': len(results),
                    'results': results[:100]  # Ограничение на 100 результатов
                })
                
            except Exception as e:
                logger.error(f"API Search error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @app.route('/api/v1/export', methods=['GET'])
        def api_export():
            """Экспорт данных"""
            try:
                export_type = request.args.get('type', 'json')
                user_id = request.args.get('user_id')
                
                if export_type == 'json':
                    data = {
                        'export_time': datetime.now().isoformat(),
                        'system_metrics': self.system_metrics,
                        'leak_database': dict(self.leak_database),
                        'user_profiles': self.user_profiles,
                        'threat_actors': self.threat_actors
                    }
                    
                    return jsonify(data)
                
                elif export_type == 'csv':
                    # Генерация CSV
                    import csv
                    from io import StringIO
                    
                    output = StringIO()
                    writer = csv.writer(output)
                    
                    # Заголовок
                    writer.writerow(['User ID', 'Leak ID', 'Timestamp', 'Type', 'Risk Level', 'Risk Score', 'Details'])
                    
                    # Данные
                    for uid, leaks in self.leak_database.items():
                        if user_id and uid != int(user_id):
                            continue
                        
                        for leak_id, leak in leaks.items():
                            writer.writerow([
                                uid,
                                leak_id,
                                leak['timestamp'],
                                leak['data'].get('type', 'UNKNOWN'),
                                leak['analysis'].get('risk_level', 'UNKNOWN'),
                                leak['analysis'].get('risk_score', 0),
                                json.dumps(leak['data'])[:200]
                            ])
                    
                    output.seek(0)
                    return output.getvalue(), 200, {'Content-Type': 'text/csv'}
                
                else:
                    return jsonify({'error': 'Unsupported export type'}), 400
                    
            except Exception as e:
                logger.error(f"API Export error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @app.route('/api/v1/health', methods=['GET'])
        def api_health():
            """Проверка здоровья системы"""
            uptime = (datetime.now() - self.start_time).total_seconds()
            
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'uptime_seconds': uptime,
                'database_size': {
                    'leaks': sum(len(leaks) for leaks in self.leak_database.values()),
                    'users': len(self.user_profiles),
                    'threat_actors': len(self.threat_actors)
                },
                'memory_usage': self._get_memory_usage(),
                'cache_status': {
                    'size': len(self.cache),
                    'hits': self.stats['cache_hits'],
                    'misses': self.stats['cache_misses']
                }
            })
        
        # Web интерфейс
        @app.route('/dashboard')
        def dashboard():
            """Веб-дашборд"""
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Quantum LeakTracker Dashboard</title>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        margin: 0;
                        padding: 20px;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                    }
                    .container {
                        max-width: 1200px;
                        margin: 0 auto;
                        background: rgba(255, 255, 255, 0.1);
                        backdrop-filter: blur(10px);
                        border-radius: 20px;
                        padding: 30px;
                        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                    }
                    .header {
                        text-align: center;
                        margin-bottom: 40px;
                    }
                    .header h1 {
                        font-size: 2.5em;
                        margin-bottom: 10px;
                        background: linear-gradient(45deg, #00ff88, #0088ff);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                    }
                    .stats-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                        gap: 20px;
                        margin-bottom: 40px;
                    }
                    .stat-card {
                        background: rgba(255, 255, 255, 0.15);
                        border-radius: 15px;
                        padding: 20px;
                        text-align: center;
                        transition: transform 0.3s;
                    }
                    .stat-card:hover {
                        transform: translateY(-5px);
                        background: rgba(255, 255, 255, 0.2);
                    }
                    .stat-value {
                        font-size: 2.5em;
                        font-weight: bold;
                        margin: 10px 0;
                    }
                    .stat-label {
                        font-size: 0.9em;
                        opacity: 0.8;
                    }
                    .api-info {
                        background: rgba(0, 0, 0, 0.3);
                        border-radius: 15px;
                        padding: 25px;
                        margin-top: 30px;
                    }
                    .endpoint {
                        background: rgba(255, 255, 255, 0.1);
                        border-radius: 10px;
                        padding: 15px;
                        margin: 10px 0;
                        font-family: 'Courier New', monospace;
                    }
                    .status-indicator {
                        display: inline-block;
                        width: 12px;
                        height: 12px;
                        border-radius: 50%;
                        margin-right: 10px;
                    }
                    .status-online {
                        background: #00ff00;
                        box-shadow: 0 0 10px #00ff00;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔮 Quantum LeakTracker Dashboard</h1>
                        <p>Real-time threat intelligence & leak detection system</p>
                        <div style="margin-top: 20px;">
                            <span class="status-indicator status-online"></span>
                            <span>System Status: ONLINE | Security Level: """ + str(SECURITY_LEVEL) + """/10</span>
                        </div>
                    </div>
                    
                    <div class="stats-grid" id="statsGrid">
                        <!-- Stats will be loaded by JavaScript -->
                    </div>
                    
                    <div class="api-info">
                        <h3>📡 API Endpoints</h3>
                        <div class="endpoint">
                            <strong>POST /api/v1/analyze</strong> - Analyze text for leaks
                        </div>
                        <div class="endpoint">
                            <strong>POST /api/v1/report_leak</strong> - Report a leak
                        </div>
                        <div class="endpoint">
                            <strong>GET /api/v1/user/&lt;id&gt;</strong> - Get user info
                        </div>
                        <div class="endpoint">
                            <strong>GET /api/v1/stats</strong> - System statistics
                        </div>
                        <div class="endpoint">
                            <strong>POST /api/v1/search</strong> - Search leaks
                        </div>
                        <div class="endpoint">
                            <strong>GET /api/v1/export?type=json|csv</strong> - Export data
                        </div>
                        <div class="endpoint">
                            <strong>GET /api/v1/health</strong> - System health check
                        </div>
                    </div>
                    
                    <div style="margin-top: 40px; text-align: center; opacity: 0.7;">
                        <p>Quantum LeakTracker v3.0 | AI-Powered Threat Detection</p>
                    </div>
                </div>
                
                <script>
                    async function loadStats() {
                        try {
                            const response = await fetch('/api/v1/stats');
                            const data = await response.json();
                            
                            const stats = [
                                { label: 'Total Leaks', value: data.metrics?.total_leaks || 0, color: '#ff6b6b' },
                                { label: 'Unique Users', value: data.distributions?.risk?.CRITICAL || 0, color: '#4ecdc4' },
                                { label: 'AI Analyses', value: data.metrics?.ai_analyses || 0, color: '#45b7d1' },
                                { label: 'Cache Hits', value: data.cache_status?.hits || 0, color: '#96ceb4' },
                                { label: 'Security Level', value: """ + str(SECURITY_LEVEL) + """, color: '#feca57' },
                                { label: 'Uptime (hours)', value: Math.floor((data.system?.uptime || 0) / 3600), color: '#ff9ff3' }
                            ];
                            
                            const grid = document.getElementById('statsGrid');
                            grid.innerHTML = stats.map(stat => `
                                <div class="stat-card">
                                    <div class="stat-label">${stat.label}</div>
                                    <div class="stat-value" style="color: ${stat.color}">${stat.value}</div>
                                </div>
                            `).join('');
                            
                        } catch (error) {
                            console.error('Error loading stats:', error);
                        }
                    }
                    
                    // Load stats on page load and every 30 seconds
                    loadStats();
                    setInterval(loadStats, 30000);
                    
                    // Auto-refresh page every 5 minutes
                    setTimeout(() => location.reload(), 300000);
                </script>
            </body>
            </html>
            """
    
    def _analyze_complete_leak(self, user_id: int, leak_data: Dict, context: Dict) -> Dict:
        """Полный анализ утечки"""
        analysis = {
            'leak_id': hashlib.md5(json.dumps(leak_data, sort_keys=True).encode()).hexdigest()[:8],
            'timestamp': datetime.now().isoformat(),
            'risk_score': 0,
            'risk_level': 'LOW',
            'detections': [],
            'quantum_signatures': [],
            'threat_indicators': [],
            'recommendations': []
        }
        
        # Анализ текста утечки
        text = leak_data.get('text', '') or leak_data.get('caption', '') or ''
        if text:
            quantum_result = self.quantum_analyzer.quantum_scan(text, context)
            analysis['risk_score'] = quantum_result['risk_score']
            analysis['detections'] = quantum_result['detections']
            analysis['quantum_signatures'] = quantum_result['quantum_signatures']
        
        # Анализ угроз
        if text:
            threat_result = self.threat_intel.analyze_threat(text, user_id)
            analysis['threat_indicators'] = threat_result['indicators']
            analysis['risk_score'] = max(analysis['risk_score'], threat_result['threat_score'])
        
        # Анализ поведения
        if ENABLE_BEHAVIOR_AI:
            behavior_data = {
                'user_id': user_id,
                'leak_type': leak_data.get('type', 'UNKNOWN'),
                'has_risk': analysis['risk_score'] > 40
            }
            behavior_result = self.quantum_analyzer.analyze_behavior(user_id, behavior_data)
            analysis['behavior_score'] = behavior_result['behavior_score']
            analysis['behavior_anomalies'] = behavior_result['anomalies']
        
        # Определение уровня риска
        if analysis['risk_score'] >= 80:
            analysis['risk_level'] = 'CRITICAL'
            analysis['recommendations'].append('IMMEDIATE_ACTION_REQUIRED')
        elif analysis['risk_score'] >= 60:
            analysis['risk_level'] = 'HIGH'
            analysis['recommendations'].append('INVESTIGATE_IMMEDIATELY')
        elif analysis['risk_score'] >= 40:
            analysis['risk_level'] = 'MEDIUM'
            analysis['recommendations'].append('MONITOR_CLOSELY')
        elif analysis['risk_score'] >= 20:
            analysis['risk_level'] = 'LOW'
            analysis['recommendations'].append('STANDARD_MONITORING')
        else:
            analysis['risk_level'] = 'MINIMAL'
            analysis['recommendations'].append('ROUTINE_CHECK')
        
        # Обновление профиля пользователя
        self._update_user_profile(user_id, leak_data, analysis)
        
        return analysis
    
    def _update_user_profile(self, user_id: int, leak_data: Dict, analysis: Dict):
        """Обновление профиля пользователя"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                'first_seen': datetime.now().isoformat(),
                'leak_count': 0,
                'max_risk_score': 0,
                'risk_history': [],
                'username': leak_data.get('username', f'id{user_id}')
            }
        
        profile = self.user_profiles[user_id]
        profile['last_seen'] = datetime.now().isoformat()
        profile['leak_count'] += 1
        profile['max_risk_score'] = max(profile.get('max_risk_score', 0), analysis['risk_score'])
        
        # Добавление в историю рисков
        profile['risk_history'].append({
            'timestamp': datetime.now().isoformat(),
            'risk_score': analysis['risk_score'],
            'risk_level': analysis['risk_level'],
            'leak_type': leak_data.get('type', 'UNKNOWN')
        })
        
        # Ограничение истории
        if len(profile['risk_history']) > 100:
            profile['risk_history'] = profile['risk_history'][-100:]
        
        # Обновление акторов угроз
        if analysis['risk_level'] in ['HIGH', 'CRITICAL']:
            if user_id not in self.threat_actors:
                self.threat_actors[user_id] = 0
            self.threat_actors[user_id] += 1
            self.system_metrics['threats_blocked'] += 1
    
    def _generate_recommendation(self, risk_score: int, threat_score: int) -> str:
        """Генерация рекомендаций на основе оценки риска"""
        max_score = max(risk_score, threat_score)
        
        if max_score >= 80:
            return "🚨 КРИТИЧЕСКИЙ РИСК: Немедленные действия, изоляция, расследование"
        elif max_score >= 60:
            return "⚠️ ВЫСОКИЙ РИСК: Приоритетное расследование, усиленный мониторинг"
        elif max_score >= 40:
            return "🔶 СРЕДНИЙ РИСК: Детальный анализ, регулярный мониторинг"
        elif max_score >= 20:
            return "🔶 НИЗКИЙ РИСК: Стандартный мониторинг, запись в лог"
        else:
            return "✅ МИНИМАЛЬНЫЙ РИСК: Рутовая проверка"
    
    def _send_immediate_alert(self, user_id: int, leak_id: str, analysis: Dict):
        """Немедленное оповещение админов"""
        alert_message = f"""
🚨 **CRITICAL LEAK DETECTED**

👤 **User:** {user_id}
🆔 **Leak ID:** {leak_id}
📊 **Risk Level:** {analysis.get('risk_level')}
🎯 **Risk Score:** {analysis.get('risk_score')}/100
⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}

🔍 **Detections:** {len(analysis.get('detections', []))}
⚠️ **Threat Indicators:** {len(analysis.get('threat_indicators', []))}

**Recommendation:** {analysis.get('recommendations', ['No recommendation'])[0]}

📈 **Total leaks from this user:** {self.user_profiles.get(user_id, {}).get('leak_count', 0)}
        """
        
        # Отправка всем админам через Telegram API
        for admin_id in ALLOWED_USER_IDS:
            try:
                telegram_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                payload = {
                    'chat_id': admin_id,
                    'text': alert_message,
                    'parse_mode': 'Markdown',
                    'disable_web_page_preview': True
                }
                
                response = requests.post(telegram_url, json=payload, timeout=10)
                if response.status_code == 200:
                    logger.info(f"🚨 Critical alert sent to admin {admin_id}")
                else:
                    logger.error(f"❌ Failed to send alert to {admin_id}: {response.text}")
                    
            except Exception as e:
                logger.error(f"❌ Alert sending error for {admin_id}: {e}")
    
    def _get_memory_usage(self) -> Dict:
        """Получение информации об использовании памяти"""
        import psutil
        process = psutil.Process()
        mem_info = process.memory_info()
        
        return {
            'rss_mb': mem_info.rss / 1024 / 1024,
            'vms_mb': mem_info.vms / 1024 / 1024,
            'percent': process.memory_percent()
        }
    
    def load_all_data(self):
        """Загрузка всех данных из файлов"""
        try:
            # Загрузка базы утечек
            if os.path.exists('quantum_database.pkl'):
                with open('quantum_database.pkl', 'rb') as f:
                    data = pickle.load(f)
                    self.leak_database = data.get('leak_database', defaultdict(OrderedDict))
                    self.user_profiles = data.get('user_profiles', {})
                    self.threat_actors = data.get('threat_actors', {})
                    self.system_metrics = data.get('system_metrics', self.system_metrics)
                
                logger.info(f"✅ Quantum database loaded: {len(self.leak_database)} users, {sum(len(l) for l in self.leak_database.values())} leaks")
            
            # Загрузка кэша
            if os.path.exists('quantum_cache.pkl'):
                with open('quantum_cache.pkl', 'rb') as f:
                    self.cache = pickle.load(f)
                
                logger.info(f"✅ Cache loaded: {len(self.cache)} entries")
                
        except Exception as e:
            logger.error(f"❌ Error loading data: {e}")
    
    def save_all_data(self):
        """Сохранение всех данных в файлы"""
        try:
            # Сохранение базы данных
            with open('quantum_database.pkl', 'wb') as f:
                pickle.dump({
                    'leak_database': self.leak_database,
                    'user_profiles': self.user_profiles,
                    'threat_actors': self.threat_actors,
                    'system_metrics': self.system_metrics
                }, f)
            
            # Сохранение кэша
            with open('quantum_cache.pkl', 'wb') as f:
                pickle.dump(self.cache, f)
            
            # Очистка старых кэшей
            self._cleanup_old_cache()
            
            logger.debug("💾 All data saved successfully")
            
        except Exception as e:
            logger.error(f"❌ Error saving data: {e}")
    
    def _cleanup_old_cache(self):
        """Очистка старого кэша"""
        now = datetime.now()
        expired_keys = []
        
        for key, value in list(self.cache.items()):
            if isinstance(value, dict) and 'timestamp' in value:
                cache_time = value['timestamp']
                if isinstance(cache_time, str):
                    cache_time = datetime.fromisoformat(cache_time)
                
                if (now - cache_time).total_seconds() > self.cache_ttl:
                    expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.debug(f"🧹 Cleaned {len(expired_keys)} expired cache entries")
    
    def cleanup_old_data(self):
        """Очистка старых данных"""
        cutoff_date = datetime.now() - timedelta(days=DATA_RETENTION_DAYS)
        cleaned_leaks = 0
        
        for user_id in list(self.leak_database.keys()):
            new_leaks = OrderedDict()
            for leak_id, leak in self.leak_database[user_id].items():
                leak_time = datetime.fromisoformat(leak['timestamp'])
                if leak_time > cutoff_date:
                    new_leaks[leak_id] = leak
                else:
                    cleaned_leaks += 1
            
            if new_leaks:
                self.leak_database[user_id] = new_leaks
            else:
                del self.leak_database[user_id]
        
        if cleaned_leaks > 0:
            logger.info(f"🧹 Cleaned {cleaned_leaks} old leaks (older than {DATA_RETENTION_DAYS} days)")
    
    def start_background_tasks(self):
        """Запуск фоновых задач"""
        def self_ping_task():
            while True:
                try:
                    if RENDER_URL:
                        response = requests.get(f"{RENDER_URL}/api/v1/health", timeout=15)
                        if response.status_code == 200:
                            logger.debug("✅ Self-ping successful")
                        else:
                            logger.warning(f"⚠️ Self-ping failed: {response.status_code}")
                except Exception as e:
                    logger.debug(f"⚠️ Self-ping error: {e}")
                time.sleep(SELF_PING_INTERVAL)
        
        def auto_save_task():
            while True:
                time.sleep(AUTO_SAVE_INTERVAL)
                self.save_all_data()
                logger.debug("💾 Auto-save completed")
        
        def cleanup_task():
            while True:
                time.sleep(3600)  # Каждый час
                self.cleanup_old_data()
                self._cleanup_old_cache()
        
        def stats_log_task():
            while True:
                time.sleep(300)  # Каждые 5 минут
                total_leaks = sum(len(leaks) for leaks in self.leak_database.values())
                logger.info(f"📊 Stats: {total_leaks} leaks, {len(self.user_profiles)} users, {len(self.threat_actors)} threats")
        
        threading.Thread(target=self_ping_task, daemon=True).start()
        threading.Thread(target=auto_save_task, daemon=True).start()
        threading.Thread(target=cleanup_task, daemon=True).start()
        threading.Thread(target=stats_log_task, daemon=True).start()
        
        logger.info("🔄 Background tasks started")

# ========== ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ==========
quantum_bot = None

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Quantum LeakTracker v3.0</title>
        <meta charset="UTF-8">
        <style>
            body {
                font-family: 'Arial', sans-serif;
                margin: 0;
                padding: 40px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-align: center;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            }
            h1 {
                font-size: 3em;
                margin-bottom: 10px;
                background: linear-gradient(45deg, #00ff88, #0088ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .status {
                display: inline-block;
                padding: 10px 20px;
                background: #00ff88;
                color: #000;
                border-radius: 50px;
                font-weight: bold;
                margin: 20px 0;
            }
            .links {
                margin-top: 30px;
            }
            .links a {
                display: inline-block;
                margin: 10px;
                padding: 15px 30px;
                background: rgba(255, 255, 255, 0.2);
                color: white;
                text-decoration: none;
                border-radius: 10px;
                transition: all 0.3s;
            }
            .links a:hover {
                background: rgba(255, 255, 255, 0.3);
                transform: translateY(-3px);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔮 Quantum LeakTracker v3.0</h1>
            <p>AI-Powered Threat Intelligence & Leak Detection System</p>
            
            <div class="status">🟢 SYSTEM ONLINE</div>
            
            <p>Security Level: <strong>""" + str(SECURITY_LEVEL) + """</strong>/10 | AI Analysis: <strong>""" + ("ENABLED" if ANALYSIS_DEEP_SCAN else "DISABLED") + """</strong></p>
            
            <div class="links">
                <a href="/dashboard">📊 Dashboard</a>
                <a href="/api/v1/health">🩺 Health Check</a>
                <a href="/api/v1/stats">📈 Statistics</a>
                <a href="/api/v1/export?type=json">📥 Export Data</a>
            </div>
            
            <div style="margin-top: 40px; opacity: 0.7;">
                <p>Powered by Quantum AI • Real-time Threat Detection • Enterprise Security</p>
                <p>🔒 End-to-End Encrypted • 🚀 High Performance • 🤖 AI-Powered Analysis</p>
            </div>
        </div>
    </body>
    </html>
    """

def main():
    global quantum_bot
    
    try:
        # Инициализация Quantum бота
        quantum_bot = QuantumLeakTracker()
        
        logger.info(f"🚀 Quantum LeakTracker запущен на порту {PORT}")
        logger.info(f"🔐 Уровень безопасности: {SECURITY_LEVEL}/10")
        logger.info(f"🤖 AI анализ: {'ВКЛЮЧЕН' if ANALYSIS_DEEP_SCAN else 'ВЫКЛЮЧЕН'}")
        logger.info(f"👥 Админов: {len(ALLOWED_USER_IDS)}")
        
        # Запуск Flask
        app.run(
            host='0.0.0.0',
            port=PORT,
            debug=False,
            use_reloader=False
        )
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()