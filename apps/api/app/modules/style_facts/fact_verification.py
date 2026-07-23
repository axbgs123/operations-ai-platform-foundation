from dataclasses import dataclass, field
from datetime import datetime

from app.modules.style_facts.fact_policy import (
    FactEvidence,
    FactResolutionStatus,
    ForcedFactOverride,
    canonicalize_fact_field,
    canonicalize_fact_value,
    is_high_risk_fact_field_code,
    resolve_fact_field,
)


FACT_CONFLICT = "FACT_CONFLICT"


class FactConflictError(ValueError):
    code = FACT_CONFLICT

    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__(f"unresolved fact conflict: {', '.join(fields)}")


@dataclass(frozen=True)
class GeneratedClaim:
    field_name: str
    value: str
    field_code: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "field_code",
            canonicalize_fact_field(self.field_name).code,
        )


@dataclass(frozen=True)
class ClaimIssue:
    field_name: str
    kind: str
    expected_value: str | None
    actual_value: str
    high_risk: bool


@dataclass(frozen=True)
class ClaimVerification:
    issues: tuple[ClaimIssue, ...]
    can_enter_pending_publication: bool


def preflight_generation_facts(
    evidence: list[FactEvidence],
    *,
    now: datetime,
    overrides: dict[str, ForcedFactOverride] | None = None,
) -> dict[str, str]:
    grouped: dict[str, list[FactEvidence]] = {}
    for item in evidence:
        grouped.setdefault(item.field_code, []).append(item)
    resolved: dict[str, str] = {}
    conflicts: list[str] = []
    for field_code, items in grouped.items():
        resolution = resolve_fact_field(
            items,
            now=now,
            override=(overrides or {}).get(field_code),
        )
        if resolution.status is FactResolutionStatus.UNRESOLVED_CONFLICT:
            conflicts.append(field_code)
        elif resolution.selected is not None:
            resolved[field_code] = resolution.selected.value
    if conflicts:
        raise FactConflictError(tuple(sorted(conflicts)))
    return resolved


def verify_generated_claims(
    claims: list[GeneratedClaim],
    *,
    confirmed_facts: dict[str, str],
) -> ClaimVerification:
    issues: list[ClaimIssue] = []
    for claim in claims:
        expected = confirmed_facts.get(claim.field_code)
        high_risk = is_high_risk_fact_field_code(claim.field_code)
        if expected is None:
            issues.append(
                ClaimIssue(
                    field_name=claim.field_name,
                    kind="unsupported",
                    expected_value=None,
                    actual_value=claim.value,
                    high_risk=high_risk,
                )
            )
        elif canonicalize_fact_value(expected) != canonicalize_fact_value(claim.value):
            issues.append(
                ClaimIssue(
                    field_name=claim.field_name,
                    kind="conflict",
                    expected_value=expected,
                    actual_value=claim.value,
                    high_risk=high_risk,
                )
            )
    return ClaimVerification(
        issues=tuple(issues),
        can_enter_pending_publication=not any(issue.high_risk for issue in issues),
    )
