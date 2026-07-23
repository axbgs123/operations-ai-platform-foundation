from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskFeedbackEvent,
    RiskFeedbackEventType,
    RiskFeedbackStatus,
    RiskFeedbackType,
    RiskScan,
    RiskScanFeedback,
)
from app.modules.workspace.permissions import (
    Permission,
    require_permission,
)


_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|password|cookie|invite[_-]?code)\s*[:=]|sk-[a-z0-9-]+"
)


class RiskFeedbackIdempotencyConflict(RuntimeError):
    pass


class UnsafeFeedbackContent(ValueError):
    pass


@dataclass(frozen=True)
class RiskRuleUpdateCandidate:
    feedback_id: UUID
    workspace_id: UUID
    platform: Platform
    finding_reference: str
    feedback_type: RiskFeedbackType
    rule_version: str
    evidence_version: str
    scope: str = "workspace_private"
    requires_manual_rule_change: bool = True
    can_modify_public_rules: bool = False


def _safe_summary(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 500:
        raise UnsafeFeedbackContent("feedback summary exceeds 500 characters")
    if _PHONE_PATTERN.search(normalized) or _SECRET_PATTERN.search(normalized):
        raise UnsafeFeedbackContent("feedback summary contains sensitive data")
    return normalized or None


def _fingerprint(
    *,
    scan_id: UUID,
    finding_reference: str,
    feedback_type: RiskFeedbackType,
    comment: str | None,
) -> str:
    payload = json.dumps(
        {
            "scan_id": str(scan_id),
            "finding_reference": finding_reference,
            "feedback_type": feedback_type.value,
            "comment": comment,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class RiskFeedbackService:
    def __init__(
        self,
        session: Session,
        *,
        context: WorkspaceContext,
    ) -> None:
        self._session = session
        self._context = context

    def submit(
        self,
        *,
        scan_id: UUID,
        finding_reference: str,
        feedback_type: RiskFeedbackType,
        idempotency_key: str,
        comment: str | None,
    ) -> RiskScanFeedback:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        member_id = self._require_member()
        finding_reference = finding_reference.strip()
        if not finding_reference or len(finding_reference) > 160:
            raise ValueError("finding reference is required")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("valid idempotency key is required")
        safe_comment = _safe_summary(comment)
        input_fingerprint = _fingerprint(
            scan_id=scan_id,
            finding_reference=finding_reference,
            feedback_type=feedback_type,
            comment=safe_comment,
        )
        existing = self._session.scalar(
            select(RiskScanFeedback).where(
                RiskScanFeedback.workspace_id == self._context.workspace_id,
                RiskScanFeedback.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.input_fingerprint != input_fingerprint:
                raise RiskFeedbackIdempotencyConflict(
                    "idempotency key was reused with different feedback"
                )
            return existing
        scan = self._session.scalar(
            select(RiskScan).where(
                RiskScan.id == scan_id,
                RiskScan.workspace_id == self._context.workspace_id,
            )
        )
        if scan is None:
            raise LookupError("risk scan not found")
        feedback = RiskScanFeedback(
            workspace_id=self._context.workspace_id,
            scan_id=scan.id,
            platform=scan.platform,
            feedback_type=feedback_type,
            status=RiskFeedbackStatus.PENDING_REVIEW,
            idempotency_key=idempotency_key,
            input_fingerprint=input_fingerprint,
            finding_reference=finding_reference,
            rule_version=scan.rule_version,
            evidence_version=scan.evidence_version,
            submitted_by=member_id,
            comment=safe_comment,
            comment_untrusted_data=True,
            reviewed_by=None,
            reviewed_at=None,
            review_note=None,
        )
        self._session.add(feedback)
        self._session.flush()
        self._append_event(
            feedback,
            RiskFeedbackEventType.SUBMITTED,
            actor_id=member_id,
            safe_note=None,
        )
        return feedback

    def review(
        self,
        feedback_id: UUID,
        *,
        status: RiskFeedbackStatus,
        note: str,
        reviewed_at: datetime,
    ) -> RiskScanFeedback:
        require_permission(
            self._context.role,
            Permission.MANAGE_RISK_KNOWLEDGE,
        )
        member_id = self._require_member()
        if status not in {
            RiskFeedbackStatus.APPROVED,
            RiskFeedbackStatus.REJECTED,
        }:
            raise ValueError("review must approve or reject feedback")
        feedback = self._get(feedback_id)
        if feedback.status is not RiskFeedbackStatus.PENDING_REVIEW:
            raise ValueError("feedback has already been reviewed")
        safe_note = _safe_summary(note)
        feedback.status = status
        feedback.reviewed_by = member_id
        feedback.reviewed_at = reviewed_at
        feedback.review_note = safe_note
        self._append_event(
            feedback,
            RiskFeedbackEventType(status.value),
            actor_id=member_id,
            safe_note=safe_note,
        )
        self._session.flush()
        return feedback

    def withdraw(
        self,
        feedback_id: UUID,
        *,
        reason: str,
        withdrawn_at: datetime,
    ) -> RiskScanFeedback:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        member_id = self._require_member()
        feedback = self._get(feedback_id)
        if feedback.submitted_by != member_id and self._context.role != "admin":
            raise PermissionError("only submitter or admin can withdraw feedback")
        if feedback.status is not RiskFeedbackStatus.PENDING_REVIEW:
            raise ValueError("only pending feedback can be withdrawn")
        safe_reason = _safe_summary(reason)
        feedback.status = RiskFeedbackStatus.WITHDRAWN
        feedback.reviewed_at = withdrawn_at
        self._append_event(
            feedback,
            RiskFeedbackEventType.WITHDRAWN,
            actor_id=member_id,
            safe_note=safe_reason,
        )
        self._session.flush()
        return feedback

    def rule_update_candidates(
        self,
        *,
        platform: Platform,
    ) -> tuple[RiskRuleUpdateCandidate, ...]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        feedback_items = self._session.scalars(
            select(RiskScanFeedback)
            .where(
                RiskScanFeedback.workspace_id == self._context.workspace_id,
                RiskScanFeedback.platform == platform,
                RiskScanFeedback.status == RiskFeedbackStatus.APPROVED,
            )
            .order_by(
                RiskScanFeedback.created_at,
                RiskScanFeedback.id,
            )
        )
        return tuple(
            RiskRuleUpdateCandidate(
                feedback_id=feedback.id,
                workspace_id=feedback.workspace_id,
                platform=feedback.platform,
                finding_reference=feedback.finding_reference,
                feedback_type=feedback.feedback_type,
                rule_version=feedback.rule_version,
                evidence_version=feedback.evidence_version,
            )
            for feedback in feedback_items
        )

    def _get(self, feedback_id: UUID) -> RiskScanFeedback:
        feedback = self._session.scalar(
            select(RiskScanFeedback).where(
                RiskScanFeedback.id == feedback_id,
                RiskScanFeedback.workspace_id == self._context.workspace_id,
            )
        )
        if feedback is None:
            raise LookupError("risk feedback not found")
        return feedback

    def _append_event(
        self,
        feedback: RiskScanFeedback,
        event_type: RiskFeedbackEventType,
        *,
        actor_id: UUID,
        safe_note: str | None,
    ) -> None:
        self._session.add(
            RiskFeedbackEvent(
                workspace_id=self._context.workspace_id,
                feedback_id=feedback.id,
                event_type=event_type,
                actor_id=actor_id,
                safe_note=safe_note,
            )
        )

    def _require_member(self) -> UUID:
        if self._context.member_id is None:
            raise PermissionError("authenticated workspace member required")
        return self._context.member_id
