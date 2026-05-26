from __future__ import annotations

import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from backend.auth.bootstrap import BootstrapAdminConfig, bootstrap_admin_from_env
from backend.auth.repository import PostgresAuthRepository
from backend.auth.service import DEFAULT_TENANT_ID, PERMISSION_DESCRIPTIONS


class AuthBootstrapTest(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_admin_from_env_creates_admin_with_password_hash(self) -> None:
        connection = FakeConnection()
        database = FakeDatabase(connection)

        with patch.dict(
            os.environ,
            {
                "BOOTSTRAP_ADMIN_ENABLED": "true",
                "BOOTSTRAP_ADMIN_USERNAME": "Root Admin",
                "BOOTSTRAP_ADMIN_EMAIL": "Admin@Example.COM",
                "BOOTSTRAP_ADMIN_PASSWORD_HASH": "pbkdf2_sha256$210000$salt$digest",
            },
            clear=True,
        ):
            await bootstrap_admin_from_env(database)

        credential_params = _first_executed_params(connection, "INSERT INTO user_credentials")
        user_params = _first_executed_params(connection, "INSERT INTO users")

        self.assertEqual(user_params["email"], "admin@example.com")
        self.assertEqual(user_params["display_name"], "Root Admin")
        self.assertEqual(credential_params["password_hash"], "pbkdf2_sha256$210000$salt$digest")
        self.assertTrue(_executed_sql_contains(connection, "pg_advisory_xact_lock"))
        self.assertTrue(_executed_sql_contains(connection, "name = ANY(:role_names)"))

    async def test_existing_admin_does_not_update_password_hash_by_default(self) -> None:
        connection = FakeConnection(existing_admin=True, existing_credentials=True)

        await PostgresAuthRepository(connection).bootstrap_admin_user(
            BootstrapAdminConfig(
                username="Root Admin",
                email="admin@example.com",
                password_hash="pbkdf2_sha256$210000$new$new",
                update_password_hash=False,
            )
        )

        self.assertFalse(_executed_sql_contains(connection, "UPDATE user_credentials"))
        self.assertTrue(_executed_sql_contains(connection, "UPDATE users"))
        self.assertTrue(_executed_sql_contains(connection, "INSERT INTO user_roles"))

    async def test_existing_admin_without_credentials_gets_password_hash(self) -> None:
        connection = FakeConnection(existing_admin=True, existing_credentials=False)

        await PostgresAuthRepository(connection).bootstrap_admin_user(
            BootstrapAdminConfig(
                username="Root Admin",
                email="admin@example.com",
                password_hash="pbkdf2_sha256$210000$new$new",
            )
        )

        credential_params = _first_executed_params(connection, "INSERT INTO user_credentials")
        self.assertEqual(credential_params["user_id"], "user-admin")
        self.assertEqual(credential_params["password_hash"], "pbkdf2_sha256$210000$new$new")

    async def test_existing_admin_updates_password_hash_when_enabled(self) -> None:
        connection = FakeConnection(existing_admin=True, existing_credentials=True)

        await PostgresAuthRepository(connection).bootstrap_admin_user(
            BootstrapAdminConfig(
                username="Root Admin",
                email="admin@example.com",
                password_hash="pbkdf2_sha256$210000$new$new",
                update_password_hash=True,
            )
        )

        credential_params = _first_executed_params(connection, "UPDATE user_credentials")
        self.assertEqual(credential_params["password_hash"], "pbkdf2_sha256$210000$new$new")

    async def test_enabled_bootstrap_requires_all_admin_environment_variables(self) -> None:
        with (
            patch.dict(os.environ, {"BOOTSTRAP_ADMIN_ENABLED": "true"}, clear=True),
            self.assertRaisesRegex(RuntimeError, "BOOTSTRAP_ADMIN_USERNAME"),
        ):
            await bootstrap_admin_from_env(FakeDatabase(FakeConnection()))


class FakeDatabase:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def begin(self):
        return _transaction(self.connection)


class FakeConnection:
    def __init__(self, *, existing_admin: bool = False, existing_credentials: bool = False) -> None:
        self.existing_admin = existing_admin
        self.existing_credentials = existing_credentials
        self.created_user_id = "user-admin"
        self.executed: list[tuple[object, dict]] = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        params = params or {}
        if "INSERT INTO permissions" in statement_text:
            return FakeResult([{"id": f"permission-{params['name']}"}])
        if "INSERT INTO roles" in statement_text:
            return FakeResult([{"id": f"role-{params['name']}"}])
        if "INSERT INTO users" in statement_text:
            self.created_user_id = str(params["id"])
            return FakeResult([])
        if "FROM users" in statement_text and "WHERE id = :user_id" in statement_text:
            return FakeResult([_admin_row(user_id=params["user_id"])])
        if "FROM users" in statement_text and "WHERE tenant_id = :tenant_id" in statement_text:
            return FakeResult([_admin_row()] if self.existing_admin else [])
        if "FROM user_credentials" in statement_text and "WHERE user_id = :user_id" in statement_text:
            return FakeResult([{"id": "credential-admin"}] if self.existing_credentials else [])
        if "FROM roles" in statement_text and "name = ANY(:role_names)" in statement_text:
            return FakeResult([{"id": "role-admin", "name": "admin", "description": "Built-in admin role"}])
        if "FROM roles r" in statement_text:
            return FakeResult([{"id": "role-admin", "name": "admin", "description": "Built-in admin role"}])
        if "FROM permissions p" in statement_text:
            return FakeResult(
                [
                    {
                        "id": f"permission-{permission}",
                        "name": permission,
                        "description": description,
                    }
                    for permission, description in PERMISSION_DESCRIPTIONS.items()
                ]
            )
        return FakeResult([])

    async def scalar(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return None


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


@asynccontextmanager
async def _transaction(connection: FakeConnection):
    yield connection


def _first_executed_params(connection: FakeConnection, sql_fragment: str) -> dict:
    for statement, params in connection.executed:
        if sql_fragment in str(statement):
            return params
    raise AssertionError(f"SQL fragment not executed: {sql_fragment}")


def _executed_sql_contains(connection: FakeConnection, sql_fragment: str) -> bool:
    return any(sql_fragment in str(statement) for statement, _ in connection.executed)


def _admin_row(*, user_id: object = "user-admin") -> dict:
    return {
        "id": user_id,
        "tenant_id": DEFAULT_TENANT_ID,
        "email": "admin@example.com",
        "display_name": "Existing Admin",
        "is_active": True,
        "created_at": object(),
        "updated_at": object(),
    }


if __name__ == "__main__":
    unittest.main()
