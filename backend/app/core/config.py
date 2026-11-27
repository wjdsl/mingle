"""애플리케이션 설정.

모든 값은 환경변수 또는 backend/.env 로 덮어쓸 수 있습니다.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    admin_email: str = ""
    admin_password: str = ""
    admin_name: str = "관리자"

    # --- CORS (쉼표 구분) ---
    cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,"
        "http://127.0.0.1:3000"
    )

    # --- LLM ---
    # auto: openai 키 -> gemini 키 -> mock 순서로 자동 선택
    llm_provider: str = "auto"  # auto | openai | gemini | qwen | mock (qwen은 명시 지정 시에만 선택)
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_chat_model: str = "gemini-3.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_http_attempts: int = Field(default=2, ge=1, le=2)
    story_generation_attempts: int = Field(default=2, ge=1, le=2)
    # 스토리 응답에 Gemini responseJsonSchema를 지정한다. 모델이 거부(400)하면 false로 끈다.
    story_response_schema: bool = True
    gemini_thinking_level: Literal["", "minimal", "low", "medium", "high"] = ""
    gemini_thinking_budget: int = 0  # 구형 옵션. -1이면 공급자 기본값을 사용한다.
    # Colab에서 실행하는 Qwen EXP-004 추론 API. LLM_PROVIDER=qwen 일 때만 사용한다.
    qwen_api_url: str | None = None
    qwen_api_key: str | None = None
    qwen_timeout_seconds: float = 120.0
    # 냉장고 회장님 대사만 Qwen EXP-004로 다시 쓰는 하이브리드 모드(기본 꺼짐). 스토리·JSON·선택지·상태는 계속 Gemini가 만든다.
    # 켜면 QWEN_API_URL/QWEN_API_KEY가 필요하며, 실패하면 Gemini 원본 대사를 쓴다.
    fridge_qwen_dialogue_enabled: bool = False
    fridge_qwen_timeout_seconds: float = Field(default=25.0, gt=0, le=120)
    fridge_qwen_max_tokens: int = Field(default=200, ge=1, le=300)
    llm_timeout_seconds: float = 30.0
    # 비우면 파일 로그를 쓰지 않는다. 지정하면 Gemini·스토리 API의 WARNING 이상만 회전 파일에 남긴다.
    llm_failure_log_file: str = ""
    llm_temperature: float = 0.8
    llm_max_tokens: int = 700
    # 일일 LLM 비용 상한(USD). 0 이면 제한 없음.
    daily_llm_cost_cap_usd: float = 0.0
    # 비용 추정용 1k 토큰당 가격(USD). 0이면 비용 추정 0.
    llm_cost_per_1k_tokens_usd: float = 0.002

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
    seed_on_startup: bool = False
    llm_probe_on_startup: bool = True

    # --- Redis (레이트 리밋 / 분산 락) ---
    redis_url: str | None = None

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
