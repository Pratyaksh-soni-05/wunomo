from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List
from typing import Optional


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "dev-secret"
    APP_CORS_ORIGINS: str = "http://localhost:3000"
    DATABASE_URL: str = "postgresql+asyncpg://dataops_user:changeme@127.0.0.1:5432/dataops"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://dataops_user:changeme@127.0.0.1:5432/dataops"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    PRIMARY_LLM_PROVIDER: str = "gemini"
    PRIMARY_LLM_MODEL: str = "gemini-3.5-flash"
    FALLBACK_LLM_MODEL: str = "openai/gpt-oss-120b"
    JWT_SECRET: str = "dev-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "axiom@dataops.ai"
    SMTP_USE_TLS: bool = True
    ALERT_EMAIL: str = ""
    SLACK_BOT_TOKEN: str = ""
    SLACK_DEFAULT_CHANNEL: str = "#dataops-alerts"
    ENABLE_AUTONOMOUS_MODE: bool = False
    ENABLE_DESTRUCTIVE_ACTIONS: bool = False
    MAX_PIPELINE_RETRIES: int = 3
    MAX_ROWS_PER_PREVIEW: int = 1000
    SLACK_WEBHOOK_URL: Optional[str] = None
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:3000/api/auth/callback/google"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = ""
    # Wunomo Projects Phase 2 frontend, slice 9: the first place a backend
    # notification embeds a real, clickable link back into the app -- every
    # earlier alert (incident, pipeline failure, stale sources) was plain
    # text with no URL at all. Same default-localhost-3000 convention
    # GOOGLE_OAUTH_REDIRECT_URI above already uses for "the frontend."
    FRONTEND_URL: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> List[str]:
        origins = [o.strip() for o in self.APP_CORS_ORIGINS.split(",") if o.strip()]
        if self.APP_ENV == "development":
            # Next dev silently falls back to 3001/3002/etc when 3000 is held
            # by a stray process (has bitten this project twice — a CORS-
            # blocked Google OAuth button that looked dead, and a "no changes
            # visible" report against stale code on 3000 while work was live
            # on 3001). Widen to the common fallback ports/hosts in dev only;
            # production/staging always use APP_CORS_ORIGINS verbatim, no
            # widening — see docs/context/WALKTHROUGH_FINDINGS_2026-08.md.
            dev_extras = [
                f"http://{host}:{port}"
                for host in ("localhost", "127.0.0.1")
                for port in (3000, 3001, 3002)
            ]
            origins = sorted(set(origins) | set(dev_extras))
        return origins

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()