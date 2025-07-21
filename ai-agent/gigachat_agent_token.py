import os
import uuid
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# === Конфигурация ===
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")  # base64(<client_id>:<client_secret>)
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
GIGACHAT_TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

token_cache = {"access_token": None, "expires_at": None}

# === Получение токена по токену авторизации ===
def get_gigachat_token():
    global token_cache
    if token_cache["access_token"] and token_cache["expires_at"] > datetime.utcnow():
        return token_cache["access_token"]

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }

    data = {'scope': GIGACHAT_SCOPE}

    print("Запрашиваем токен...")
    response = requests.post(GIGACHAT_TOKEN_URL, headers=headers, data=data, verify=True)
    response.raise_for_status()

    result = response.json()
    token_cache["access_token"] = result['access_token']
    token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=result['expires_in'])
    print("Токен получен.")
    return token_cache["access_token"]

# === Отправка сообщения в GigaChat ===
def ask_gigachat(question: str) -> str:
    token = get_gigachat_token()

    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }

    payload = {
        "model": "GigaChat-Pro",
        "messages": [
            {"role": "user", "content": question}
        ]
    }

    print("Отправляем запрос в GigaChat...")
    response = requests.post(GIGACHAT_API_URL, headers=headers, json=payload, verify=True)
    response.raise_for_status()

    reply = response.json()["choices"][0]["message"]["content"]
    return reply

# === Основной запуск ===
if __name__ == "__main__":
    user_input = input("Введите вопрос для GigaChat: ")
    try:
        response = ask_gigachat(user_input)
        print("\n🤖 Ответ GigaChat:")
        print(response)
    except Exception as e:
        print(f"Ошибка: {e}")
