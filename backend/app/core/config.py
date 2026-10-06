"""Central application settings.

Every value can be overridden from the project-root ``.env`` file or from
real environment variables. Keep secrets (API keys) ONLY in ``.env`` – that
file is git-ignored and must never be committed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "Lumina"
    app_version: str = "7.0.0"
    host: str = "127.0.0.1"
    port: int = 5001
    log_level: str = "INFO"

    # Comma-separated list of allowed browser origins.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    # ------------------------------------------------------------------
    # Database & storage
    # ------------------------------------------------------------------
    database_url: str = "sqlite:///./storage/app.db"
    upload_dir: str = "storage/uploads"
    temp_dir: str = "storage/temporary"
    summary_dir: str = "storage/summaries"
    rag_dir: str = "storage/rag"

    max_file_size_mb: int = 25
    delete_source_after_processing: bool = False

    # ------------------------------------------------------------------
    # Local LLM (Ollama)
    # ------------------------------------------------------------------
    # "ollama" (default) or "openai" for any OpenAI-compatible server:
    # LM Studio, llama.cpp server, vLLM, Jan, LocalAI – or a cloud API.
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"

    # OpenAI-compatible settings (only used when LLM_PROVIDER=openai)
    openai_base_url: str = "http://127.0.0.1:1234/v1"
    openai_api_key: str = ""
    openai_model: str = "local-model"
    openai_embedding_model: str = ""

    llm_timeout: int = 600
    # How many requests may run on the model at the same time (1 = best for CPU).
    llm_max_parallel: int = 1
    # Speed-aware reading: answers always keep their full length. On a slow
    # computer the model reads fewer, more focused passages so the first word
    # appears within about this many seconds (measured automatically).
    adaptive_speed: bool = True
    read_target_seconds: int = 15
    summary_read_target_seconds: int = 30
    # Optional safety net: stop writing after this many seconds (0 = never –
    # the default, so answers are always complete).
    answer_hard_limit_seconds: int = 0
    llm_temperature: float = 0.15
    llm_max_tokens: int = 700
    # Context window passed to Ollama. Bigger = slower prompt processing.
    llm_num_ctx: int = 4096
    # How long Ollama keeps the model in memory after a request.
    llm_keep_alive: str = "2h"
    # Load the model into memory when the backend starts (faster 1st answer).
    llm_warmup_on_startup: bool = True
    # Number of previous chat messages sent for follow-up questions.
    chat_history_messages: int = 6
    # CPU threads Ollama may use (0 = let Ollama decide).
    llm_num_thread: int = 0

    # ------------------------------------------------------------------
    # Answer cache – repeated questions are answered instantly from RAM
    # ------------------------------------------------------------------
    answer_cache_enabled: bool = True
    answer_cache_size: int = 300

    # ------------------------------------------------------------------
    # Chunking (smaller chunks = sharper retrieval and faster answers)
    # ------------------------------------------------------------------
    chunk_size: int = 1400
    chunk_overlap: int = 200
    max_chunks: int = 2000

    # ------------------------------------------------------------------
    # RAG (semantic retrieval with local embeddings)
    # ------------------------------------------------------------------
    rag_enabled: bool = True
    rag_embedding_model: str = "embeddinggemma"
    rag_top_k: int = 5
    rag_max_context_chars: int = 5000
    rag_embed_batch: int = 4
    # How many document indexes to keep cached in RAM.
    rag_cache_size: int = 32

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------
    summary_max_context_chars: int = 9000
    summary_max_tokens: int = 900

    # Suggested questions: False = instant (from key terms, no AI call).
    # True = written by the AI model (nicer, but slow on CPU-only PCs).
    llm_suggestions: bool = False

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    tesseract_cmd: str = ""
    ocr_dpi: int = 180
    ocr_min_chars: int = 120
    ocr_language: str = "eng"
    ocr_workers: int = 4

    # ------------------------------------------------------------------
    # Web research (optional). Leave empty to use the free fallbacks.
    # ------------------------------------------------------------------
    web_research_enabled: bool = True
    google_api_key: str = ""
    google_cse_id: str = ""
    research_max_tokens: int = 800

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def provider(self) -> str:
        return "openai" if self.llm_provider.strip().lower() in {"openai", "openai_compatible", "lmstudio", "llamacpp", "vllm"} else "ollama"

    @property
    def default_model(self) -> str:
        return self.openai_model if self.provider == "openai" else self.ollama_model

    @property
    def embedding_model(self) -> str:
        if self.provider == "openai":
            return self.openai_embedding_model
        return self.rag_embedding_model

    @property
    def google_search_configured(self) -> bool:
        return bool(self.google_api_key and self.google_cse_id)

    def ensure_dirs(self) -> None:
        for directory in (
            self.upload_dir,
            self.temp_dir,
            self.summary_dir,
            self.rag_dir,
        ):
            Path(directory).mkdir(parents=True, exist_ok=True)

        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.replace("sqlite:///", "", 1))
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
