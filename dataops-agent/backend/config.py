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
    FALLBACK_LLM_MODEL: str = "llama-3.3-70b-versatile"
    JWT_SECRET: str = "dev-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
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

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.APP_CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()