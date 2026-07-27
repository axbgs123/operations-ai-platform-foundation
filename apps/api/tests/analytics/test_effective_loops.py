from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.modules.analytics.north_star import (
    AnalyticsEventFact,
    CompletenessInput,
    LoopEvidence,
    calculate_completeness,
    calculate_first_analysis_duration,
    calculate_normalized_edit_magnitude,
    calculate_weekly_retention,
    derive_effective_weekly_loops,
)
from tests.imports.helpers import configured_client, create_workspace_account


def _fact(
    name: str,
    when: datetime,
    *,
    workspace_id=None,
    platform: str = "douyin",
    eligible: bool = True,
) -> AnalyticsEventFact:
    return AnalyticsEventFact(
        event_id=uuid4(),
        event_name=name,
        workspace_id=workspace_id or WORKSPACE_ID,
        platform=platform,
        occurred_at=when,
        analytics_eligible=eligible,
    )


WORKSPACE_ID = uuid4()
OTHER_WORKSPACE_ID = uuid4()
MONDAY = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


def test_normalized_edit_magnitude_is_deterministic_and_bounded() -> None:
    identical = calculate_normalized_edit_magnitude(
        original_title="Ａ 标题",
        original_body="第一行\r\n第二行",
        final_title="A   标题",
        final_body="第一行\n第二行",
    )
    changed = calculate_normalized_edit_magnitude(
        original_title="标题",
        original_body="正文",
        final_title="标题改",
        final_body="正文",
    )
    empty = calculate_normalized_edit_magnitude(
        original_title="",
        original_body="",
        final_title="新",
        final_body="内容",
    )
    assert identical.algorithm_version == "normalized-levenshtein-v1"
    assert identical.total == 0
    assert identical.title == 0
    assert identical.body == 0
    assert 0 < changed.total <= changed.title <= 1
    assert changed.body == 0
    assert empty.total == 1


def test_first_analysis_requires_first_real_successful_view_and_splits_duration() -> None:
    entered_at = MONDAY
    result = calculate_first_analysis_duration(
        workspace_entered_at=entered_at,
        events=[
            _fact("analysis.started", entered_at + timedelta(minutes=1)),
            _fact(
                "analysis.processing_started",
                entered_at + timedelta(minutes=2),
            ),
            _fact(
                "analysis.completed",
                entered_at + timedelta(minutes=3),
                eligible=False,
            ),
            _fact(
                "analysis.viewed",
                entered_at + timedelta(minutes=4),
                eligible=False,
            ),
            _fact("analysis.completed", entered_at + timedelta(minutes=6)),
            _fact("analysis.viewed", entered_at + timedelta(minutes=8)),
            _fact("analysis.viewed", entered_at + timedelta(minutes=9)),
        ],
    )
    assert result.status == "AVAILABLE"
    assert result.total_seconds == 8 * 60
    assert result.queue_seconds == 60
    assert result.processing_seconds == 4 * 60
    assert result.queue_and_processing_seconds == 5 * 60
    assert result.user_wait_seconds == 2 * 60
    assert result.metric_version == "first-analysis-duration-v1"
    missing = calculate_first_analysis_duration(
        workspace_entered_at=entered_at,
        events=[_fact("analysis.completed", entered_at + timedelta(minutes=1))],
    )
    assert missing.status == "INSUFFICIENT_SAMPLE"
    assert missing.total_seconds is None
    assert missing.queue_seconds is None
    assert missing.processing_seconds is None


def test_completeness_excludes_not_applicable_items_from_denominator() -> None:
    result = calculate_completeness(
        CompletenessInput(
            platform="xiaohongshu",
            has_objective=True,
            has_metric_weights=True,
            has_benchmark=False,
            has_column_campaign=False,
            has_confirmed_style=True,
            has_confirmed_facts=False,
            has_title=True,
            has_body=True,
            has_cover=True,
            has_confirmed_snapshot=True,
            has_active_risk_knowledge=True,
            has_active_model=False,
        )
    )
    campaign = next(item for item in result.items if item.key == "column_campaign")
    assert campaign.applicable is False
    assert campaign.weight not in {
        item.weight for item in result.items if item.applicable is False
    } or campaign.weight == 0
    assert result.completeness_version == "profile-completeness-v1"
    assert result.denominator == sum(
        item.weight for item in result.items if item.applicable
    )
    assert {"benchmark", "confirmed_facts", "active_model"} <= set(
        result.missing_items
    )


def test_effective_loop_requires_all_server_facts_and_never_crosses_scope() -> None:
    evidence = LoopEvidence(
        workspace_id=WORKSPACE_ID,
        platform="douyin",
        published_content_id=uuid4(),
        published_at=MONDAY + timedelta(hours=1),
        confirmed_snapshot_id=uuid4(),
        snapshot_confirmed_at=MONDAY + timedelta(hours=2),
        snapshot_analytics_eligible=True,
        events=[
            _fact("analysis.viewed", MONDAY + timedelta(hours=3)),
            _fact("suggestion.saved", MONDAY + timedelta(hours=4)),
            _fact("suggestion.saved", MONDAY + timedelta(hours=5)),
        ],
    )
    loops = derive_effective_weekly_loops(
        [evidence, evidence],
        timezone_name="Asia/Shanghai",
    )
    assert len(loops) == 1
    assert loops[0].metric_version == "effective-weekly-loop-v1"
    assert loops[0].iso_week == "2026-W31"
    assert loops[0].workspace_id == WORKSPACE_ID
    assert loops[0].evidence_ids["content_id"] == str(
        evidence.published_content_id
    )

    variants = [
        evidence.model_copy(update={"published_content_id": None}),
        evidence.model_copy(update={"confirmed_snapshot_id": None}),
        evidence.model_copy(update={"snapshot_analytics_eligible": False}),
        evidence.model_copy(
            update={
                "events": [
                    _fact("suggestion.saved", MONDAY + timedelta(hours=4))
                ]
            }
        ),
        evidence.model_copy(
            update={
                "events": [
                    _fact("analysis.viewed", MONDAY + timedelta(hours=3))
                ]
            }
        ),
        evidence.model_copy(
            update={
                "events": [
                    _fact(
                        "analysis.viewed",
                        MONDAY + timedelta(hours=3),
                        workspace_id=OTHER_WORKSPACE_ID,
                    ),
                    _fact("suggestion.saved", MONDAY + timedelta(hours=4)),
                ]
            }
        ),
        evidence.model_copy(
            update={
                "events": [
                    _fact(
                        "analysis.viewed",
                        MONDAY + timedelta(hours=3),
                        platform="xiaohongshu",
                    ),
                    _fact("suggestion.saved", MONDAY + timedelta(hours=4)),
                ]
            }
        ),
    ]
    assert derive_effective_weekly_loops(variants) == []


def test_week_boundary_and_retention_use_one_workspace_per_iso_week() -> None:
    boundary = LoopEvidence(
        workspace_id=WORKSPACE_ID,
        platform="douyin",
        published_content_id=uuid4(),
        published_at=datetime(2026, 7, 26, 15, 50, tzinfo=UTC),
        confirmed_snapshot_id=uuid4(),
        snapshot_confirmed_at=datetime(2026, 7, 26, 15, 55, tzinfo=UTC),
        snapshot_analytics_eligible=True,
        events=[
            _fact(
                "analysis.viewed",
                datetime(2026, 7, 26, 15, 57, tzinfo=UTC),
            ),
            _fact(
                "draft.created",
                datetime(2026, 7, 26, 16, 1, tzinfo=UTC),
            ),
        ],
    )
    loop = derive_effective_weekly_loops([boundary])[0]
    assert loop.iso_week == "2026-W31"

    insufficient = calculate_weekly_retention(
        baseline_week="2026-W30",
        return_week="2026-W31",
        loops=[loop],
    )
    assert insufficient.status == "INSUFFICIENT_SAMPLE"
    assert insufficient.rate is None
    previous = loop.model_copy(update={"iso_week": "2026-W30"})
    retained = calculate_weekly_retention(
        baseline_week="2026-W30",
        return_week="2026-W31",
        loops=[previous, loop, loop],
    )
    assert retained.denominator == 1
    assert retained.returned_workspaces == 1
    assert retained.rate == 1
    assert retained.metric_version == "weekly-loop-retention-v1"


def test_analytics_api_role_matrix_and_workspace_404() -> None:
    with configured_client() as (admin, _):
        workspace_id, csrf, account = create_workspace_account(admin)
        metrics = admin.get(
            f"/v1/workspaces/{workspace_id}/analytics/product-metrics"
        )
        assert metrics.status_code == 200, metrics.text
        assert (
            metrics.json()["first_analysis"]["status"]
            == "INSUFFICIENT_SAMPLE"
        )
        assert (
            admin.get(
                f"/v1/workspaces/{uuid4()}/analytics/product-metrics"
            ).status_code
            == 404
        )

        for role in ("editor", "viewer"):
            issued = admin.post(
                f"/v1/workspaces/{workspace_id}/members/codes",
                headers={"X-CSRF-Token": csrf},
                json={"role": role},
            )
            assert issued.status_code == 201, issued.text
            with TestClient(app) as member:
                login = member.post(
                    "/v1/sessions/invite",
                    json={
                        "code": issued.json()["code"],
                        "display_name": f"合成{role}",
                    },
                )
                assert login.status_code == 201, login.text
                completeness = member.get(
                    f"/v1/workspaces/{workspace_id}/analytics/completeness",
                    params={"account_id": account["id"]},
                )
                assert completeness.status_code == 200, completeness.text
                assert (
                    member.get(
                        f"/v1/workspaces/{workspace_id}/analytics/product-metrics"
                    ).status_code
                    == 403
                )
