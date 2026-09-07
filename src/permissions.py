"""Shared authorization capabilities.

Roles remain the persisted RBAC contract; these helpers describe the
capabilities consumed by application rules so that those rules do not need to
repeat role-specific lists throughout the codebase.
"""

from src.models import AdministrativeCapability, User, UserRole

PERSONAL_READER_ROLES = frozenset({UserRole.STUDENT, UserRole.TEACHER})


def has_personal_reader_capability(role: UserRole | str | None) -> bool:
    """Whether a role can access personal circulation data and actions."""

    if role is None:
        return False
    value = role.value if isinstance(role, UserRole) else role
    return value in {item.value for item in PERSONAL_READER_ROLES}


def has_administrative_capability(
    user: User, capability: AdministrativeCapability, school_id: int
) -> bool:
    """Check a delegated librarian capability within its tenant."""

    if user.role != UserRole.LIBRARIAN or user.school_id != school_id:
        return False
    return capability.value in user.administrative_capabilities
