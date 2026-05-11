from __future__ import annotations

import json
import os
from functools import lru_cache
from urllib.parse import urlparse
from typing import Any


class SettingsError(ValueError):
    pass


class Settings:
    def __init__(self) -> None:
        self.environment = _read("ENVIRONMENT", "development").lower()
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
        self.trusted_hosts = _read_list(
            "TRUSTED_HOSTS",
            ["localhost", "127.0.0.1", "testserver"],
        )
        self.max_request_body_bytes = _read_int(
            "MAX_REQUEST_BODY_BYTES",
            8 * 1024 * 1024,
        )
        self.rate_limit_window_seconds = _read_int("RATE_LIMIT_WINDOW_SECONDS", 60)
        self.rate_limit_sensitive_requests = _read_int(
            "RATE_LIMIT_SENSITIVE_REQUESTS",
            120,
        )
        self.api_docs_enabled = _read_bool("ENABLE_API_DOCS", not self.is_production)
        self.voice_provider_adapter = _read("VOICE_PROVIDER_ADAPTER", "mock").lower()
        self.make_mcp_server_url = _read("MAKE_MCP_SERVER_URL", "")
        self.make_mcp_bearer_token = _read("MAKE_MCP_BEARER_TOKEN", "")
        self.make_mcp_call_tool_name = _read("MAKE_MCP_CALL_TOOL_NAME", "")
        self.make_mcp_timeout_seconds = _read_int("MAKE_MCP_TIMEOUT_SECONDS", 20)
        self.make_mcp_allow_real_calls = _read_bool("MAKE_MCP_ALLOW_REAL_CALLS", False)
        self._validate()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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

    def _validate(self) -> None:
        if self.auth_mode not in {"firebase", "test"}:
            raise SettingsError("CAREAGENT_AUTH_MODE must be 'firebase' or 'test'")

        if self.voice_provider_adapter not in {"mock", "make_mcp"}:
            raise SettingsError("VOICE_PROVIDER_ADAPTER must be 'mock' or 'make_mcp'")

        if self.make_mcp_timeout_seconds <= 0:
            raise SettingsError("MAKE_MCP_TIMEOUT_SECONDS must be greater than zero")

        if self.voice_provider_adapter == "make_mcp":
            missing_make_mcp = [
                name
                for name, value in {
                    "MAKE_MCP_SERVER_URL": self.make_mcp_server_url,
                    "MAKE_MCP_BEARER_TOKEN": self.make_mcp_bearer_token,
                    "MAKE_MCP_CALL_TOOL_NAME": self.make_mcp_call_tool_name,
                }.items()
                if not value
            ]
            if missing_make_mcp:
                raise SettingsError(
                    f"{', '.join(missing_make_mcp)} required when VOICE_PROVIDER_ADAPTER=make_mcp"
                )

        if self.is_production and self.make_mcp_allow_real_calls:
            raise SettingsError("MAKE_MCP_ALLOW_REAL_CALLS must remain false in production")

        if self.max_request_body_bytes <= 0:
            raise SettingsError("MAX_REQUEST_BODY_BYTES must be greater than zero")

        if self.rate_limit_window_seconds <= 0:
            raise SettingsError("RATE_LIMIT_WINDOW_SECONDS must be greater than zero")

        if self.rate_limit_sensitive_requests <= 0:
            raise SettingsError("RATE_LIMIT_SENSITIVE_REQUESTS must be greater than zero")

        if not self.is_production:
            return

        if not self.database_url:
            raise SettingsError("DATABASE_URL is required when ENVIRONMENT=production")

        database_user = urlparse(self.database_url).username or ""
        if database_user.lower() in {"postgres", "supabase_admin"}:
            raise SettingsError("Production DATABASE_URL must not use a Postgres admin user")

        if self.auth_mode != "firebase":
            raise SettingsError("Production CAREAGENT_AUTH_MODE must be firebase")

        if not (self.firebase_project_id or self.firebase_service_account_json):
            raise SettingsError(
                "FIREBASE_PROJECT_ID or FIREBASE_SERVICE_ACCOUNT_JSON is required in production"
            )

        if not self.cors_allowed_origins:
            raise SettingsError("CORS_ALLOWED_ORIGINS is required in production")

        for origin in self.cors_allowed_origins:
            if origin == "*" or origin.startswith("http://localhost"):
                raise SettingsError("Production CORS_ALLOWED_ORIGINS must be explicit HTTPS origins")
            if not origin.startswith("https://"):
                raise SettingsError("Production CORS_ALLOWED_ORIGINS must use HTTPS")

        if not self.trusted_hosts or "*" in self.trusted_hosts:
            raise SettingsError("TRUSTED_HOSTS must be explicit in production")

        if self.api_docs_enabled:
            raise SettingsError("ENABLE_API_DOCS must be false in production")


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


def _read_int(name: str, default: int) -> int:
    raw = _read(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc


def _read_bool(name: str, default: bool) -> bool:
    raw = _read(name, "")
    if not raw:
        return default
    normalized = raw.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean")
