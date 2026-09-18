from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List
from typing import Optional
from pydantic import field_validator

LLM_DATA_RESIDENCY_MODES = ("global", "eu", "self_hosted")


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "dev-secret"
    APP_CORS_ORIGINS: str = "http://localhost:3000"
    # Runtime URLs — these must point at `dataops_app`, a NOSUPERUSER /
    # NOBYPASSRLS role. Row-Level Security is silently and completely bypassed
    # for superusers and BYPASSRLS roles (FORCE ROW LEVEL SECURITY closes only
    # the table-*owner* bypass, not those two), so pointing these back at
    # `dataops_user` would leave every RLS policy in place but inert.
    DATABASE_URL: str = "postgresql+asyncpg://dataops_app:changeme@127.0.0.1:5432/dataops"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://dataops_app:changeme@127.0.0.1:5432/dataops"
    # Privileged URL — `dataops_user` (superuser/owner). Used ONLY by Alembic
    # migrations, test_schema_drift.py (which needs CREATE DATABASE), and
    # cross-tenant maintenance scripts. Never by a request-serving or Celery
    # code path; there is a regression test asserting exactly that.
    ADMIN_DATABASE_URL: str = "postgresql+psycopg2://dataops_user:changeme@127.0.0.1:5432/dataops"
    # Password the migration provisions `dataops_app` with. Kept separate from
    # the URLs so the role can be created before those URLs are usable.
    APP_DB_PASSWORD: str = "changeme"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    # Provider is DECLARED, not guessed from the model name. PRIMARY_LLM_PROVIDER
    # already existed here and was read by nothing -- llm_service inferred the
    # provider from substrings in the model name instead, which silently routed
    # every Groq model not containing "llama"/"mixtral"/"gemma" to Google.
    PRIMARY_LLM_PROVIDER: str = "gemini"
    PRIMARY_LLM_MODEL: str = "gemini-3.5-flash"
    FALLBACK_LLM_PROVIDER: str = "groq"
    FALLBACK_LLM_MODEL: str = "openai/gpt-oss-120b"
    # Security Master Ranking Item #11 (GDPR data residency). Where LLM
    # inference is allowed to run:
    #   global       the configured providers above (Gemini / Groq), whose
    #                own regions apply -- see docs/compliance/LLM_DATA_FLOW.md
    #   eu           an EU-resident endpoint. NOT IMPLEMENTED: every outbound
    #                LLM call is refused (DataResidencyError) rather than sent
    #                somewhere that does not satisfy the setting.
    #   self_hosted  a customer-operated OpenAI-compatible endpoint at
    #                LLM_SELF_HOSTED_ENDPOINT. NOT IMPLEMENTED: same refusal.
    # Deliberately fail-closed: a residency promise that silently falls back
    # to the global providers is worse than no setting at all. Validated at
    # import so a typo cannot boot as "global".
    LLM_DATA_RESIDENCY_MODE: str = "global"
    LLM_SELF_HOSTED_ENDPOINT: str = ""
    # Security Master Ranking Item #13 (MFA). TOTP is mandatory for owners and
    # admins; they get this many days from becoming one (or from the deploy
    # that introduced the rule) to enrol before privileged routes refuse them.
    MFA_GRACE_DAYS: int = 7
    MFA_ISSUER: str = "Wunomo"
    JWT_SECRET: str = "dev-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    # Fernet key encrypting DataSource.connection_config at rest. Deliberately
    # defaults to empty rather than to a usable dev key: services/
    # encryption_service.py raises at startup when it's unset outside tests,
    # because a silently-defaulted key would encrypt real credentials with a
    # value that is public in this repo. Never commit a real key here.
    CREDENTIAL_ENCRYPTION_KEY: str = ""
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "axiom@dataops.ai"
    SMTP_USE_TLS: bool = True
    ALERT_EMAIL: str = ""
    # Item #9 follow-up: where the daily audit-chain tail hashes are mailed.
    # Empty means "not anchored" and the task logs an ERROR every run until
    # it is set -- the local file it also writes is a convenience copy on the
    # same host, not an anchor.
    ANCHOR_NOTIFICATION_EMAIL: str = ""
    AUDIT_ANCHOR_LOG_PATH: str = "audit_chain_anchors.log"
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

    @field_validator("LLM_DATA_RESIDENCY_MODE")
    @classmethod
    def _residency_mode_known(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in LLM_DATA_RESIDENCY_MODES:
            raise ValueError(
                f"LLM_DATA_RESIDENCY_MODE={v!r} is not one of {LLM_DATA_RESIDENCY_MODES}")
        return v

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