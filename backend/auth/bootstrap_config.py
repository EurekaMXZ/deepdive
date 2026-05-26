from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapAdminConfig:
    username: str
    email: str
    password_hash: str
    update_password_hash: bool = False
