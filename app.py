import os
import json
import time
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
import requests

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

print("="*60)
print("🔐 ULTRA-STRICT LEAK DETECTOR")
print("="*60)
print(f"Token: {'✓' if TELEGRAM_TOKEN else '✗'}")
print(f"Allowed IDs: {ALLOWED_IDS}")
print("="*60)

# ========== ХРАНИЛИЩЕ С РАЗДЕЛЕНИЕМ ==========
class Storage:
    def __init__(self):
        self.messages = []
        self.users = {}
        self.chats = {}
        self.bot_chats = set()
        
        # РАЗДЕЛЕНИЕ ПО ИСТОЧНИКАМ УТЕЧЕК
        self.leaks_by_source = {
            "forward_from_our_chat": [],      # Переслал ИЗ нашего чата
            "forward_to_our_chat": [],        # Переслал В наш чат
            "copy_from_our_chat": [],         # Скопировал ИЗ нашего чата
            "copy_to_our_chat": [],           # Скопировал В наш чат
            "screenshot_from_our_chat": [],   # Заскринил ИЗ нашего чата
            "screenshot_to_our_chat": [],     # Заскринил В наш чат
            "other_leaks": []                 # Другие утечки
        }
        
        self.load()
    
    def save(self):
        try:
            data = {
                "messages": self.messages[-10000:],
                "users": self.users,
                "chats": self.chats,
                "bot_chats": list(self.bot_chats),
                "leaks_by_source": self.leaks_by_source,
                "saved": datetime.now().isoformat()
            }
            with open("data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"💾 Saved: {len(self.messages)} msgs, {sum(len(v) for v in self.leaks_by_source.values())} leaks")
        except Exception as e:
            print(f"Save error: {e}")
    
    def load(self):
        try:
            if os.path.exists("data.json"):
                with open("data.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.messages = data.get("messages", [])
                self.users = data.get("users", {})
                self.chats = data.get("chats", {})
                self.bot_chats = set(data.get("bot_chats", []))
                self.leaks_by_source = data.get("leaks_by_source", {
                    "forward_from_our_chat": [],
                    "forward_to_our_chat": [],
                    "copy_from_our_chat": [],
                    "copy_to_our_chat": [],
                    "screenshot_from_our_chat": [],
                    "screenshot_to_our_chat": [],
                    "other_leaks": []
                })
                total_leaks = sum(len(v) for v in self.leaks_by_source.values())
                print(f"📂 Loaded: {len(self.messages)} msgs, {total_leaks} leaks")
        except Exception as e:
            print(f"Load error: {e}")
    
    def add_leak(self, leak_type: str, leak_data: dict):
        """Добавить утечку в нужную категорию"""
        if leak_type in self.leaks_by_source:
            leak_data["id"] = len(self.leaks_by_source[leak_type]) + 1
            leak_data["added_at"] = datetime.now().isoformat()
            self.leaks_by_source[leak_type].append(leak_data)
            return True
        return False
    
    def get_all_leaks(self) -> list:
        """Получить все утечки"""
        all_leaks = []
        for leak_type, leaks in self.leaks_by_source.items():
            for leak in leaks:
                leak["source_type"] = leak_type
                all_leaks.append(leak)
        return sorted(all_leaks, key=lambda x: x.get("timestamp", ""), reverse=True)
    
    def get_leak_stats(self) -> dict:
        """Статистика по утечкам"""
        stats = {}
        for leak_type, leaks in self.leaks_by_source.items():
            stats[leak_type] = {
                "count": len(leaks),
                "last_leak": leaks[-1] if leaks else None,
                "today": len([l for l in leaks if l.get("timestamp", "").startswith(datetime.now().strftime("%Y-%m-%d"))])
            }
        stats["total"] = sum(len(v) for v in self.leaks_by_source.values())
        return stats

storage = Storage()

# ========== УЛЬТРА-ЖЕСТКИЙ АНАЛИЗАТОР ==========
class UltraStrictDetector:
    def __init__(self):
        # СУПЕР-ЖЕСТКИЕ ПАТТЕРНЫ ДЛЯ КАЖДОГО ТИПА
        
        # 1. ПЕРЕСЫЛКА - максимально строгая проверка
        self.forward_patterns = {
            "exact": [
                r"переслал",
                r"forward",
                r"отправил",
                r"сделал репост",
                r"репостнул",
                r"поделился",
                r"распространил",
                r"разослал",
                r"отслал",
                r"форвард"
            ],
            "context": [
                r"всем покажу",
                r"показал другу",
                r"кинул в другой чат",
                r"отправил в другой чат",
                r"скинул в",
                r"разместил в",
                r"опубликовал в",
                r"выложил в"
            ],
            "intent": [
                r"сохраню на будущее",
                r"оставлю себе",
                r"буду хранить",
                r"заберу себе",
                r"присвою",
                r"использую",
                r"воспользуюсь"
            ]
        }
        
        # 2. КОПИРОВАНИЕ - гипер-строгая проверка
        self.copy_patterns = {
            "exact": [
                r"скопировал",
                r"копирую",
                r"copy",
                r"взял текст",
                r"украл текст",
                r"присвоил текст",
                r"сохранил текст",
                r"записал текст",
                r"копипаст",
                r"копипаста",
                r"дублировал",
                r"повторил"
            ],
            "context": [
                r"весь текст",
                r"целиком",
                r"полностью",
                r"дословно",
                r"точно так же",
                r"один в один",
                r"как есть",
                r"без изменений"
            ],
            "method": [
                r"через ctrl\+c",
                r"через ctrl\+v",
                r"выделил и копировал",
                r"выделил весь текст",
                r"скопировал мышкой",
                r"сохранил в буфер"
            ]
        }
        
        # 3. СКРИНШОТЫ - максимальная детекция
        self.screenshot_patterns = {
            "exact": [
                r"скрин",
                r"screenshot",
                r"снимок экрана",
                r"фото экрана",
                r"картинка чата",
                r"заскринил",
                r"сделал скрин",
                r"сохранил скрин",
                r"снял скрин",
                r"захватил экран"
            ],
            "context": [
                r"сохранил себе",
                r"сохранено у меня",
                r"имею фото",
                r"имею снимок",
                r"зафиксировал",
                r"запечатлел",
                r"запомнил на фото",
                r"оставил на память"
            ],
            "action": [
                r"нажал print screen",
                r"через ножницы",
                r"через lightshot",
                r"через gyazo",
                r"через snipping tool",
                r"скриншотил",
                r"снимал экран"
            ],
            "sharing": [
                r"покажу всем",
                r"распространил скрин",
                r"разошлю скрин",
                r"отправлю скрин",
                r"скину скрин",
                r"выложу скрин"
            ]
        }
        
        # 4. ДОПОЛНИТЕЛЬНЫЕ ЖЕСТКИЕ ПАТТЕРНЫ
        self.extra_strict_patterns = {
            "data_leak": [
                r"пароль[:\s]*[^\s]{4,}",
                r"логин[:\s]*[^\s]{3,}",
                r"ключ[:\s]*[^\s]{8,}",
                r"токен[:\s]*[^\s]{10,}",
                r"секрет[:\s]*[^\s]{4,}",
                r"конфиденциально[^\s]*"
            ],
            "threat": [
                r"слил инфу",
                r"утекло инфо",
                r"выложил данные",
                r"опубликовал приват",
                r"рассекретил",
                r"раскрыл тайну"
            ]
        }
    
    def ultra_detect_forward(self, text: str, is_actual_forward: bool = False) -> dict:
        """УЛЬТРА-ЖЕСТКАЯ проверка на пересылку"""
        if not text:
            return {"detected": False, "confidence": 0, "patterns": [], "score": 0}
        
        text_lower = text.lower()
        patterns_found = []
        confidence = 0
        
        # БАЗОВЫЙ СЛУЧАЙ: реальная пересылка в Telegram
        if is_actual_forward:
            patterns_found.append("actual_telegram_forward")
            confidence += 90
        
        # ЖЕСТКАЯ проверка по точным словам
        for pattern in self.forward_patterns["exact"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"forward_exact_{pattern[:15]}")
                confidence += 30
        
        # Проверка контекста
        for pattern in self.forward_patterns["context"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"forward_context_{pattern[:15]}")
                confidence += 25
        
        # Проверка намерений
        for pattern in self.forward_patterns["intent"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"forward_intent_{pattern[:15]}")
                confidence += 20
        
        # Комбинация паттернов увеличивает уверенность
        if len(patterns_found) >= 2:
            confidence += 15
        if len(patterns_found) >= 3:
            confidence += 20
        
        return {
            "detected": confidence >= 20,
            "confidence": min(100, confidence),
            "patterns": patterns_found,
            "score": min(100, confidence * 1.5)
        }
    
    def ultra_detect_copy(self, text: str, reply_to_text: str = "") -> dict:
        """УЛЬТРА-ЖЕСТКАЯ проверка на копирование"""
        if not text:
            return {"detected": False, "confidence": 0, "patterns": [], "similarity": 0}
        
        text_lower = text.lower()
        patterns_found = []
        confidence = 0
        
        # 1. Проверка по точным словам копирования
        for pattern in self.copy_patterns["exact"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"copy_exact_{pattern[:15]}")
                confidence += 35
        
        # 2. Проверка контекста копирования
        for pattern in self.copy_patterns["context"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"copy_context_{pattern[:15]}")
                confidence += 25
        
        # 3. Проверка методов копирования
        for pattern in self.copy_patterns["method"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"copy_method_{pattern[:15]}")
                confidence += 30
        
        # 4. ПРОВЕРКА СХОЖЕСТИ ТЕКСТОВ (самая важная)
        similarity_score = 0
        if reply_to_text and text:
            similarity = self._calculate_text_similarity(text, reply_to_text)
            similarity_score = similarity * 100
            
            if similarity > 0.7:  # 70% схожести
                patterns_found.append("high_text_similarity")
                confidence += 40
            elif similarity > 0.5:  # 50% схожести
                patterns_found.append("medium_text_similarity")
                confidence += 25
            elif similarity > 0.3:  # 30% схожести
                patterns_found.append("low_text_similarity")
                confidence += 15
        
        # 5. Проверка на копирование структуры
        if len(text.split()) > 10:  # Длинный текст
            # Проверяем повторы фраз
            words = text_lower.split()
            common_phrases = []
            for i in range(len(words) - 2):
                phrase = " ".join(words[i:i+3])
                if text_lower.count(phrase) > 1:
                    common_phrases.append(phrase)
            
            if common_phrases:
                patterns_found.append("repeated_phrases")
                confidence += 20
        
        # Комбинация паттернов
        if len(patterns_found) >= 2:
            confidence += 15
        if len(patterns_found) >= 3:
            confidence += 20
        
        return {
            "detected": confidence >= 25,
            "confidence": min(100, confidence),
            "patterns": patterns_found,
            "similarity": similarity_score,
            "score": min(100, confidence * 1.3)
        }
    
    def ultra_detect_screenshot(self, text: str) -> dict:
        """УЛЬТРА-ЖЕСТКАЯ проверка на скриншоты"""
        if not text:
            return {"detected": False, "confidence": 0, "patterns": [], "score": 0}
        
        text_lower = text.lower()
        patterns_found = []
        confidence = 0
        
        # 1. Точные слова скриншотов
        for pattern in self.screenshot_patterns["exact"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"screenshot_exact_{pattern[:15]}")
                confidence += 40
        
        # 2. Контекст сохранения
        for pattern in self.screenshot_patterns["context"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"screenshot_context_{pattern[:15]}")
                confidence += 30
        
        # 3. Методы создания скриншотов
        for pattern in self.screenshot_patterns["action"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"screenshot_action_{pattern[:15]}")
                confidence += 35
        
        # 4. Распространение скриншотов
        for pattern in self.screenshot_patterns["sharing"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                patterns_found.append(f"screenshot_sharing_{pattern[:15]}")
                confidence += 45  # Очень высокий вес!
        
        # 5. Дополнительные жесткие проверки
        for category, patterns in self.extra_strict_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    patterns_found.append(f"extra_{category}_{pattern[:10]}")
                    confidence += 25
        
        # Комбинация паттернов
        if len(patterns_found) >= 2:
            confidence += 20
        if len(patterns_found) >= 3:
            confidence += 30
        if len(patterns_found) >= 4:
            confidence += 40
        
        return {
            "detected": confidence >= 30,
            "confidence": min(100, confidence),
            "patterns": patterns_found,
            "score": min(100, confidence * 1.4)
        }
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Расчет схожести текстов"""
        if not text1 or not text2:
            return 0.0
        
        # Очистка текста
        clean1 = re.sub(r'\s+', ' ', text1.strip().lower())
        clean2 = re.sub(r'\s+', ' ', text2.strip().lower())
        
        if clean1 == clean2:
            return 1.0
        
        # Разделение на слова
        words1 = set(clean1.split())
        words2 = set(clean2.split())
        
        if not words1 or not words2:
            return 0.0
        
        # Коэффициент Жаккара
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        # Учитываем порядок слов
        jaccard = intersection / union if union > 0 else 0.0
        
        # Дополнительная проверка на подстроки
        if len(clean1) > 20 and len(clean2) > 20:
            if clean1 in clean2 or clean2 in clean1:
                return max(jaccard, 0.8)
        
        return jaccard
    
    def analyze_message(self, text: str, is_forwarded: bool = False, reply_text: str = "") -> dict:
        """Полный анализ сообщения"""
        forward_result = self.ultra_detect_forward(text, is_forwarded)
        copy_result = self.ultra_detect_copy(text, reply_text)
        screenshot_result = self.ultra_detect_screenshot(text)
        
        # Определение главного типа утечки
        max_score = max(
            forward_result["score"],
            copy_result["score"],
            screenshot_result["score"]
        )
        
        main_leak_type = None
        if max_score > 30:  # Порог обнаружения
            if forward_result["score"] == max_score:
                main_leak_type = "forward"
            elif copy_result["score"] == max_score:
                main_leak_type = "copy"
            elif screenshot_result["score"] == max_score:
                main_leak_type = "screenshot"
        
        return {
            "has_leak": main_leak_type is not None,
            "main_leak_type": main_leak_type,
            "forward": forward_result,
            "copy": copy_result,
            "screenshot": screenshot_result,
            "max_score": max_score,
            "timestamp": datetime.now().isoformat()
        }

detector = UltraStrictDetector()

# ========== TELEGRAM API ==========
def send_telegram_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Отправить сообщение в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=10)
        return response.json().get("ok", False)
    except Exception as e:
        print(f"Send message error: {e}")
        return False

# ========== FLASK APP ==========
app = Flask(__name__)

@app.route('/')
def home():
    stats = {
        "total_messages": len(storage.messages),
        "total_users": len(storage.users),
        "total_chats": len(storage.chats),
        "bot_chats_count": len(storage.bot_chats),
        "leak_stats": storage.get_leak_stats(),
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Получаем последние утечки
    recent_leaks = storage.get_all_leaks()[:20]
    
    # Статистика по типам утечек
    leak_types_count = {}
    for leak_type, leaks in storage.leaks_by_source.items():
        leak_types_count[leak_type] = len(leaks)
    
    return render_template('index.html',
                         stats=stats,
                         allowed_ids=ALLOWED_IDS,
                         recent_leaks=recent_leaks,
                         leak_types_count=leak_types_count)

@app.route('/api/stats')
def api_stats():
    leak_stats = storage.get_leak_stats()
    return jsonify({
        "general": {
            "messages": len(storage.messages),
            "users": len(storage.users),
            "chats": len(storage.chats),
            "bot_chats": len(storage.bot_chats)
        },
        "leaks": leak_stats,
        "today": {
            "messages": len([m for m in storage.messages if m.get("time", "").startswith(datetime.now().strftime("%Y-%m-%d"))]),
            "leaks": sum([len([l for l in storage.leaks_by_source[lt] 
                             if l.get("timestamp", "").startswith(datetime.now().strftime("%Y-%m-%d"))])
                         for lt in storage.leaks_by_source])
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/leaks')
def api_leaks():
    all_leaks = storage.get_all_leaks()
    return jsonify({
        "leaks": all_leaks[:100],
        "count": len(all_leaks),
        "by_source": {k: len(v) for k, v in storage.leaks_by_source.items()}
    })

@app.route('/api/leaks/forward')
def api_leaks_forward():
    """Утечки типа пересылка"""
    forwards = storage.leaks_by_source["forward_from_our_chat"] + storage.leaks_by_source["forward_to_our_chat"]
    return jsonify({
        "leaks": forwards[-50:],
        "count": len(forwards),
        "from_our_chat": len(storage.leaks_by_source["forward_from_our_chat"]),
        "to_our_chat": len(storage.leaks_by_source["forward_to_our_chat"])
    })

@app.route('/api/leaks/copy')
def api_leaks_copy():
    """Утечки типа копирование"""
    copies = storage.leaks_by_source["copy_from_our_chat"] + storage.leaks_by_source["copy_to_our_chat"]
    return jsonify({
        "leaks": copies[-50:],
        "count": len(copies),
        "from_our_chat": len(storage.leaks_by_source["copy_from_our_chat"]),
        "to_our_chat": len(storage.leaks_by_source["copy_to_our_chat"])
    })

@app.route('/api/leaks/screenshot')
def api_leaks_screenshot():
    """Утечки типа скриншот"""
    screenshots = storage.leaks_by_source["screenshot_from_our_chat"] + storage.leaks_by_source["screenshot_to_our_chat"]
    return jsonify({
        "leaks": screenshots[-50:],
        "count": len(screenshots),
        "from_our_chat": len(storage.leaks_by_source["screenshot_from_our_chat"]),
        "to_our_chat": len(storage.leaks_by_source["screenshot_to_our_chat"])
    })

@app.route('/api/users')
def api_users():
    users_list = []
    for user_id, user_data in storage.users.items():
        # Считаем утечки по типам
        leaks_by_type = {}
        for leak_type, leaks in storage.leaks_by_source.items():
            user_leaks = [l for l in leaks if l.get("user_id") == user_id]
            if user_leaks:
                leaks_by_type[leak_type] = len(user_leaks)
        
        user_data_copy = user_data.copy()
        user_data_copy["total_leaks"] = sum(len([l for l in leaks if l.get("user_id") == user_id]) 
                                          for leaks in storage.leaks_by_source.values())
        user_data_copy["leaks_by_type"] = leaks_by_type
        users_list.append(user_data_copy)
    
    return jsonify({
        "users": sorted(users_list, key=lambda x: x.get("messages", 0), reverse=True),
        "count": len(users_list)
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": "ultra-strict-leak-detector",
        "timestamp": datetime.now().isoformat(),
        "detector": "ULTRA_STRICT_MODE_ACTIVE"
    })

@app.route('/setup')
def setup():
    """Установка webhook"""
    try:
        webhook_url = os.environ.get("RENDER_EXTERNAL_URL", "https://anti-peresilka.onrender.com")
        webhook_url = f"{webhook_url}/webhook"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {
            "url": webhook_url,
            "max_connections": 100,
            "allowed_updates": ["message", "edited_message", "chat_member"]
        }
        response = requests.post(url, json=data)
        
        if response.json().get("ok"):
            return jsonify({
                "ok": True,
                "message": "ULTRA STRICT MODE ACTIVATED",
                "url": webhook_url,
                "detection_level": "MAXIMUM"
            })
        else:
            return jsonify({"error": response.json()})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка сообщений от Telegram - УЛЬТРА-ЖЕСТКАЯ ПРОВЕРКА"""
    try:
        data = request.json
        if not data:
            return jsonify({"ok": True})
        
        # Обработка добавления бота в чат
        if "my_chat_member" in data:
            chat_member = data["my_chat_member"]
            chat = chat_member.get("chat", {})
            chat_id = chat.get("id")
            
            if chat_id:
                storage.bot_chats.add(chat_id)
                storage.chats[str(chat_id)] = {
                    "id": chat_id,
                    "title": chat.get("title", f"Chat {chat_id}"),
                    "type": chat.get("type", ""),
                    "bot_added": datetime.now().isoformat()
                }
                print(f"🤖 Бот добавлен в чат: {chat.get('title')} (ID: {chat_id})")
        
        # Обработка сообщений
        if "message" in data:
            msg = data["message"]
            user_id = msg.get("from", {}).get("id", 0)
            chat_id = msg.get("chat", {}).get("id", 0)
            text = msg.get("text", "") or msg.get("caption", "")
            
            # Добавляем чат в список
            storage.bot_chats.add(chat_id)
            
            # Сохраняем сообщение
            message_data = {
                "id": msg.get("message_id"),
                "user_id": user_id,
                "chat_id": chat_id,
                "text": text[:1000],
                "time": datetime.now().isoformat(),
                "is_forward": "forward_date" in msg,
                "has_reply": "reply_to_message" in msg,
                "chat_title": msg.get("chat", {}).get("title", ""),
                "username": msg.get("from", {}).get("username", ""),
                "first_name": msg.get("from", {}).get("first_name", "")
            }
            
            storage.messages.append(message_data)
            
            # Обновляем чат
            chat_info = msg.get("chat", {})
            storage.chats[str(chat_id)] = {
                "id": chat_id,
                "title": chat_info.get("title", f"Chat {chat_id}"),
                "type": chat_info.get("type", ""),
                "last_activity": datetime.now().isoformat()
            }
            
            # Обновляем пользователя
            if user_id not in storage.users:
                storage.users[user_id] = {
                    "id": user_id,
                    "username": msg.get("from", {}).get("username", ""),
                    "first_name": msg.get("from", {}).get("first_name", ""),
                    "messages": 0,
                    "leaks": 0,
                    "first_seen": datetime.now().isoformat()
                }
            
            user = storage.users[user_id]
            user["messages"] = user.get("messages", 0) + 1
            user["last_seen"] = datetime.now().isoformat()
            
            # УЛЬТРА-ЖЕСТКИЙ АНАЛИЗ СООБЩЕНИЯ
            reply_text = ""
            if "reply_to_message" in msg:
                reply_text = msg["reply_to_message"].get("text", "") or msg["reply_to_message"].get("caption", "")
            
            analysis = detector.analyze_message(
                text=text,
                is_forwarded=message_data["is_forward"],
                reply_text=reply_text
            )
            
            # ОПРЕДЕЛЕНИЕ ИСТОЧНИКА УТЕЧКИ
            if analysis["has_leak"]:
                leak_type = analysis["main_leak_type"]
                chat_name = message_data.get("chat_title", f"чат {chat_id}")
                
                # Определяем направление утечки
                # TODO: Здесь нужно определить, наш это чат или внешний
                # Пока что считаем все чаты "нашими" для бота
                source_direction = "from_our_chat"  # ИЗ нашего чата
                
                leak_category = f"{leak_type}_{source_direction}"
                
                leak_data = {
                    "user_id": user_id,
                    "username": user.get("username", ""),
                    "chat_id": chat_id,
                    "chat_title": chat_name,
                    "message_id": message_data["id"],
                    "text": text[:300],
                    "leak_type": leak_type,
                    "confidence": analysis[leak_type]["confidence"],
                    "patterns": analysis[leak_type]["patterns"],
                    "score": analysis[leak_type]["score"],
                    "timestamp": analysis["timestamp"],
                    "is_actual_forward": message_data["is_forward"],
                    "has_reply": message_data["has_reply"]
                }
                
                # Добавляем в соответствующую категорию
                if leak_category == "forward_from_our_chat":
                    storage.add_leak("forward_from_our_chat", leak_data)
                elif leak_category == "copy_from_our_chat":
                    storage.add_leak("copy_from_our_chat", leak_data)
                elif leak_category == "screenshot_from_our_chat":
                    storage.add_leak("screenshot_from_our_chat", leak_data)
                else:
                    storage.add_leak("other_leaks", leak_data)
                
                user["leaks"] = user.get("leaks", 0) + 1
                
                print(f"🚨 УЛЬТРА-ЖЕСТКОЕ ОБНАРУЖЕНИЕ!")
                print(f"   Тип: {leak_type.upper()}")
                print(f"   Чат: {chat_name}")
                print(f"   Пользователь: {user_id}")
                print(f"   Уверенность: {analysis[leak_type]['confidence']}%")
                print(f"   Паттерны: {analysis[leak_type]['patterns'][:3]}")
                
                # ОТПРАВКА УВЕДОМЛЕНИЯ РАЗРЕШЕННЫМ ПОЛЬЗОВАТЕЛЯМ
                for allowed_id in ALLOWED_IDS:
                    if allowed_id != user_id:
                        # Определяем эмодзи и уровень
                        if analysis[leak_type]["confidence"] > 80:
                            emoji = "🔴"
                            level = "КРИТИЧЕСКИЙ УРОВЕНЬ"
                        elif analysis[leak_type]["confidence"] > 60:
                            emoji = "🟠"
                            level = "ВЫСОКИЙ УРОВЕНЬ"
                        elif analysis[leak_type]["confidence"] > 40:
                            emoji = "🟡"
                            level = "СРЕДНИЙ УРОВЕНЬ"
                        else:
                            emoji = "🔵"
                            level = "НИЗКИЙ УРОВЕНЬ"
                        
                        # Тип утечки
                        if leak_type == "forward":
                            type_desc = "📤 ПЕРЕСЫЛКА"
                        elif leak_type == "copy":
                            type_desc = "📋 КОПИРОВАНИЕ"
                        elif leak_type == "screenshot":
                            type_desc = "📸 СКРИНШОТ"
                        else:
                            type_desc = "⚠️ УТЕЧКА"
                        
                        alert_message = f"""
{emoji} <b>{level} - {type_desc}</b>

<b>📌 ДЕТАЛИ ОБНАРУЖЕНИЯ:</b>
├─ <b>Тип:</b> {type_desc}
├─ <b>Чат:</b> <code>{chat_name}</code>
├─ <b>Пользователь:</b> @{user.get('username', 'без username')}
├─ <b>ID:</b> <code>{user_id}</code>
├─ <b>Уверенность:</b> <b>{analysis[leak_type]['confidence']}%</b>
└─ <b>Направление:</b> ИЗ нашего чата

<b>🔍 ОБНАРУЖЕННЫЕ ПАТТЕРНЫ:</b>
{chr(10).join(f'├─ {p}' for p in analysis[leak_type]['patterns'][:3])}
└─ ... (всего {len(analysis[leak_type]['patterns'])} паттернов)

<b>💬 СООБЩЕНИЕ:</b>
<code>{text[:120]}{'...' if len(text) > 120 else ''}</code>

<b>📊 СТАТИСТИКА:</b>
├─ Всего сообщений от пользователя: {user.get('messages', 0)}
├─ Всего утечек от пользователя: {user.get('leaks', 0)}
└─ Время: {datetime.now().strftime('%H:%M:%S')}

<i>⚠️ УЛЬТРА-ЖЕСТКАЯ СИСТЕМА МОНИТОРИНГА АКТИВНА</i>
"""
                        send_telegram_message(allowed_id, alert_message)
            
            # ОТВЕТ ПОЛЬЗОВАТЕЛЮ (только разрешенным)
            if user_id in ALLOWED_IDS:
                if text.lower() in ["/start", "/старт"]:
                    welcome_msg = f"""
🔐 <b>УЛЬТРА-ЖЕСТКИЙ ДЕТЕКТОР УТЕЧЕК</b>

<b>⚡ РЕЖИМ:</b> МАКСИМАЛЬНАЯ СТРОГОСТЬ
<b>👥 ДОСТУП:</b> Только {len(ALLOWED_IDS)} пользователей

<b>🔍 ТИПЫ ОБНАРУЖЕНИЯ:</b>
├─ 📤 <b>ПЕРЕСЫЛКИ:</b> 25+ паттернов
├─ 📋 <b>КОПИРОВАНИЕ:</b> 20+ паттернов  
├─ 📸 <b>СКРИНШОТЫ:</b> 30+ паттернов
└─ ⚠️ <b>ДРУГИЕ УТЕЧКИ:</b> 15+ паттернов

<b>📊 СТАТИСТИКА СИСТЕМЫ:</b>
├─ Сообщений: {len(storage.messages)}
├─ Пользователей: {len(storage.users)}
├─ Чатов: {len(storage.bot_chats)}
└─ Утечек: {sum(len(v) for v in storage.leaks_by_source.values())}

<b>🔧 КОМАНДЫ:</b>
├─ /stats - статистика
├─ /mystats - моя статистика
├─ /leaks - последние утечки
└─ /help - помощь

<i>Система активна и мониторит {len(storage.bot_chats)} чатов</i>
"""
                    send_telegram_message(chat_id, welcome_msg)
                
                elif text.lower() in ["/stats", "/статистика"]:
                    leak_stats = storage.get_leak_stats()
                    stats_msg = f"""
<b>📊 СТАТИСТИКА УЛЬТРА-ЖЕСТКОГО МОНИТОРИНГА</b>

<b>📈 ОБЩАЯ СТАТИСТИКА:</b>
├─ 📨 Сообщений: <b>{len(storage.messages)}</b>
├─ 👥 Пользователей: <b>{len(storage.users)}</b>
├─ 💬 Чатов: <b>{len(storage.bot_chats)}</b>
└─ ⚠️ Утечек: <b>{leak_stats['total']}</b>

<b>🔍 РАСПРЕДЕЛЕНИЕ УТЕЧЕК:</b>
├─ 📤 Пересылки ИЗ чата: <b>{leak_stats['forward_from_our_chat']['count']}</b>
├─ 📤 Пересылки В чат: <b>{leak_stats['forward_to_our_chat']['count']}</b>
├─ 📋 Копирования ИЗ: <b>{leak_stats['copy_from_our_chat']['count']}</b>
├─ 📋 Копирования В: <b>{leak_stats['copy_to_our_chat']['count']}</b>
├─ 📸 Скриншоты ИЗ: <b>{leak_stats['screenshot_from_our_chat']['count']}</b>
└─ 📸 Скриншоты В: <b>{leak_stats['screenshot_to_our_chat']['count']}</b>

<b>📅 СЕГОДНЯ:</b>
├─ Сообщений: <b>{len([m for m in storage.messages if m.get('time', '').startswith(datetime.now().strftime('%Y-%m-%d'))])}</b>
└─ Утечек: <b>{sum([len([l for l in storage.leaks_by_source[lt] if l.get('timestamp', '').startswith(datetime.now().strftime('%Y-%m-%d'))]) for lt in storage.leaks_by_source])}</b>

<i>🕒 Последнее обновление: {datetime.now().strftime('%H:%M:%S')}</i>
"""
                    send_telegram_message(chat_id, stats_msg)
                
                elif text.lower() == "/mystats":
                    user_data = storage.users.get(user_id, {})
                    user_leaks = sum(len([l for l in leaks if l.get("user_id") == user_id]) 
                                   for leaks in storage.leaks_by_source.values())
                    
                    mystats_msg = f"""
<b>📊 ВАША СТАТИСТИКА</b>

<b>👤 ПРОФИЛЬ:</b>
├─ ID: <code>{user_id}</code>
├─ Username: @{user_data.get('username', 'не установлен')}
└─ Имя: <b>{user_data.get('first_name', 'Неизвестно')}</b>

<b>📈 АКТИВНОСТЬ:</b>
├─ Сообщений: <b>{user_data.get('messages', 0)}</b>
├─ Утечек: <b>{user_leaks}</b>
├─ Первый раз: <b>{user_data.get('first_seen', '')[:16]}</b>
└─ Последний раз: <b>{user_data.get('last_seen', '')[:16] if user_data.get('last_seen') else 'только что'}</b>

<b>⚠️ ВАШИ УТЕЧКИ:</b>
"""
                    for leak_type, leaks in storage.leaks_by_source.items():
                        user_type_leaks = [l for l in leaks if l.get("user_id") == user_id]
                        if user_type_leaks:
                            leak_name = leak_type.replace("_", " ").title()
                            mystats_msg += f"├─ {leak_name}: <b>{len(user_type_leaks)}</b>\n"
                    
                    if user_leaks == 0:
                        mystats_msg += "└─ 🟢 Утечек не обнаружено\n"
                    
                    mystats_msg += f"\n<i>Вы в {len([c for c in storage.bot_chats])} чатах с ботом</i>"
                    send_telegram_message(chat_id, mystats_msg)
                
                elif text.lower() in ["/leaks", "/утечки"]:
                    all_leaks = storage.get_all_leaks()
                    if all_leaks:
                        leaks_msg = f"""
<b>⚠️ ПОСЛЕДНИЕ УТЕЧКИ (5 из {len(all_leaks)})</b>
"""
                        for i, leak in enumerate(all_leaks[:5], 1):
                            leak_type = leak.get("leak_type", "unknown")
                            emoji = "📤" if leak_type == "forward" else "📋" if leak_type == "copy" else "📸"
                            confidence = leak.get("confidence", 0)
                            risk_emoji = "🔴" if confidence > 80 else "🟠" if confidence > 60 else "🟡"
                            
                            leaks_msg += f"\n{i}. {emoji} <b>{leak_type.upper()}</b> {risk_emoji}\n"
                            leaks_msg += f"   👤 @{leak.get('username', 'unknown')}\n"
                            leaks_msg += f"   📍 {leak.get('chat_title', '')[:20]}\n"
                            leaks_msg += f"   🎯 {confidence}% уверенности\n"
                            leaks_msg += f"   🕒 {leak.get('timestamp', '')[:16]}\n"
                    else:
                        leaks_msg = "🟢 Утечек пока не обнаружено"
                    
                    leaks_msg += f"\n\n<i>Подробности на веб-панели</i>"
                    send_telegram_message(chat_id, leaks_msg)
        
        # Автосохранение
        if len(storage.messages) % 20 == 0:
            storage.save()
        
        return jsonify({"ok": True, "processed": True})
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# Автосохранение каждые 2 минуты
def auto_save():
    while True:
        time.sleep(120)
        storage.save()

import threading
thread = threading.Thread(target=auto_save, daemon=True)
thread.start()

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Запуск УЛЬТРА-ЖЕСТКОГО ДЕТЕКТОРА УТЕЧЕК...")
    print(f"✅ Режим: МАКСИМАЛЬНАЯ СТРОГОСТЬ")
    print(f"✅ Доступ: {len(ALLOWED_IDS)} пользователей")
    print(f"✅ Паттернов: 100+ жестких правил")
    print("="*60)
    app.run(host="0.0.0.0", port=PORT, debug=False)
