"""Environment settings + YAML config. Credentials come from the environment only, never YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "config").is_dir():
            return candidate
    return current


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    root: Path = field(default_factory=project_root)
    env: str = field(default_factory=lambda: _env("TENDER_SCOUT_ENV", "local"))
    log_level: str = field(default_factory=lambda: _env("TENDER_SCOUT_LOG_LEVEL", "INFO"))
    user_agent: str = field(
        default_factory=lambda: _env("TENDER_SCOUT_USER_AGENT", "TenderScout/0.1 (tender monitoring for a small contractor)")
    )
    # Email: SMTP (Microsoft 365, Gmail...) or Resend. Whichever is configured is used.
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587") or 587))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    resend_api_key: str = field(default_factory=lambda: _env("RESEND_API_KEY"))
    email_from: str = field(default_factory=lambda: _env("EMAIL_FROM"))
    email_to: str = field(default_factory=lambda: _env("EMAIL_TO"))
    dashboard_url: str = field(default_factory=lambda: _env("DASHBOARD_URL"))

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    def email_configured(self) -> bool:
        has_transport = bool(self.resend_api_key or self.smtp_host)
        return has_transport and bool(self.email_from and self.email_to)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _load_yaml(name: str) -> dict[str, Any]:
    path = get_settings().config_dir / name
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_profile() -> dict[str, Any]:
    return _load_yaml("profile.yaml")


def load_sources() -> dict[str, Any]:
    return _load_yaml("sources.yaml")
