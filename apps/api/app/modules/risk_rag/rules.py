from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
import re
import unicodedata
from uuid import UUID

from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskDocumentStatus,
    RiskSourceLevel,
)


class MatchType(StrEnum):
    TERM = "term"
    CONTACT = "contact"


class RuleDisposition(StrEnum):
    PROHIBIT = "prohibit"
    FLAG = "flag"
    ALLOW = "allow"


class RuleScope(StrEnum):
    TITLE = "title"
    BODY = "body"
    COVER_TEXT = "cover_text"


class RuleSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RulePolicyViolation(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceSnapshot:
    document_id: UUID
    platform: Platform
    source_level: RiskSourceLevel
    status: RiskDocumentStatus
    effective_at: datetime | None


@dataclass(frozen=True)
class DeterministicRule:
    rule_id: str
    match_type: MatchType
    patterns: tuple[str, ...]
    severity: RuleSeverity
    scopes: frozenset[RuleScope]
    disposition: RuleDisposition
    evidence_document_ids: tuple[UUID, ...]
    normalization_aliases: tuple[tuple[str, str], ...] = ()
    overrides_rule_id: str | None = None


@dataclass(frozen=True)
class RuleSet:
    platform: Platform
    version: str
    published_at: datetime
    rules: tuple[DeterministicRule, ...]
    workspace_id: UUID | None = None


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    severity: RuleSeverity
    disposition: RuleDisposition
    scope: RuleScope
    matched_pattern: str
    rule_set_version: str
    evidence_document_ids: tuple[UUID, ...]


def _normalize_term(
    value: str,
    aliases: tuple[tuple[str, str], ...],
) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )
    for source, target in aliases:
        normalized_source = _normalize_term(source, ())
        normalized_target = _normalize_term(target, ())
        normalized = normalized.replace(
            normalized_source,
            normalized_target,
        )
    return normalized


def _matches_contact(value: str, kind: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if kind == "phone":
        return (
            re.search(r"(?<!\d)1(?:[\s.-]*\d){10}(?!\d)", normalized)
            is not None
        )
    compact = re.sub(r"\s+", "", normalized)
    if kind == "email":
        return (
            re.search(
                r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
                compact,
            )
            is not None
        )
    if kind == "handle":
        return re.search(r"@[a-z0-9_.-]{2,}", compact) is not None
    raise RulePolicyViolation(f"unsupported contact pattern: {kind}")


class RuleEngine:
    def __init__(self, rule_set: RuleSet) -> None:
        self._rule_set = rule_set

    def scan(
        self,
        *,
        platform: Platform,
        title: str,
        body: str,
        cover_text: str,
    ) -> list[RuleMatch]:
        if platform is not self._rule_set.platform:
            return []
        values = {
            RuleScope.TITLE: title,
            RuleScope.BODY: body,
            RuleScope.COVER_TEXT: cover_text,
        }
        matches: list[RuleMatch] = []
        for rule in self._rule_set.rules:
            for scope in sorted(rule.scopes, key=lambda item: item.value):
                value = values[scope]
                matched_pattern = next(
                    (
                        pattern
                        for pattern in rule.patterns
                        if (
                            _normalize_term(
                                pattern,
                                rule.normalization_aliases,
                            )
                            in _normalize_term(
                                value,
                                rule.normalization_aliases,
                            )
                            if rule.match_type is MatchType.TERM
                            else _matches_contact(value, pattern)
                        )
                    ),
                    None,
                )
                if matched_pattern is None:
                    continue
                matches.append(
                    RuleMatch(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        disposition=rule.disposition,
                        scope=scope,
                        matched_pattern=matched_pattern,
                        rule_set_version=self._rule_set.version,
                        evidence_document_ids=rule.evidence_document_ids,
                    )
                )
        return matches


def load_rule_set(
    path: Path,
    *,
    allow_synthetic: bool = False,
) -> RuleSet:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("synthetic_only") is not True:
        raise RulePolicyViolation(
            "bundled rule sets must be explicitly synthetic"
        )
    if not allow_synthetic:
        raise RulePolicyViolation(
            "synthetic rule sets require explicit test-only opt-in"
        )
    try:
        published_at = datetime.fromisoformat(
            str(payload["published_at"]).replace("Z", "+00:00")
        )
        rules = tuple(
            DeterministicRule(
                rule_id=str(item["rule_id"]),
                match_type=MatchType(item["match_type"]),
                patterns=tuple(str(value) for value in item["patterns"]),
                severity=RuleSeverity(item["severity"]),
                scopes=frozenset(
                    RuleScope(value) for value in item["scopes"]
                ),
                disposition=RuleDisposition(item["disposition"]),
                evidence_document_ids=tuple(
                    UUID(value) for value in item["evidence_document_ids"]
                ),
                normalization_aliases=tuple(
                    (str(pair[0]), str(pair[1]))
                    for pair in item.get("normalization_aliases", [])
                ),
                overrides_rule_id=item.get("overrides_rule_id"),
            )
            for item in payload["rules"]
        )
        return RuleSet(
            platform=Platform(payload["platform"]),
            version=str(payload["version"]),
            published_at=published_at,
            rules=rules,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RulePolicyViolation("invalid synthetic rule set") from error


def publish_rule_set(
    rule_set: RuleSet,
    *,
    evidence: dict[UUID, EvidenceSnapshot],
) -> RuleSet:
    if not rule_set.version.strip():
        raise RulePolicyViolation("published rule set requires a version")
    if not rule_set.rules:
        raise RulePolicyViolation("published rule set requires rules")

    seen: set[str] = set()
    for rule in rule_set.rules:
        if not rule.rule_id or rule.rule_id in seen:
            raise RulePolicyViolation("published rules require unique IDs")
        seen.add(rule.rule_id)
        if not rule.patterns or not rule.scopes:
            raise RulePolicyViolation(
                "published rules require patterns, severity, and scope"
            )
        if (
            rule.match_type is MatchType.TERM
            and any(
                not _normalize_term(
                    pattern,
                    rule.normalization_aliases,
                )
                for pattern in rule.patterns
            )
        ) or (
            rule.match_type is MatchType.CONTACT
            and not set(rule.patterns) <= {"phone", "email", "handle"}
        ):
            raise RulePolicyViolation(
                "published rule contains an invalid matcher"
            )
        if not rule.evidence_document_ids:
            raise RulePolicyViolation(
                "published rules require evidence document IDs"
            )
        valid = [
            snapshot
            for evidence_id in rule.evidence_document_ids
            if (snapshot := evidence.get(evidence_id)) is not None
            and snapshot.platform is rule_set.platform
            and snapshot.status is RiskDocumentStatus.ACTIVE
            and snapshot.effective_at is not None
            and snapshot.effective_at <= rule_set.published_at
        ]
        if not valid:
            label = (
                "high-risk rule"
                if rule.severity is RuleSeverity.HIGH
                else "published rule"
            )
            raise RulePolicyViolation(
                f"{label} requires active same-platform evidence"
            )
        if (
            rule.severity is RuleSeverity.HIGH
            and all(
                snapshot.source_level is RiskSourceLevel.S5
                for snapshot in valid
            )
        ):
            raise RulePolicyViolation(
                "high-risk rule cannot rely only on S5 evidence"
            )
    return rule_set


def merge_team_rule_set(
    official: RuleSet,
    team: RuleSet,
) -> RuleSet:
    if official.workspace_id is not None or team.workspace_id is None:
        raise RulePolicyViolation(
            "team rules require public official and private team sets"
        )
    if official.platform is not team.platform:
        raise RulePolicyViolation("team and official platforms must match")

    disposition_rank = {
        RuleDisposition.ALLOW: 0,
        RuleDisposition.FLAG: 1,
        RuleDisposition.PROHIBIT: 2,
    }
    severity_rank = {
        RuleSeverity.LOW: 0,
        RuleSeverity.MEDIUM: 1,
        RuleSeverity.HIGH: 2,
    }
    effective = {
        rule.rule_id: rule
        for rule in official.rules
    }
    for rule in team.rules:
        if rule.overrides_rule_id is None:
            effective[rule.rule_id] = rule
            continue
        base = effective.get(rule.overrides_rule_id)
        if base is None:
            raise RulePolicyViolation(
                "team override references an unknown official rule"
            )
        base_patterns = {
            _normalize_term(pattern, base.normalization_aliases)
            for pattern in base.patterns
        }
        team_patterns = {
            _normalize_term(pattern, rule.normalization_aliases)
            for pattern in rule.patterns
        }
        relaxes = (
            rule.match_type is not base.match_type
            or disposition_rank[rule.disposition]
            < disposition_rank[base.disposition]
            or severity_rank[rule.severity] < severity_rank[base.severity]
            or not base.scopes <= rule.scopes
            or not base_patterns <= team_patterns
        )
        if relaxes:
            raise RulePolicyViolation(
                "team rule cannot relax an official prohibition or warning"
            )
        del effective[base.rule_id]
        effective[rule.rule_id] = rule

    return RuleSet(
        platform=official.platform,
        version=f"{official.version}+{team.version}",
        published_at=max(official.published_at, team.published_at),
        rules=tuple(effective.values()),
        workspace_id=team.workspace_id,
    )
