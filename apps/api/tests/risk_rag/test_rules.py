from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.modules.content.account_models import Platform
from app.modules.risk_rag.models import (
    RiskDocumentStatus,
    RiskSourceLevel,
)
from app.modules.risk_rag.rules import (
    DeterministicRule,
    EvidenceSnapshot,
    MatchType,
    RuleDisposition,
    RulePolicyViolation,
    RuleEngine,
    RuleScope,
    RuleSet,
    RuleSeverity,
    publish_rule_set,
    merge_team_rule_set,
    load_rule_set,
)


NOW = datetime(2026, 7, 23, 8, tzinfo=UTC)
ROOT = Path(__file__).parents[4]


def _evidence(
    evidence_id: UUID,
    *,
    platform: Platform = Platform.DOUYIN,
    level: RiskSourceLevel = RiskSourceLevel.S1,
    status: RiskDocumentStatus = RiskDocumentStatus.ACTIVE,
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        document_id=evidence_id,
        platform=platform,
        source_level=level,
        status=status,
        effective_at=NOW,
    )


def _rule(
    *,
    rule_id: str = "synthetic-rule",
    severity: RuleSeverity = RuleSeverity.HIGH,
    evidence_document_ids: tuple[UUID, ...],
) -> DeterministicRule:
    return DeterministicRule(
        rule_id=rule_id,
        match_type=MatchType.TERM,
        patterns=("SYNTHETIC_RISK_WORD",),
        severity=severity,
        scopes=frozenset({RuleScope.TITLE, RuleScope.BODY}),
        disposition=RuleDisposition.PROHIBIT,
        evidence_document_ids=evidence_document_ids,
    )


def _rule_set(
    rule: DeterministicRule,
    *,
    platform: Platform = Platform.DOUYIN,
    version: str = "2026.07.synthetic.1",
) -> RuleSet:
    return RuleSet(
        platform=platform,
        version=version,
        published_at=NOW,
        rules=(rule,),
    )


def test_published_rules_require_version_severity_scope_and_evidence() -> None:
    evidence_id = uuid4()
    published = publish_rule_set(
        _rule_set(_rule(evidence_document_ids=(evidence_id,))),
        evidence={evidence_id: _evidence(evidence_id)},
    )

    assert published.version == "2026.07.synthetic.1"
    assert published.rules[0].severity is RuleSeverity.HIGH
    assert published.rules[0].scopes == frozenset(
        {RuleScope.TITLE, RuleScope.BODY}
    )
    assert published.rules[0].evidence_document_ids == (evidence_id,)


@pytest.mark.parametrize(
    "rule_set",
    [
        RuleSet(
            platform=Platform.DOUYIN,
            version="",
            published_at=NOW,
            rules=(
                _rule(evidence_document_ids=(uuid4(),)),
            ),
        ),
        _rule_set(_rule(evidence_document_ids=())),
    ],
)
def test_rule_publication_rejects_missing_governance_fields(
    rule_set: RuleSet,
) -> None:
    with pytest.raises(RulePolicyViolation):
        publish_rule_set(rule_set, evidence={})


@pytest.mark.parametrize(
    ("match_type", "patterns"),
    [
        (MatchType.TERM, ("---",)),
        (MatchType.CONTACT, ("unsupported-contact-kind",)),
    ],
)
def test_rule_publication_rejects_ambiguous_matchers(
    match_type: MatchType,
    patterns: tuple[str, ...],
) -> None:
    evidence_id = uuid4()
    rule = DeterministicRule(
        rule_id="synthetic-invalid-matcher",
        match_type=match_type,
        patterns=patterns,
        severity=RuleSeverity.LOW,
        scopes=frozenset({RuleScope.BODY}),
        disposition=RuleDisposition.FLAG,
        evidence_document_ids=(evidence_id,),
    )

    with pytest.raises(RulePolicyViolation, match="matcher"):
        publish_rule_set(
            _rule_set(rule),
            evidence={evidence_id: _evidence(evidence_id)},
        )


@pytest.mark.parametrize(
    "snapshot",
    [
        lambda evidence_id: _evidence(
            evidence_id,
            status=RiskDocumentStatus.PENDING_REVIEW,
        ),
        lambda evidence_id: _evidence(
            evidence_id,
            platform=Platform.XIAOHONGSHU,
        ),
        lambda evidence_id: _evidence(
            evidence_id,
            level=RiskSourceLevel.S5,
        ),
    ],
)
def test_high_risk_rule_requires_active_same_platform_non_s5_evidence(
    snapshot,
) -> None:
    evidence_id = uuid4()
    with pytest.raises(RulePolicyViolation, match="high-risk"):
        publish_rule_set(
            _rule_set(_rule(evidence_document_ids=(evidence_id,))),
            evidence={evidence_id: snapshot(evidence_id)},
        )


def _published_engine(
    rule: DeterministicRule,
    *,
    platform: Platform = Platform.DOUYIN,
) -> RuleEngine:
    evidence_id = rule.evidence_document_ids[0]
    return RuleEngine(
        publish_rule_set(
            _rule_set(rule, platform=platform),
            evidence={
                evidence_id: _evidence(
                    evidence_id,
                    platform=platform,
                )
            },
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        "SYNTHETICRISK",
        "syntheticrisk",
        "ＳｙｎｔｈｅｔｉｃＲｉｓｋ",
        "S Y N T H E T I C - R I S K",
        "synthetic.risk",
    ],
)
def test_term_matching_normalizes_case_width_spaces_and_punctuation(
    text: str,
) -> None:
    evidence_id = uuid4()
    engine = _published_engine(
        DeterministicRule(
            rule_id="synthetic-normalization",
            match_type=MatchType.TERM,
            patterns=("SyntheticRisk",),
            severity=RuleSeverity.MEDIUM,
            scopes=frozenset({RuleScope.TITLE}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(evidence_id,),
        )
    )

    matches = engine.scan(
        platform=Platform.DOUYIN,
        title=f"人工测试 {text}",
        body="",
        cover_text="",
    )

    assert len(matches) == 1
    assert matches[0].rule_id == "synthetic-normalization"
    assert matches[0].scope is RuleScope.TITLE
    assert matches[0].rule_set_version == "2026.07.synthetic.1"
    assert matches[0].evidence_document_ids == (evidence_id,)


def test_controlled_homophone_aliases_are_normalized() -> None:
    evidence_id = uuid4()
    engine = _published_engine(
        DeterministicRule(
            rule_id="synthetic-homophone",
            match_type=MatchType.TERM,
            patterns=("风控词",),
            normalization_aliases=(("枫控词", "风控词"),),
            severity=RuleSeverity.MEDIUM,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(evidence_id,),
        )
    )

    matches = engine.scan(
        platform=Platform.DOUYIN,
        title="",
        body="这里包含人工谐音：枫 控 词。",
        cover_text="",
    )

    assert [match.rule_id for match in matches] == ["synthetic-homophone"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("联系 138 0000 0000", "phone"),
        ("邮件 demo @ example . invalid", "email"),
    ],
)
def test_contact_variants_are_detected(text: str, kind: str) -> None:
    evidence_id = uuid4()
    engine = _published_engine(
        DeterministicRule(
            rule_id=f"synthetic-contact-{kind}",
            match_type=MatchType.CONTACT,
            patterns=(kind,),
            severity=RuleSeverity.MEDIUM,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(evidence_id,),
        )
    )

    matches = engine.scan(
        platform=Platform.DOUYIN,
        title="",
        body=text,
        cover_text="",
    )

    assert len(matches) == 1
    assert matches[0].matched_pattern == kind


def test_rules_do_not_cross_platform_or_unlisted_scopes() -> None:
    evidence_id = uuid4()
    engine = _published_engine(
        DeterministicRule(
            rule_id="douyin-synthetic-only",
            match_type=MatchType.TERM,
            patterns=("PLATFORM_ONLY_SYNTHETIC",),
            severity=RuleSeverity.MEDIUM,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(evidence_id,),
        ),
        platform=Platform.DOUYIN,
    )

    assert engine.scan(
        platform=Platform.XIAOHONGSHU,
        title="",
        body="PLATFORM_ONLY_SYNTHETIC",
        cover_text="",
    ) == []
    assert engine.scan(
        platform=Platform.DOUYIN,
        title="PLATFORM_ONLY_SYNTHETIC",
        body="",
        cover_text="",
    ) == []


def _published_set(
    rule: DeterministicRule,
    *,
    platform: Platform = Platform.DOUYIN,
    workspace_id: UUID | None = None,
    version: str,
) -> RuleSet:
    evidence_id = rule.evidence_document_ids[0]
    return publish_rule_set(
        RuleSet(
            platform=platform,
            version=version,
            published_at=NOW,
            rules=(rule,),
            workspace_id=workspace_id,
        ),
        evidence={
            evidence_id: _evidence(
                evidence_id,
                platform=platform,
                level=(
                    RiskSourceLevel.S3
                    if workspace_id is not None
                    else RiskSourceLevel.S1
                ),
            )
        },
    )


def test_team_rule_cannot_allow_an_official_prohibition() -> None:
    official_evidence = uuid4()
    official = _published_set(
        DeterministicRule(
            rule_id="official-synthetic-prohibition",
            match_type=MatchType.TERM,
            patterns=("OFFICIAL_SYNTHETIC",),
            severity=RuleSeverity.HIGH,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.PROHIBIT,
            evidence_document_ids=(official_evidence,),
        ),
        version="official.synthetic.1",
    )
    team = _published_set(
        DeterministicRule(
            rule_id="team-illegal-relaxation",
            match_type=MatchType.TERM,
            patterns=("OFFICIAL_SYNTHETIC",),
            severity=RuleSeverity.LOW,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.ALLOW,
            evidence_document_ids=(uuid4(),),
            overrides_rule_id="official-synthetic-prohibition",
        ),
        workspace_id=uuid4(),
        version="team.synthetic.1",
    )

    with pytest.raises(RulePolicyViolation, match="cannot relax"):
        merge_team_rule_set(official, team)


def test_team_rule_cannot_reduce_official_severity() -> None:
    official = _published_set(
        DeterministicRule(
            rule_id="official-synthetic-warning",
            match_type=MatchType.TERM,
            patterns=("SYNTHETIC_WARNING",),
            severity=RuleSeverity.HIGH,
            scopes=frozenset({RuleScope.TITLE}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(uuid4(),),
        ),
        version="official.synthetic.2",
    )
    team = _published_set(
        DeterministicRule(
            rule_id="team-lower-severity",
            match_type=MatchType.TERM,
            patterns=("SYNTHETIC_WARNING",),
            severity=RuleSeverity.MEDIUM,
            scopes=frozenset({RuleScope.TITLE}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(uuid4(),),
            overrides_rule_id="official-synthetic-warning",
        ),
        workspace_id=uuid4(),
        version="team.synthetic.2",
    )

    with pytest.raises(RulePolicyViolation, match="cannot relax"):
        merge_team_rule_set(official, team)


def test_team_rule_can_replace_with_a_stricter_rule_and_add_rules() -> None:
    official = _published_set(
        DeterministicRule(
            rule_id="official-synthetic-flag",
            match_type=MatchType.TERM,
            patterns=("SYNTHETIC_FLAG",),
            severity=RuleSeverity.MEDIUM,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.FLAG,
            evidence_document_ids=(uuid4(),),
        ),
        version="official.synthetic.3",
    )
    workspace_id = uuid4()
    stricter = _published_set(
        DeterministicRule(
            rule_id="team-stricter-prohibition",
            match_type=MatchType.TERM,
            patterns=("SYNTHETIC_FLAG",),
            severity=RuleSeverity.HIGH,
            scopes=frozenset({RuleScope.BODY}),
            disposition=RuleDisposition.PROHIBIT,
            evidence_document_ids=(uuid4(),),
            overrides_rule_id="official-synthetic-flag",
        ),
        workspace_id=workspace_id,
        version="team.synthetic.3",
    )

    effective = merge_team_rule_set(official, stricter)

    assert effective.workspace_id == workspace_id
    assert effective.version == "official.synthetic.3+team.synthetic.3"
    assert [rule.rule_id for rule in effective.rules] == [
        "team-stricter-prohibition"
    ]


@pytest.mark.parametrize(
    ("file_name", "platform", "marker"),
    [
        (
            "douyin.yml",
            Platform.DOUYIN,
            "SYNTHETIC_DOUYIN_TEST_MARKER",
        ),
        (
            "xiaohongshu.yml",
            Platform.XIAOHONGSHU,
            "SYNTHETIC_XIAOHONGSHU_TEST_MARKER",
        ),
    ],
)
def test_bundled_rule_sets_are_explicitly_synthetic_and_platform_scoped(
    file_name: str,
    platform: Platform,
    marker: str,
) -> None:
    path = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "modules"
        / "risk_rag"
        / "rule_sets"
        / file_name
    )

    with pytest.raises(RulePolicyViolation, match="synthetic"):
        load_rule_set(path)
    loaded = load_rule_set(path, allow_synthetic=True)

    assert loaded.platform is platform
    assert loaded.version == "synthetic-placeholder-v1"
    assert loaded.rules[0].patterns == (marker,)
    assert loaded.rules[0].severity is RuleSeverity.LOW
    other_platform = (
        Platform.XIAOHONGSHU
        if platform is Platform.DOUYIN
        else Platform.DOUYIN
    )
    assert RuleEngine(loaded).scan(
        platform=other_platform,
        title=marker,
        body="",
        cover_text="",
    ) == []
