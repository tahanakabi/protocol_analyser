from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    storage_dir: Path = Path(__file__).resolve().parent.parent / "storage"
    # Weights and caches for the optional PDF parsers (marker, unstructured, pymupdf4llm).
    model_cache_dir: Path = Path(__file__).resolve().parent.parent / ".models"
    max_upload_bytes: int = 50 * 1024 * 1024
    # Per LLM call: retrieved source blocks (chars). ~4 chars/token → 24k ≈ 6k tokens input.
    llm_context_char_budget: int = 24_000
    max_block_text_chars: int = 1_200
    retrieval_min_blocks: int = 6
    # Hybrid-ranked blocks added from outside the matched outline sections (0 = outline only).
    retrieval_extra_blocks: int = 6
    openai_embedding_model: str = "text-embedding-3-small"
    # Chat (RAG): blocks retrieved per question and how many earlier turns are sent back to the model.
    chat_top_k: int = 8
    chat_history_turns: int = 6
    cors_origins: str = "http://localhost:5173"


settings = Settings()
