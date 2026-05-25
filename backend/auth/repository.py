from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from backend.api.pagination import cursor_offset
from backend.auth.models import PermissionRecord, RoleRecord, UserRecord
from backend.auth.passwords import hash_password
from backend.auth.service import DEFAULT_TENANT_ID, PERMISSION_DESCRIPTIONS, ROLE_PERMISSIONS
from backend.db.connections import ConnectionSource, connection_from
from backend.ids import new_uuid7

DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


class PostgresAuthRepository:
    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def ensure_seed_data(self) -> None:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO tenants (id, slug, display_name, created_at, updated_at)
                    VALUES (:id, :slug, :display_name, :created_at, :updated_at)
                    ON CONFLICT (slug) DO NOTHING
                    """
                ),
                {
                    "id": DEFAULT_TENANT_ID,
                    "slug": DEFAULT_TENANT_SLUG,
                    "display_name": DEFAULT_TENANT_NAME,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            permission_ids: dict[str, UUID] = {}
            for permission_name, description in PERMISSION_DESCRIPTIONS.items():
                permission_id = new_uuid7()
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO permissions (id, name, description, created_at)
                        VALUES (:id, :name, :description, :created_at)
                        ON CONFLICT (name) DO UPDATE
                        SET description = EXCLUDED.description
                        RETURNING id
                        """
                    ),
                    {
                        "id": permission_id,
                        "name": permission_name,
                        "description": description,
                        "created_at": now,
                    },
                )
                row = result.mappings().first()
                if row is None:
                    raise RuntimeError("permission upsert did not return an id")
                permission_ids[permission_name] = cast(UUID, row["id"])

            for role_name, permission_names in ROLE_PERMISSIONS.items():
                role_id = new_uuid7()
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO roles (id, tenant_id, name, description, created_at)
                        VALUES (:id, :tenant_id, :name, :description, :created_at)
                        ON CONFLICT (tenant_id, name) DO UPDATE
                        SET description = EXCLUDED.description
                        RETURNING id
                        """
                    ),
                    {
                        "id": role_id,
                        "tenant_id": DEFAULT_TENANT_ID,
                        "name": role_name,
                        "description": f"Built-in {role_name} role",
                        "created_at": now,
                    },
                )
                row = result.mappings().first()
                if row is None:
                    raise RuntimeError("role upsert did not return an id")
                stored_role_id = cast(UUID, row["id"])
                for permission_name in permission_names:
                    await connection.execute(
                        text(
                            """
                            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
                            VALUES (:id, :role_id, :permission_id, :created_at)
                            ON CONFLICT (role_id, permission_id) DO NOTHING
                            """
                        ),
                        {
                            "id": new_uuid7(),
                            "role_id": stored_role_id,
                            "permission_id": permission_ids[permission_name],
                            "created_at": now,
                        },
                    )

    async def has_users(self) -> bool:
        async with self._connection() as connection:
            value = await connection.scalar(text("SELECT EXISTS (SELECT 1 FROM users)"))
        return bool(value)

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None,
        role_names: Sequence[str],
    ) -> UserRecord:
        now = datetime.now(UTC)
        user_id = new_uuid7()
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (id, tenant_id, email, display_name, is_active, created_at, updated_at)
                    VALUES (:id, :tenant_id, :email, :display_name, :is_active, :created_at, :updated_at)
                    """
                ),
                {
                    "id": user_id,
                    "tenant_id": DEFAULT_TENANT_ID,
                    "email": email,
                    "display_name": display_name,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO user_credentials (id, user_id, password_hash, created_at, updated_at)
                    VALUES (:id, :user_id, :password_hash, :created_at, :updated_at)
                    """
                ),
                {
                    "id": new_uuid7(),
                    "user_id": user_id,
                    "password_hash": hash_password(password),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            roles = await _roles_by_names(connection, role_names)
            for role in roles:
                await connection.execute(
                    text(
                        """
                        INSERT INTO user_roles (id, user_id, role_id, created_at)
                        VALUES (:id, :user_id, :role_id, :created_at)
                        ON CONFLICT (user_id, role_id) DO NOTHING
                        """
                    ),
                    {"id": new_uuid7(), "user_id": user_id, "role_id": role.id, "created_at": now},
                )
        user = await self.get_user(user_id)
        if user is None:
            raise RuntimeError("created user could not be loaded")
        return user

    async def create_user_without_password(
        self,
        *,
        email: str,
        display_name: str | None,
        role_names: Sequence[str],
    ) -> UserRecord:
        now = datetime.now(UTC)
        user_id = new_uuid7()
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (id, tenant_id, email, display_name, is_active, created_at, updated_at)
                    VALUES (:id, :tenant_id, :email, :display_name, :is_active, :created_at, :updated_at)
                    """
                ),
                {
                    "id": user_id,
                    "tenant_id": DEFAULT_TENANT_ID,
                    "email": email,
                    "display_name": display_name,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            roles = await _roles_by_names(connection, role_names)
            for role in roles:
                await connection.execute(
                    text(
                        """
                        INSERT INTO user_roles (id, user_id, role_id, created_at)
                        VALUES (:id, :user_id, :role_id, :created_at)
                        ON CONFLICT (user_id, role_id) DO NOTHING
                        """
                    ),
                    {"id": new_uuid7(), "user_id": user_id, "role_id": role.id, "created_at": now},
                )
        user = await self.get_user(user_id)
        if user is None:
            raise RuntimeError("created user could not be loaded")
        return user

    async def get_user_by_email_with_password(self, email: str) -> tuple[UserRecord, str] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT u.id, u.tenant_id, u.email, u.display_name, u.is_active,
                           u.created_at, u.updated_at, c.password_hash
                    FROM users u
                    JOIN user_credentials c ON c.user_id = u.id
                    WHERE u.tenant_id = :tenant_id
                      AND u.email = :email
                    """
                ),
                {"tenant_id": DEFAULT_TENANT_ID, "email": email},
            )
            row = result.mappings().first()
        if row is None:
            return None
        user = await self.get_user(cast(UUID, row["id"]))
        if user is None:
            return None
        return user, str(row["password_hash"])

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE tenant_id = :tenant_id
                      AND email = :email
                    """
                ),
                {"tenant_id": DEFAULT_TENANT_ID, "email": email},
            )
            row = result.mappings().first()
        return None if row is None else await self.get_user(cast(UUID, row["id"]))

    async def get_user_by_external_identity(self, provider: str, provider_account_id: str) -> UserRecord | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT user_id
                    FROM oauth_accounts
                    WHERE provider = :provider
                      AND provider_account_id = :provider_account_id
                    """
                ),
                {"provider": provider, "provider_account_id": provider_account_id},
            )
            row = result.mappings().first()
        return None if row is None else await self.get_user(cast(UUID, row["user_id"]))

    async def link_external_identity(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        provider_login: str | None,
        provider_email: str,
        provider_email_verified: bool,
    ) -> None:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO oauth_accounts (
                        id, tenant_id, user_id, provider, provider_account_id, provider_login,
                        provider_email, provider_email_verified, created_at, updated_at
                    )
                    VALUES (
                        :id, :tenant_id, :user_id, :provider, :provider_account_id, :provider_login,
                        :provider_email, :provider_email_verified, :created_at, :updated_at
                    )
                    ON CONFLICT (provider, provider_account_id) DO UPDATE
                    SET provider_login = EXCLUDED.provider_login,
                        provider_email = EXCLUDED.provider_email,
                        provider_email_verified = EXCLUDED.provider_email_verified,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "id": new_uuid7(),
                    "tenant_id": DEFAULT_TENANT_ID,
                    "user_id": user_id,
                    "provider": provider,
                    "provider_account_id": provider_account_id,
                    "provider_login": provider_login,
                    "provider_email": provider_email,
                    "provider_email_verified": provider_email_verified,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    async def list_users(self, *, limit: int = 50, cursor: str | None = None) -> list[UserRecord]:
        offset = cursor_offset(cursor)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    WITH page AS (
                        SELECT id, tenant_id, email, display_name, is_active, created_at, updated_at
                        FROM users
                        WHERE tenant_id = :tenant_id
                        ORDER BY created_at, id
                        LIMIT :limit OFFSET :offset
                    )
                    SELECT
                        page.id AS user_id,
                        page.tenant_id AS tenant_id,
                        page.email AS email,
                        page.display_name AS display_name,
                        page.is_active AS is_active,
                        page.created_at AS created_at,
                        page.updated_at AS updated_at,
                        r.id AS role_id,
                        r.name AS role_name,
                        r.description AS role_description,
                        p.id AS permission_id,
                        p.name AS permission_name,
                        p.description AS permission_description
                    FROM page
                    LEFT JOIN user_roles ur ON ur.user_id = page.id
                    LEFT JOIN roles r ON r.id = ur.role_id
                    LEFT JOIN role_permissions rp ON rp.role_id = r.id
                    LEFT JOIN permissions p ON p.id = rp.permission_id
                    ORDER BY page.created_at, page.id, r.name, p.name
                    """
                ),
                {"tenant_id": DEFAULT_TENANT_ID, "limit": limit, "offset": offset},
            )
            rows = result.mappings().all()
        return _users_from_join_rows(rows)

    async def list_user_ids(self, *, limit: int = 50, cursor: str | None = None) -> list[UUID]:
        offset = cursor_offset(cursor)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at, id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"tenant_id": DEFAULT_TENANT_ID, "limit": limit, "offset": offset},
            )
        return [cast(UUID, row["id"]) for row in result.mappings().all()]

    async def get_user(self, user_id: UUID) -> UserRecord | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, tenant_id, email, display_name, is_active, created_at, updated_at
                    FROM users
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            roles = await _roles_for_user(connection, user_id)
        return _user_from_row(row, roles)

    async def update_user(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_active: bool | None = None,
    ) -> UserRecord | None:
        existing = await self.get_user(user_id)
        if existing is None:
            return None
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE users
                    SET display_name = :display_name,
                        is_active = :is_active,
                        updated_at = :updated_at
                    WHERE id = :user_id
                    """
                ),
                {
                    "user_id": user_id,
                    "display_name": existing.display_name if display_name is None else display_name,
                    "is_active": existing.is_active if is_active is None else is_active,
                    "updated_at": datetime.now(UTC),
                },
            )
        return await self.get_user(user_id)

    async def reset_password(self, user_id: UUID, *, password: str) -> bool:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE user_credentials
                    SET password_hash = :password_hash,
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                    RETURNING user_id
                    """
                ),
                {"user_id": user_id, "password_hash": hash_password(password), "updated_at": datetime.now(UTC)},
            )
        return result.mappings().first() is not None

    async def list_roles(self) -> list[RoleRecord]:
        async with self._connection() as connection:
            return await _all_roles(connection)

    async def list_permissions(self) -> list[PermissionRecord]:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, name, description
                    FROM permissions
                    ORDER BY name
                    """
                )
            )
        return [_permission_from_row(row) for row in result.mappings().all()]

    async def assign_roles(self, user_id: UUID, role_ids: list[UUID]) -> UserRecord | None:
        if await self.get_user(user_id) is None:
            return None
        now = datetime.now(UTC)
        async with self._connection() as connection:
            roles_by_id = {role.id: role for role in await _all_roles(connection)}
            if any(role_id not in roles_by_id for role_id in role_ids):
                raise RoleNotFoundError
            await connection.execute(text("DELETE FROM user_roles WHERE user_id = :user_id"), {"user_id": user_id})
            for role_id in dict.fromkeys(role_ids):
                await connection.execute(
                    text(
                        """
                        INSERT INTO user_roles (id, user_id, role_id, created_at)
                        VALUES (:id, :user_id, :role_id, :created_at)
                        """
                    ),
                    {"id": new_uuid7(), "user_id": user_id, "role_id": role_id, "created_at": now},
                )
            await connection.execute(
                text("UPDATE users SET updated_at = :updated_at WHERE id = :user_id"),
                {"user_id": user_id, "updated_at": now},
            )
        return await self.get_user(user_id)

    async def role_names_exist(self, role_names: Sequence[str]) -> bool:
        async with self._connection() as connection:
            roles = await _roles_by_names(connection, role_names)
        return len(roles) == len(tuple(dict.fromkeys(role_names)))


class RoleNotFoundError(ValueError):
    pass


async def _roles_by_names(connection: Any, role_names: Sequence[str]) -> list[RoleRecord]:
    unique_names = tuple(dict.fromkeys(role_names))
    if not unique_names:
        return []
    result = await connection.execute(
        text(
            """
            SELECT id, name, description
            FROM roles
            WHERE tenant_id = :tenant_id
              AND name = ANY(:role_names)
            ORDER BY name
            """
        ),
        {"tenant_id": DEFAULT_TENANT_ID, "role_names": list(unique_names)},
    )
    roles: list[RoleRecord] = []
    for row in result.mappings().all():
        permissions = await _permissions_for_role(connection, cast(UUID, row["id"]))
        roles.append(_role_from_row(row, permissions))
    return roles


async def _all_roles(connection: Any) -> list[RoleRecord]:
    result = await connection.execute(
        text(
            """
            SELECT id, name, description
            FROM roles
            WHERE tenant_id = :tenant_id
            ORDER BY name
            """
        ),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    roles: list[RoleRecord] = []
    for row in result.mappings().all():
        permissions = await _permissions_for_role(connection, cast(UUID, row["id"]))
        roles.append(_role_from_row(row, permissions))
    return roles


async def _roles_for_user(connection: Any, user_id: UUID) -> list[RoleRecord]:
    result = await connection.execute(
        text(
            """
            SELECT r.id, r.name, r.description
            FROM roles r
            JOIN user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = :user_id
            ORDER BY r.name
            """
        ),
        {"user_id": user_id},
    )
    roles: list[RoleRecord] = []
    for row in result.mappings().all():
        permissions = await _permissions_for_role(connection, cast(UUID, row["id"]))
        roles.append(_role_from_row(row, permissions))
    return roles


async def _permissions_for_role(connection: Any, role_id: UUID) -> list[PermissionRecord]:
    result = await connection.execute(
        text(
            """
            SELECT p.id, p.name, p.description
            FROM permissions p
            JOIN role_permissions rp ON rp.permission_id = p.id
            WHERE rp.role_id = :role_id
            ORDER BY p.name
            """
        ),
        {"role_id": role_id},
    )
    return [_permission_from_row(row) for row in result.mappings().all()]


def _user_from_row(row: Mapping[str, Any], roles: list[RoleRecord]) -> UserRecord:
    return UserRecord(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        email=str(row["email"]),
        display_name=cast(str | None, row["display_name"]),
        is_active=bool(row["is_active"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        roles=roles,
    )


def _users_from_join_rows(rows: Sequence[Mapping[str, Any]]) -> list[UserRecord]:
    users: dict[UUID, dict[str, Any]] = {}
    roles_by_user: dict[UUID, dict[UUID, RoleRecord]] = {}
    permissions_by_role: dict[tuple[UUID, UUID], set[UUID]] = {}

    for row in rows:
        user_id = cast(UUID, row["user_id"])
        users.setdefault(
            user_id,
            {
                "id": user_id,
                "tenant_id": row["tenant_id"],
                "email": row["email"],
                "display_name": row["display_name"],
                "is_active": row["is_active"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
        role_id = cast(UUID | None, row["role_id"])
        if role_id is None:
            continue
        role_permissions = roles_by_user.setdefault(user_id, {})
        role = role_permissions.get(role_id)
        if role is None:
            role = RoleRecord(
                id=role_id,
                name=str(row["role_name"]),
                description=str(row["role_description"]),
                permissions=[],
            )
            role_permissions[role_id] = role
        permission_id = cast(UUID | None, row["permission_id"])
        if permission_id is None:
            continue
        permission_key = (user_id, role_id)
        seen_permission_ids = permissions_by_role.setdefault(permission_key, set())
        if permission_id in seen_permission_ids:
            continue
        seen_permission_ids.add(permission_id)
        role.permissions.append(
            PermissionRecord(
                id=permission_id,
                name=str(row["permission_name"]),
                description=str(row["permission_description"]),
            )
        )

    return [
        _user_from_row(user_row, list(roles_by_user.get(user_id, {}).values())) for user_id, user_row in users.items()
    ]


def _role_from_row(row: Mapping[str, Any], permissions: list[PermissionRecord]) -> RoleRecord:
    return RoleRecord(
        id=cast(UUID, row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        permissions=permissions,
    )


def _permission_from_row(row: Mapping[str, Any]) -> PermissionRecord:
    return PermissionRecord(
        id=cast(UUID, row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
    )
