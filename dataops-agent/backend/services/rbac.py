"""Locked role set (Phase 15).

Roles are plain lowercase strings stored on `User.role` (String(50), no DB
enum) — matches this codebase's existing convention for role/severity-style
fields (see `QualityRule.severity`). The only value ever written before this
phase was "owner" (every account is created as its tenant's owner via
`create_new_tenant_and_user()`), so introducing the other four here is a new
capability, not a migration of existing data — every existing row is already
a valid value under this set.
"""
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DATA_ENGINEER = "data_engineer"
    DATA_ANALYST = "data_analyst"
    VIEWER = "viewer"


ALL_ROLES = tuple(r.value for r in Role)
