from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any


class SettingsError(ValueError):
    pass


class Settings:
    def __init__(self) -> None:
        self.environment = _read("ENVIRONMENT", "development")
        self.log_level = _read("LOG_LEVEL", "info")
        self.database_url = _read("DATABASE_URL", "")
        self.auth_mode = _read("CAREAGENT_AUTH_MODE", "").lower() or (
            "firebase" if self.environment == "production" else "test"
        )
        self.firebase_project_id = _read("FIREBASE_PROJECT_ID", "")
        self.firebase_service_account_json = _read("FIREBASE_SERVICE_ACCOUNT_JSON", "")
        self.cors_allowed_origins = _read_list(
            "CORS_ALLOWED_ORIGINS",
            [
                "http://localhost:3000",
                "http://localhost:5173",
                "http://localhost:8080",
                "http://localhost:5000",
            ],
        )
        self.document_storage_bucket = _read("DOCUMENT_STORAGE_BUCKET", "careagent-documents")

    @property
    def use_database(self) -> bool:
        return bool(self.database_url)

    @property
    def require_firebase(self) -> bool:
        return self.auth_mode == "firebase"

    def firebase_credentials(self) -> dict[str, Any] | None:
        if not self.firebase_service_account_json:
            return None
        try:
            return json.loads(self.firebase_service_account_json)
        except json.JSONDecodeError as exc:
            raise SettingsError("FIREBASE_SERVICE_ACCOUNT_JSON must be valid JSON") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _read(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def _read_list(name: str, default: list[str]) -> list[str]:
    raw = _read(name, "")
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]
