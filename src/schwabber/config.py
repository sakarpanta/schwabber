from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str
    schwab_client_id: str | None
    schwab_client_secret: str | None
    callback_url: str
    token_path: Path
    refresh_token_max_age_days: int
    refresh_token_warn_age_days: int
    requests_per_minute: int
    log_level: str
    sec_user_agent: str | None = None

    @property
    def schwab_configured(self) -> bool:
        return bool(self.schwab_client_id and self.schwab_client_secret)

    @property
    def sec_configured(self) -> bool:
        return bool(self.sec_user_agent and "@" in self.sec_user_agent)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> Settings:
        api_key = values.get("SCHWABBER_API_KEY", "")
        if len(api_key) < 32:
            raise ConfigurationError("SCHWABBER_API_KEY must be at least 32 characters")
        try:
            max_age = int(values.get("SCHWAB_REFRESH_TOKEN_MAX_AGE_DAYS", "7"))
            warn_age = int(values.get("SCHWAB_REFRESH_TOKEN_WARN_AGE_DAYS", "6"))
            rpm = int(values.get("SCHWABBER_REQUESTS_PER_MINUTE", "60"))
        except ValueError as exc:
            raise ConfigurationError(
                "Numeric configuration values must be integers"
            ) from exc
        if max_age <= 0 or not 0 <= warn_age < max_age:
            raise ConfigurationError(
                "Schwab token warning age must be below its positive maximum age"
            )
        if rpm <= 0:
            raise ConfigurationError("SCHWABBER_REQUESTS_PER_MINUTE must be positive")
        return cls(
            api_key=api_key,
            schwab_client_id=values.get("SCHWAB_CLIENT_ID") or None,
            schwab_client_secret=values.get("SCHWAB_CLIENT_SECRET") or None,
            callback_url=values.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
            token_path=Path(values.get("SCHWAB_TOKEN_PATH", "/data/token.json")),
            refresh_token_max_age_days=max_age,
            refresh_token_warn_age_days=warn_age,
            requests_per_minute=rpm,
            log_level=values.get("SCHWABBER_LOG_LEVEL", "INFO"),
            sec_user_agent=values.get("SEC_USER_AGENT") or None,
        )

    @classmethod
    def from_env(cls) -> Settings:
        return cls.from_mapping(os.environ)
