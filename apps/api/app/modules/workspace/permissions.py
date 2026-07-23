from enum import StrEnum

from app.core.security import WorkspaceRole


class Permission(StrEnum):
    READ_CONTENT = "read_content"
    WRITE_CONTENT = "write_content"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_MODELS = "manage_models"
    MANAGE_STYLES = "manage_styles"
    MANAGE_FACTS = "manage_facts"
    MANAGE_RISK_KNOWLEDGE = "manage_risk_knowledge"


class PermissionDenied(Exception):
    pass


ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "editor": frozenset(
        {
            Permission.READ_CONTENT,
            Permission.WRITE_CONTENT,
            Permission.MANAGE_FACTS,
        }
    ),
    "viewer": frozenset({Permission.READ_CONTENT}),
    "demo": frozenset({Permission.READ_CONTENT}),
}


def require_permission(role: WorkspaceRole, permission: Permission) -> None:
    if permission not in ROLE_PERMISSIONS[role]:
        raise PermissionDenied(f"role {role} lacks {permission.value}")
