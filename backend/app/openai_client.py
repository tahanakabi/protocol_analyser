from openai import OpenAI

from app.config import settings
from app.vector_store import Embedder


def client() -> OpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def openai_embedder() -> Embedder:
    api = client()

    def embed(texts: list[str]) -> list[list[float]]:
        response = api.embeddings.create(model=settings.openai_embedding_model, input=texts)
        return [item.embedding for item in response.data]

    return embed
