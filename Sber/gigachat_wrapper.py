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


