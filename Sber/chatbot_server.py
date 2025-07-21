import logging
from aiohttp import web

from agent_core import check_idea_with_gigachat, generate_files, TEMPLATE_FIELDS

logging.basicConfig(level=logging.INFO)

user_states = {}

async def handler(request):
    data = await request.json()
    user_id = data['from']['userId']
    text = data['message']['text'].strip()

    if user_id not in user_states:
        user_states[user_id] = {}

    if text.lower() in ["/start", "привет"]:
        return web.json_response({"text": "👋 Привет! Опиши свою идею, и я проверю её уникальность."})

    if "step" not in user_states[user_id]:
        response = check_idea_with_gigachat(text)
        user_states[user_id]["last_idea"] = text
        user_states[user_id]["summary"] = response

        if any(word in response.lower() for word in ["уникальн"]):
            user_states[user_id]["step"] = 0
            user_states[user_id]["data"] = {TEMPLATE_FIELDS[0]: text}
            return web.json_response({"text": f"Идея выглядит уникальной! Давай заполним шаблон.\n1️⃣ {TEMPLATE_FIELDS[1]}:"})
        else:
            return web.json_response({"text": f"Похоже, такая идея уже есть.\n\n🤖 Ответ GigaChat:\n{response}"})
    else:
        state = user_states[user_id]
        step = state["step"] + 1
        state["data"][TEMPLATE_FIELDS[step]] = text
        if step + 1 < len(TEMPLATE_FIELDS):
            state["step"] = step
            return web.json_response({"text": f"{step+1}️⃣ {TEMPLATE_FIELDS[step+1]}:"})
        else:
            generate_files(state["data"])
            del user_states[user_id]
            return web.json_response({"text": "✅ Файлы готовы. Спасибо!"})

app = web.Application()
app.router.add_post("/gigabot", handler)

if __name__ == '__main__':
    web.run_app(app, port=8080)
