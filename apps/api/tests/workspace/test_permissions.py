import pytest

from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        ("admin", Permission.MANAGE_MEMBERS, True),
        ("admin", Permission.WRITE_CONTENT, True),
        ("editor", Permission.MANAGE_MEMBERS, False),
        ("editor", Permission.WRITE_CONTENT, True),
        ("viewer", Permission.READ_CONTENT, True),
        ("viewer", Permission.WRITE_CONTENT, False),
        ("demo", Permission.READ_CONTENT, True),
        ("demo", Permission.WRITE_CONTENT, False),
    ],
)
def test_role_permission_matrix(role: str, permission: Permission, allowed: bool) -> None:
    if allowed:
        require_permission(role, permission)  # type: ignore[arg-type]
    else:
        with pytest.raises(PermissionDenied):
            require_permission(role, permission)  # type: ignore[arg-type]
