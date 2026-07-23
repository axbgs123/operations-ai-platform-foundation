from uuid import uuid4

import pytest

from app.modules.risk_rag.lifecycle import (
    SourcePolicyViolation,
    can_independently_support_high_risk,
    validate_source_policy,
)
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskDocumentScope,
    RiskSourceLevel,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("S1", RiskSourceLevel.S1),
        ("S2", RiskSourceLevel.S2),
        ("S3", RiskSourceLevel.S3),
        ("S4", RiskSourceLevel.S4),
        ("S5", RiskSourceLevel.S5),
    ],
)
def test_source_levels_are_explicit(value: str, expected: RiskSourceLevel) -> None:
    assert RiskSourceLevel(value) is expected


@pytest.mark.parametrize("level", [RiskSourceLevel.S1, RiskSourceLevel.S2])
def test_public_library_accepts_s1_and_s2_by_default(
    level: RiskSourceLevel,
) -> None:
    validate_source_policy(
        scope=RiskDocumentScope.PUBLIC,
        level=level,
        authorization_status=RiskAuthorizationStatus.NOT_REQUIRED,
        workspace_id=None,
    )


@pytest.mark.parametrize(
    "level",
    [RiskSourceLevel.S3, RiskSourceLevel.S4, RiskSourceLevel.S5],
)
def test_public_library_requires_explicit_authorization_for_other_levels(
    level: RiskSourceLevel,
) -> None:
    with pytest.raises(SourcePolicyViolation, match="explicit authorization"):
        validate_source_policy(
            scope=RiskDocumentScope.PUBLIC,
            level=level,
            authorization_status=RiskAuthorizationStatus.UNVERIFIED,
            workspace_id=None,
        )

    validate_source_policy(
        scope=RiskDocumentScope.PUBLIC,
        level=level,
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        workspace_id=None,
    )


def test_private_documents_require_workspace_and_public_documents_forbid_it() -> None:
    with pytest.raises(SourcePolicyViolation, match="workspace_id"):
        validate_source_policy(
            scope=RiskDocumentScope.PRIVATE,
            level=RiskSourceLevel.S3,
            authorization_status=RiskAuthorizationStatus.AUTHORIZED,
            workspace_id=None,
        )

    with pytest.raises(SourcePolicyViolation, match="workspace_id"):
        validate_source_policy(
            scope=RiskDocumentScope.PUBLIC,
            level=RiskSourceLevel.S1,
            authorization_status=RiskAuthorizationStatus.NOT_REQUIRED,
            workspace_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("level", "allowed"),
    [
        (RiskSourceLevel.S1, True),
        (RiskSourceLevel.S2, True),
        (RiskSourceLevel.S3, True),
        (RiskSourceLevel.S4, True),
        (RiskSourceLevel.S5, False),
    ],
)
def test_s5_cannot_independently_support_high_risk(
    level: RiskSourceLevel,
    allowed: bool,
) -> None:
    assert can_independently_support_high_risk(level) is allowed
