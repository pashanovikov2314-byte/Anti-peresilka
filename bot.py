import logging
import re
import time
import threading
import requests
import hashlib
import pickle
import base64
import secrets
import math
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from collections import defaultdict, OrderedDict
import json
import os
import sys

# ========== ЗАГЛУШКА ДЛЯ IMGHDR ==========
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
MAX_LEAKS_PER_USER = int(os.environ.get("MAX_LEAKS_PER_USER", 500))

# Уровни безопасности
SECURITY_LEVEL = int(os.environ.get("SECURITY_LEVEL", 7))
ANALYSIS_DEEP_SCAN = os.environ.get("DEEP_SCAN", "true").lower() == "true"
ENABLE_BEHAVIOR_AI = os.environ.get("BEHAVIOR_AI", "true").lower() == "true"

if not TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не установлен")
if not ALLOWED_USER_IDS:
    raise ValueError("❌ ALLOWED_IDS не установлен")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise ValueError("❌ SECRET_KEY должен быть минимум 32 символа")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== СИСТЕМЫ АНАЛИЗА ==========
class QuantumAnalyzer:
    """Анализатор с детекцией утечек"""
    
    def __init__(self, security_level=7):
        self.security_level = max(1, min(10, security_level))
        self.patterns = self._load_patterns()
        self.behavior_profiles = {}
        self.threat_intelligence = defaultdict(list)
        
    def _load_patterns(self):
        """Загрузка паттернов обнаружения"""
        return {
            'financial': [
                r'\b\d{16}\b',
                r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
                r'(?:счет|account|р\/с)[:\s№]*[\d\s]{10,}',
            ],
            
            'personal': [
                r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}\b',
                r'(?:паспорт|passport)[:\s№]*[\d\s]{6,}',
                r'(?:снилс|snils)[:\s]*\d{3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{2}',
            ],
            
            'credentials': [
                r'(?:логин|login|user)[:\s]*[\w\.@-]{3,}',
                r'(?:пароль|password|pass)[:\s]*[^\s]{6,}',
                r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\s*[:;]\s*\S{4,}',
            ],
            
            'network': [
                r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b',
                r'(?:ssh|ftp|sftp)://[^\s]+',
            ],
            
            'telegram': [
                r't\.me/(?:c/)?[a-zA-Z0-9_\-/]+',
                r'(?:https?://)?(?:www\.)?(?:telegram\.me|t\.me)/[a-zA-Z0-9_\-/]+',
            ]
        }
    
    def analyze_text(self, text: str) -> dict:
        """Анализ текста на утечки"""
        if not text or not isinstance(text, str):
            return {'risk_score': 0, 'detections': [], 'risk_level': 'LOW'}
        
        results = {
            'risk_score': 0,
            'detections': [],
            'risk_level': 'LOW',
            'timestamp': datetime.now().isoformat()
        }
        
        # Проверка по категориям
        for category, patterns in self.patterns.items():
            for pattern in patterns:
                try:
                    matches = list(re.finditer(pattern, text, re.IGNORECASE))
                    for match in matches:
                        if match and len(match.group()) > 3:
                            detection = {
                                'category': category,
                                'text': match.group()[:50],
                                'position': match.start(),
                                'confidence': self._calculate_confidence(category, match.group())
                            }
                            results['detections'].append(detection)
                            
                            # Веса категорий
                            weights = {
                                'financial': 40,
                                'personal': 35,
                                'credentials': 45,
                                'network': 25,
                                'telegram': 20
                            }
                            results['risk_score'] += weights.get(category, 10)
                except Exception as e:
                    logger.debug(f"Pattern error: {e}")
        
        # Нормализация
        results['risk_score'] = min(100, results['risk_score'])
        
        # Уровень риска
        if results['risk_score'] >= 70:
            results['risk_level'] = 'HIGH'
        elif results['risk_score'] >= 40:
            results['risk_level'] = 'MEDIUM'
        elif results['risk_score'] >= 20:
            results['risk_level'] = 'LOW'
        else:
            results['risk_level'] = 'MINIMAL'
        
        return results
    
    def _calculate_confidence(self, category: str, text: str) -> int:
        """Расчет уверенности"""
        base_conf = {
            'financial': 80,
            'personal': 75,
            'credentials': 85,
            'network': 70,
            'telegram': 60
        }
        return base_conf.get(category, 50)

class ThreatIntelligence:
    """Система анализа угроз"""
    
    def __init__(self):
        self.threat_actors = defaultdict(int)
        self.suspicious_keywords = ['слив', 'слито', 'утекло', 'утечка', 'секрет', 'конфиденциально']
    
    def analyze_threat(self, text: str, user_id: int) -> dict:
        """Анализ угроз"""
        threat_score = 0
        indicators = []
        
        # Ключевые слова
        text_lower = text.lower()
        for keyword in self.suspicious_keywords:
            if keyword in text_lower:
                threat_score += 15
                indicators.append(f'KEYWORD_{keyword.upper()}')
        
        # Угрозы от пользователя
        if self.threat_actors.get(user_id, 0) > 0:
            threat_score += 10 * self.threat_actors[user_id]
            indicators.append('REPEAT_THREAT_ACTOR')
        
        return {
            'threat_score': min(100, threat_score),
            'indicators': indicators,
            'threat_level': 'HIGH' if threat_score >= 30 else 'MEDIUM' if threat_score >= 15 else 'LOW'
        }

# ========== ОСНОВНОЙ БОТ ==========
class LeakTracker:
    """Трекер утечек"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.leak_database = defaultdict(OrderedDict)
        self.user_profiles = {}
        self.system_stats = {
            'total_leaks': 0,
            'total_users': 0,
            'start_time': self.start_time.isoformat()
        }
        
        # Системы
        self.analyzer = QuantumAnalyzer(SECURITY_LEVEL)
        self.threat_intel = ThreatIntelligence()
        
        # Кэш
        self.cache = {}
        self.cache_timeout = 300
        
        logger.info("🚀 LeakTracker инициализирован")
    
    def analyze_leak(self, user_id: int, leak_data: dict) -> dict:
        """Анализ утечки"""
        analysis = {
            'leak_id': hashlib.md5(json.dumps(leak_data, sort_keys=True).encode()).hexdigest()[:8],
            'timestamp': datetime.now().isoformat(),
            'risk_score': 0,
            'risk_level': 'LOW',
            'detections': []
        }
        
        # Анализ текста
        text = leak_data.get('text', '') or leak_data.get('details', '')
        if text:
            text_analysis = self.analyzer.analyze_text(text)
            analysis['risk_score'] = text_analysis['risk_score']
            analysis['detections'] = text_analysis['detections']
            analysis['risk_level'] = text_analysis['risk_level']
        
        # Обновление профиля
        self._update_user_profile(user_id, leak_data, analysis)
        
        return analysis
    
    def _update_user_profile(self, user_id: int, leak_data: dict, analysis: dict):
        """Обновление профиля пользователя"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                'first_seen': datetime.now().isoformat(),
                'leak_count': 0,
                'max_risk': 0,
                'username': leak_data.get('username', f'id{user_id}')
            }
        
        profile = self.user_profiles[user_id]
        profile['last_seen'] = datetime.now().isoformat()
        profile['leak_count'] += 1
        profile['max_risk'] = max(profile['max_risk'], analysis['risk_score'])
        
        # Обновление статистики
        self.system_stats['total_leaks'] += 1
        if profile['leak_count'] == 1:
            self.system_stats['total_users'] += 1
    
    def save_data(self):
        """Сохранение данных"""
        try:
            data = {
                'leak_database': dict(self.leak_database),
                'user_profiles': self.user_profiles,
                'system_stats': self.system_stats,
                'saved_at': datetime.now().isoformat()
            }
            
            with open('leak_data.pkl', 'wb') as f:
                pickle.dump(data, f)
            
            # Очистка кэша
            self._clean_cache()
            
            logger.debug("💾 Данные сохранены")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")
    
    def load_data(self):
        """Загрузка данных"""
        try:
            if os.path.exists('leak_data.pkl'):
                with open('leak_data.pkl', 'rb') as f:
                    data = pickle.load(f)
                
                self.leak_database = defaultdict(OrderedDict, data.get('leak_database', {}))
                self.user_profiles = data.get('user_profiles', {})
                self.system_stats.update(data.get('system_stats', {}))
                
                logger.info(f"✅ Данные загружены: {len(self.user_profiles)} пользователей")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
    
    def _clean_cache(self):
        """Очистка кэша"""
        now = datetime.now()
        expired = []
        
        for key, value in list(self.cache.items()):
            if isinstance(value, dict) and 'timestamp' in value:
                try:
                    cache_time = datetime.fromisoformat(value['timestamp'])
                    if (now - cache_time).total_seconds() > self.cache_timeout:
                        expired.append(key)
                except:
                    expired.append(key)
        
        for key in expired:
            del self.cache[key]
        
        if expired:
            logger.debug(f"🧹 Очищено {len(expired)} записей кэша")

# ========== FLASK APP ==========
tracker = LeakTracker()
tracker.load_data()

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>LeakTracker v2.0</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 40px;
                background: #f5f5f5;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                border-bottom: 2px solid #4CAF50;
                padding-bottom: 10px;
            }
            .status {
                padding: 10px;
                background: #4CAF50;
                color: white;
                border-radius: 5px;
                display: inline-block;
                margin: 10px 0;
            }
            .endpoint {
                background: #f9f9f9;
                padding: 15px;
                border-left: 4px solid #4CAF50;
                margin: 10px 0;
                font-family: monospace;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔐 LeakTracker v2.0</h1>
            <div class="status">🟢 SYSTEM ONLINE</div>
            
            <p>Система мониторинга утечек информации</p>
            
            <h2>📊 Статистика</h2>
            <p>• Пользователей: """ + str(tracker.system_stats.get('total_users', 0)) + """</p>
            <p>• Утечек: """ + str(tracker.system_stats.get('total_leaks', 0)) + """</p>
            <p>• Уровень безопасности: """ + str(SECURITY_LEVEL) + """/10</p>
            
            <h2>🔧 API Endpoints</h2>
            <div class="endpoint">POST /api/analyze - Анализ текста</div>
            <div class="endpoint">POST /api/report - Отчет об утечке</div>
            <div class="endpoint">GET /api/health - Статус системы</div>
            <div class="endpoint">GET /api/stats - Статистика</div>
            
            <p style="margin-top: 30px; color: #666; font-size: 0.9em;">
                LeakTracker v2.0 | Мониторинг утечек информации
            </p>
        </div>
    </body>
    </html>
    """

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    """Анализ текста"""
    try:
        data = request.json
        if not data or 'text' not in data:
            return jsonify({'error': 'Текст не предоставлен'}), 400
        
        text = data['text']
        user_id = data.get('user_id', 0)
        
        # Анализ
        analysis = tracker.analyzer.analyze_text(text)
        
        return jsonify({
            'status': 'success',
            'analysis': analysis,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"API Analyze error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/report', methods=['POST'])
def api_report():
    """Отчет об утечке"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Нет данных'}), 400
        
        user_id = data.get('user_id')
        leak_data = data.get('leak_data', {})
        
        if not user_id:
            return jsonify({'error': 'ID пользователя обязателен'}), 400
        
        # Анализ утечки
        analysis = tracker.analyze_leak(user_id, leak_data)
        
        # Сохранение
        if user_id not in tracker.leak_database:
            tracker.leak_database[user_id] = OrderedDict()
        
        leak_id = analysis['leak_id']
        tracker.leak_database[user_id][leak_id] = {
            'leak_id': leak_id,
            'timestamp': analysis['timestamp'],
            'data': leak_data,
            'analysis': analysis
        }
        
        # Ограничение количества
        if len(tracker.leak_database[user_id]) > MAX_LEAKS_PER_USER:
            oldest = next(iter(tracker.leak_database[user_id]))
            del tracker.leak_database[user_id][oldest]
        
        return jsonify({
            'status': 'success',
            'leak_id': leak_id,
            'analysis': analysis
        })
        
    except Exception as e:
        logger.error(f"API Report error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def api_health():
    """Проверка здоровья"""
    uptime = (datetime.now() - tracker.start_time).total_seconds()
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'uptime_seconds': uptime,
        'database': {
            'users': tracker.system_stats['total_users'],
            'leaks': tracker.system_stats['total_leaks']
        },
        'security_level': SECURITY_LEVEL
    })

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Статистика"""
    return jsonify(tracker.system_stats)

@app.route('/ping', methods=['GET'])
def ping():
    """Пинг для поддержания активности"""
    return jsonify({'status': 'pong', 'time': datetime.now().isoformat()})

# ========== ФОНОВЫЕ ЗАДАЧИ ==========
def background_tasks():
    """Фоновые задачи"""
    def self_ping():
        while True:
            try:
                if RENDER_URL and RENDER_URL.startswith('http'):
                    requests.get(f"{RENDER_URL}/ping", timeout=10)
                    logger.debug("✅ Self-ping выполнен")
            except Exception as e:
                logger.debug(f"⚠️ Self-ping error: {e}")
            time.sleep(SELF_PING_INTERVAL)
    
    def auto_save():
        while True:
            time.sleep(AUTO_SAVE_INTERVAL)
            tracker.save_data()
            logger.debug("💾 Автосохранение выполнено")
    
    # Запуск в отдельных потоках
    threading.Thread(target=self_ping, daemon=True).start()
    threading.Thread(target=auto_save, daemon=True).start()

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    # Запуск фоновых задач
    background_tasks()
    
    logger.info(f"🚀 Сервер запускается на порту {PORT}")
    logger.info(f"🔐 Уровень безопасности: {SECURITY_LEVEL}")
    logger.info(f"👥 Разрешено пользователей: {len(ALLOWED_USER_IDS)}")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False
    )

if __name__ == '__main__':
    main()
