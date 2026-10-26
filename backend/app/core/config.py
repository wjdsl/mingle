"""애플리케이션 설정.

모든 값은 환경변수 또는 backend/.env 로 덮어쓸 수 있습니다.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 앱 ---
    app_name: str = "Persona Companion AI API"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = True
    api_prefix: str = "/api"

    # --- 데이터베이스 ---
    # 기본값은 별도 설치 없이 바로 실행 가능한 SQLite.
    # 운영/배포 시 postgresql+asyncpg://user:pass@host:5432/dbname 로 변경하면 pgvector를 사용합니다.
    database_url: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'app.db').as_posix()}"
    db_echo: bool = False

    # --- 인증 ---
    secret_key: str = "change-me-in-production-please-use-32-bytes"
    access_token_expire_minutes: int = 720  # 관리자 JWT (12시간)
    admin_email: str = "admin@companion.ai"
    admin_password: str = "admin1234!"
    admin_name: str = "관리자"

    # --- CORS (쉼표 구분) ---
    cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,"
        "http://127.0.0.1:3000"
    )

    # --- LLM ---
    # auto: openai 키 -> gemini 키 -> mock 순서로 자동 선택
    llm_provider: str = "auto"  # auto | openai | gemini | mock
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_chat_model: str = "gemini-3.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_thinking_budget: int = 0  # 0=thinking 비활성(빠른 응답), -1=모델 기본값
    llm_timeout_seconds: float = 30.0
    llm_temperature: float = 0.8
    llm_max_tokens: int = 700

    # --- RAG ---
    embedding_dim: int = 1536
    rag_top_k: int = 4
    rag_min_score: float = 0.05
    context_message_limit: int = 12

    # --- 기억(User Note) ---
    memory_extraction_enabled: bool = True
    memory_llm_enabled: bool = False  # True면 LLM으로 기억 추출(비용 발생)
    memory_compaction_threshold: int = 12

    # --- 대화/마케팅 ---
    trigger_llm_judge_enabled: bool = False
    guardrail_enabled: bool = True
    seed_on_startup: bool = True

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_provider(self) -> str:
        explicit = (self.llm_provider or "auto").lower()
        if explicit != "auto":
            return explicit
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        return "mock"

    def ensure_dirs(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
