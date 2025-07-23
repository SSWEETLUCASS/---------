# gigachat_wrapper.py

from langchain_gigachat import GigaChat, GigaChatEmbeddings
from secret_data import token

AUTH_URL = "https://sm-auth-sd.prom-88-89-apps.ocp-geo.ocp.sigma.sbrf.ru/api/v2/oauth"


def get_llm() -> GigaChat:
    return GigaChat(
        credentials=token,
        auth_url=AUTH_URL,
        verify_ssl_certs=False,
        scope="GIGACHAT_API_CORP",
        model="GigaChat-2-Max",
        top_p=0,
        profanity_check=False,
    )


def get_embedder() -> GigaChatEmbeddings:
    return GigaChatEmbeddings(
        credentials=token,
        auth_url=AUTH_URL,
        verify_ssl_certs=False,
        scope="GIGACHAT_API_CORP",
        model="Embeddings",
    )


def check_idea_with_gigachat_local(user_input: str, user_data: dict) -> tuple[str, bool]:
    try:
        wb = load_workbook("agents.xlsm", data_only=True)
        ws = wb.active
        all_agents_data = []

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[4]:  # Название инициативы
                continue

            block, ssp, owner, contact, name, short_name, desc, typ = row
            full_info = f"""Блок: {block}
ССП: {ssp}
Владелец: {owner}
Контакт: {contact}
Название инициативы: {name}
Краткое название: {short_name}
Описание: {desc}
Тип: {typ}"""
            all_agents_data.append(full_info)

        joined_data = "\n\n".join(all_agents_data)
    except Exception as e:
        joined_data = "(не удалось загрузить данные об инициативах)"
    
    # Отправка в GigaChat
    prompt = f"""
Вот инициатива от пользователя:
Название: {user_data['Название инициативы']}
Краткое название: {user_data['Краткое название']}
Описание: {user_data['Описание инициативы']}
Тип: {user_data['Тип инициативы']}

Сравни её с известными инициативами ниже и ответь:
- Если идея похожа на существующие — напиши "НЕ уникальна".
- Если идея действительно новая — напиши "Уникальна".

Инициативы:
{joined_data}
"""
    from gigachat_wrapper import get_llm
    response = get_llm().invoke(prompt)

    cleaned_response = response.replace('\\n', '\n').replace('\"', '"').strip().lower()
    is_unique = "уникальна" in cleaned_response and "не уникальна" not in cleaned_response

    return cleaned_response, is_unique

