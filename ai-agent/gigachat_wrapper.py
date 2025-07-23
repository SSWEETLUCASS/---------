import requests
import os
import json
import uuid
from config import sigma_run
from secret_data import token

from langchain_core.language_models.llms import LLM
from time import perf_counter, sleep
from typing import Union, Any

import urllib3
urllib3.disable_warnings()

GIGACHAT_API_URL = 'https://gigachat.devices.sberbank.ru/api/v1'


def completions(query: str) -> str:
    """Отправка запроса в GigaChat и получение ответа."""
    if not token:
        return "⚠️ Ошибка: токен не найден в `secret_data.py`"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    data = {
        "model": "GigaChat-Max",
        "messages": [
            {"role": "user", "content": query}
        ],
        "n": 1,
        "top_p": 0,
    }

    if sigma_run:
        data['profanity_check'] = False

    try:
        response = requests.post(
            url=GIGACHAT_API_URL + "/chat/completions",
            headers=headers,
            json=data,
            verify=False
        )

        if response.ok:
            return json.loads(response.text)['choices'][0]['message']['content']
        else:
            return f"⚠️ Ошибка GigaChat: {response.status_code} — {response.text}"
    except Exception as e:
        return f"⚠️ Исключение при обращении к GigaChat: {e}"


def check_idea_with_gigachat(user_input: str, agents_list: str) -> str:
    """Создаёт промпт и отправляет его в GigaChat."""
    prompt = (
        f"Вот список существующих AI-агентов:\n{agents_list}\n\n"
        f"Пользователь предлагает идею: {user_input}.\n"
        "Проверь, есть ли похожие идеи. Ответь кратко и по делу. Если идея уникальна, напиши 'Контакт лидера: ...'."
    )
    return completions(prompt)

class GigaChatLLM(LLM):
    invoke_delay: Union[int, float] = 7 if not sigma_run else 0
    last_invoke: Any = 0

    def _call(self, prompt, stop=None, run_manager=None, **kwargs) -> str:
        if perf_counter() - self.last_invoke < self.invoke_delay:
            sleep(self.invoke_delay - (perf_counter() - self.last_invoke))

        self.last_invoke = perf_counter()

        if stop is not None:
            raise ValueError("stop kwargs are not permitted.")

        return completions(prompt)

    @property
    def _llm_type(self) -> str:
        return "customGigaChatModel"
