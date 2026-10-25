"""Settings, read once from environment variables (see .env.example)."""

import os
import secrets
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Mrigel"
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./mrigel.db"))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY") or secrets.token_urlsafe(32))
    secure_cookies: bool = field(default_factory=lambda: _bool("SECURE_COOKIES", False))
    default_lang: str = field(default_factory=lambda: os.getenv("DEFAULT_LANG", "ar"))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    cron_token: str = field(default_factory=lambda: os.getenv("CRON_TOKEN", ""))
    run_jobs_in_process: bool = field(default_factory=lambda: _bool("RUN_JOBS", True))
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", False))
    trust_proxy: bool = field(default_factory=lambda: _bool("TRUST_PROXY", False))
    whatsapp_api_version: str = field(default_factory=lambda: os.getenv("WHATSAPP_API_VERSION", "v21.0"))
    # the address buyers see in links (order form). Render sets RENDER_EXTERNAL_URL on its own.
    public_url: str = field(default_factory=lambda: (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/"))
    support_email: str = field(default_factory=lambda: os.getenv("SUPPORT_EMAIL", "").strip())
    support_whatsapp: str = field(default_factory=lambda: os.getenv("SUPPORT_WHATSAPP", "").strip())
    # lets the operator set a new password for a merchant who lost theirs (/admin/reset). Empty = off.
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", "").strip())


settings = Settings()
