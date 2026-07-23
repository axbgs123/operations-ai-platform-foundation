from uuid import UUID

from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)


class SourcePolicyViolation(ValueError):
    pass


class InvalidLifecycleTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[
    RiskDocumentStatus, frozenset[RiskDocumentStatus]
] = {
    RiskDocumentStatus.DRAFT: frozenset({RiskDocumentStatus.PARSED}),
    RiskDocumentStatus.PARSED: frozenset(
        {RiskDocumentStatus.PENDING_REVIEW}
    ),
    RiskDocumentStatus.PENDING_REVIEW: frozenset(
        {RiskDocumentStatus.ACTIVE, RiskDocumentStatus.REJECTED}
    ),
    RiskDocumentStatus.ACTIVE: frozenset(
        {RiskDocumentStatus.SUPERSEDED, RiskDocumentStatus.EXPIRED}
    ),
    RiskDocumentStatus.SUPERSEDED: frozenset(),
    RiskDocumentStatus.EXPIRED: frozenset(),
    RiskDocumentStatus.REJECTED: frozenset({RiskDocumentStatus.DRAFT}),
}


def transition_status(
    current: RiskDocumentStatus,
    target: RiskDocumentStatus,
    *,
    reviewer_id: UUID | None,
) -> RiskDocumentStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransition(
            f"transition from {current.value} to {target.value} is not allowed"
        )
    if target is RiskDocumentStatus.ACTIVE and reviewer_id is None:
        raise InvalidLifecycleTransition("activation requires a reviewer")
    return target


def validate_source_policy(
    *,
    scope: RiskDocumentScope,
    level: RiskSourceLevel,
    authorization_status: RiskAuthorizationStatus,
    workspace_id: UUID | None,
) -> None:
    if scope is RiskDocumentScope.PRIVATE and workspace_id is None:
        raise SourcePolicyViolation("private documents require workspace_id")
    if scope is RiskDocumentScope.PUBLIC and workspace_id is not None:
        raise SourcePolicyViolation("public documents must not have workspace_id")
    if authorization_status is RiskAuthorizationStatus.RESTRICTED:
        raise SourcePolicyViolation("restricted material cannot enter a knowledge library")
    if (
        scope is RiskDocumentScope.PUBLIC
        and level not in {RiskSourceLevel.S1, RiskSourceLevel.S2}
        and authorization_status is not RiskAuthorizationStatus.AUTHORIZED
    ):
        raise SourcePolicyViolation(
            "public S3-S5 material requires explicit authorization"
        )


def can_independently_support_high_risk(level: RiskSourceLevel) -> bool:
    return level is not RiskSourceLevel.S5
