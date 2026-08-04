"""
config.py — central configuration + secrets abstraction (Sprint 1, S1-06).

One typed Settings object read from the environment, with a vault-ready
`get_secret()` seam: it tries a secrets backend (Vault/SSM) when configured,
else falls back to env. No secret is hard-coded; production points
SECRETS_BACKEND at a real vault and nothing else changes.
"""
from __future__ import annotations
import os
from typing import Optional


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Resolve a secret. Order: explicit env var -> secrets backend -> default.
    The backend hook is intentionally minimal; wire HashiCorp Vault / AWS SSM by
    implementing `_backend_get`."""
    if name in os.environ:
        return os.environ[name]
    backend = os.environ.get("SECRETS_BACKEND")
    if backend:
        val = _backend_get(backend, name)
        if val is not None:
            return val
    return default


def _backend_get(backend: str, name: str) -> Optional[str]:
    # Placeholder for Vault/SSM. Returns None until wired (so it never silently
    # returns a wrong/empty secret). Implement per your infra in Sprint 9.
    return None


class Settings:
    def __init__(self) -> None:
        self.env = os.environ.get("APP_ENV", "dev")
        self.database_url = os.environ.get("DATABASE_URL", "sqlite:///./drip_dev.db")
        self.migrate_database_url = os.environ.get("MIGRATE_DATABASE_URL", self.database_url)
        self.redis_url = os.environ.get("REDIS_URL")
        self.jwt_secret = get_secret("JWT_SECRET", "drip-dev-jwt-secret-change-me")
        self.auth_enforced = os.environ.get("AUTH_ENFORCED", "false").lower() == "true"
        self.mandrill_webhook_key = get_secret("MANDRILL_WEBHOOK_KEY", "")
        self.enable_ses = os.environ.get("ENABLE_SES_TRANSPORT", "false").lower() == "true"
        self.scheduler_timezone = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Riyadh")
        self.service_name = os.environ.get("SERVICE_NAME", "drip-api")
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")

    def validate_runtime(self) -> None:
        """Fail closed when a deployment declares itself production.

        Startup-time guard, not a lint: `APP_ENV=prod` with any of dev-mode
        auth-off, the default JWT secret, a SQLite DATABASE_URL, a missing
        ADMIN_PASSWORD, or a wildcard/empty CORS allowlist means the process
        refuses to boot rather than silently serving unsafely-configured prod
        traffic. No-op for every other APP_ENV value (dev/test/staging).
        """
        if self.env.lower() not in {"prod", "production"}:
            return
        errors = []
        if not self.auth_enforced:
            errors.append("AUTH_ENFORCED must be true")
        if self.jwt_secret == "drip-dev-jwt-secret-change-me" or len(self.jwt_secret or "") < 32:
            errors.append("JWT_SECRET must be a non-default secret of at least 32 characters")
        if self.database_url.startswith("sqlite"):
            errors.append("production DATABASE_URL must use PostgreSQL")
        if not os.environ.get("ADMIN_PASSWORD"):
            errors.append("ADMIN_PASSWORD must be configured")
        origins = [x.strip() for x in os.environ.get("CORS_ORIGINS", "").split(",") if x.strip()]
        if not origins or "*" in origins:
            errors.append("CORS_ORIGINS must be an explicit production allowlist")
        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))

    def redacted(self) -> dict:
        """Safe-to-log view (secrets masked) — used by /health/ready."""
        def mask(v):
            return (v[:3] + "***") if v else None
        return {"env": self.env, "auth_enforced": self.auth_enforced,
                "redis": bool(self.redis_url), "ses": self.enable_ses,
                "jwt_secret": mask(self.jwt_secret), "db": self.database_url.split("@")[-1]}


settings = Settings()
