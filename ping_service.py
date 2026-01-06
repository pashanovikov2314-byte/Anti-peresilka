import requests
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def keep_alive(url):
    while True:
        try:
            response = requests.get(url, timeout=30)
            logger.info(f"✅ Пинг отправлен: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Ошибка пинга: {e}")
        
        # Ждем 5 минут перед следующим пингом
        time.sleep(300)

if __name__ == "__main__":
    # Замените на URL вашего бота на Render
    keep_alive("https://ваш-бот.onrender.com")
