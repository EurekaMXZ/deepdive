from __future__ import annotations

import os

from backend.auth.bootstrap_config import BootstrapAdminConfig
from backend.auth.repository import PostgresAuthRepository
from backend.auth.service import normalize_email
from backend.db.connections import AsyncConnectionProvider


async def bootstrap_admin_from_env(database: AsyncConnectionProvider) -> None:
    if not _bool_env(os.environ.get("BOOTSTRAP_ADMIN_ENABLED", "false")):
        return
    config = _bootstrap_admin_config_from_env()
    await PostgresAuthRepository(database).bootstrap_admin_user(config)


def _bootstrap_admin_config_from_env() -> BootstrapAdminConfig:
    username = _required_env("BOOTSTRAP_ADMIN_USERNAME")
    email = normalize_email(_required_env("BOOTSTRAP_ADMIN_EMAIL"))
    password_hash = _required_env("BOOTSTRAP_ADMIN_PASSWORD_HASH")
    return BootstrapAdminConfig(
        username=username,
        email=email,
        password_hash=password_hash,
        update_password_hash=_bool_env(os.environ.get("BOOTSTRAP_ADMIN_UPDATE_PASSWORD_HASH", "false")),
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required when BOOTSTRAP_ADMIN_ENABLED=true")
    return value.strip()


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
