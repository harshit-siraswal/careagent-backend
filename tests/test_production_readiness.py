from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings, SettingsError


PRODUCTION_ENV = {
    "ENVIRONMENT": "production",
    "CAREAGENT_AUTH_MODE": "firebase",
    "DATABASE_URL": "postgresql://careagent_app:secret@db.example.com:5432/postgres",
    "FIREBASE_PROJECT_ID": "careagent-pilot",
    "CORS_ALLOWED_ORIGINS": "https://app.careagent.example",
    "TRUSTED_HOSTS": "api.careagent.example",
    "ENABLE_API_DOCS": "false",
}


def _set_production_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    keys = set(PRODUCTION_ENV) | set(overrides)
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**PRODUCTION_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)


def test_production_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_production_env(monkeypatch, DATABASE_URL="")

    with pytest.raises(SettingsError, match="DATABASE_URL is required"):
        Settings()


def test_production_settings_reject_admin_database_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_production_env(
        monkeypatch,
        DATABASE_URL="postgresql://postgres:secret@db.example.com:5432/postgres",
    )

    with pytest.raises(SettingsError, match="must not use a Postgres admin user"):
        Settings()


def test_production_settings_reject_public_api_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_production_env(monkeypatch, ENABLE_API_DOCS="true")

    with pytest.raises(SettingsError, match="ENABLE_API_DOCS must be false"):
        Settings()


def test_production_settings_accept_hardened_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_production_env(monkeypatch)

    settings = Settings()

    assert settings.is_production is True
    assert settings.use_database is True
    assert settings.api_docs_enabled is False
    assert settings.trusted_hosts == ["api.careagent.example"]


def test_apply_migrations_script_discovers_all_sql_migrations() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "apply_migrations.ps1").read_text()
    migrations = sorted(path.name for path in (repo_root / "migrations").glob("*.sql"))

    assert migrations[0].startswith("001_")
    assert migrations[-1].startswith("008_")
    assert 'Get-ChildItem -LiteralPath $MigrationsPath -Filter "*.sql"' in script
    assert "003_channels_calls_escalation.sql" not in script
