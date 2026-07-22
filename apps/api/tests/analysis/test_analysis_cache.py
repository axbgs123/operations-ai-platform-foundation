from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.modules.analysis.features import (
    BenchmarkEvidenceInput,
    ContentEvidenceInput,
    MetricEvidenceInput,
    SnapshotEvidenceInput,
    build_analysis_evidence,
)
from app.modules.analysis.models import (
    AnalysisRun,
    AnalysisRunStatus,
    ProductEvent,
)
from app.modules.analysis.schemas import MockAnalysisAdapter
from app.modules.analysis.service import (
    AnalysisVersionContext,
    begin_analysis_attempt,
    execute_bundle_analysis,
    process_analysis_run,
    lease_recoverable_analysis_runs,
    record_analysis_provider_failure,
)
from app.modules.analysis.tasks import (
    get_analysis_enqueuer,
    get_auto_analysis_enqueuer,
)
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)


class CountingAdapter(MockAnalysisAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, bundle):
        self.calls += 1
        return super().analyze(bundle)


class InvalidCitationAdapter(MockAnalysisAdapter):
    def analyze(self, bundle):
        report = super().analyze(bundle)
        report.recommendations[0].evidence_ids = ["outside:bundle"]
        return report


class TemporarilyUnavailableAdapter(MockAnalysisAdapter):
    def analyze(self, bundle):
        raise RuntimeError("synthetic provider timeout")


def evidence_bundle():
    return build_analysis_evidence(
        ContentEvidenceInput(
            id=uuid4(),
            title="合成测试标题",
            body="仅包含虚构数据的测试文案",
            cover_asset_ids=[],
        ),
        [
            SnapshotEvidenceInput(
                id=uuid4(),
                collected_at=datetime(2026, 7, 22, 1, tzinfo=UTC),
                maturity_bucket="24h",
                metrics=[MetricEvidenceInput(key="views", value="120")],
            )
        ],
        BenchmarkEvidenceInput(
            id=uuid4(),
            sample_count=12,
            confidence="normal",
            percentiles={"views": {"median": "80", "p90": "150"}},
        ),
    )


def version_context(bundle) -> AnalysisVersionContext:
    return AnalysisVersionContext(
        workspace_id=uuid4(),
        account_id=uuid4(),
        content_id=bundle.content.id,
        benchmark_run_id=bundle.benchmark.id,
        snapshot_ids=[snapshot.id for snapshot in bundle.snapshots],
        model_version="mock-analysis-v1",
        prompt_version="analysis-prompt-v1",
        algorithm_version="analysis-v1",
        benchmark_algorithm_version="benchmark-v1",
        trigger_kind="manual",
    )


def test_identical_evidence_and_versions_reuse_successful_report() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    bundle = evidence_bundle()
    context = version_context(bundle)
    adapter = CountingAdapter()

    with Session(engine, expire_on_commit=False) as session:
        first = execute_bundle_analysis(session, bundle, context, adapter)
        second = execute_bundle_analysis(session, bundle, context, adapter)

        assert first.id == second.id
        assert first.status == AnalysisRunStatus.SUCCEEDED
        assert adapter.calls == 1
        assert first.model_version == "mock-analysis-v1"
        assert first.prompt_version == "analysis-prompt-v1"
        assert first.algorithm_version == "analysis-v1"
        assert first.benchmark_algorithm_version == "benchmark-v1"
        assert first.benchmark_run_id == bundle.benchmark.id
        assert first.snapshot_ids == [str(bundle.snapshots[0].id)]


def test_active_cache_has_database_uniqueness_guard() -> None:
    index = next(
        item
        for item in AnalysisRun.__table__.indexes
        if item.name == "uq_analysis_runs_active_cache"
    )
    assert index.unique is True


def test_pending_run_is_a_durable_recovery_queue_entry() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    bundle = evidence_bundle()
    context = version_context(bundle)
    with Session(engine) as session:
        run = AnalysisRun(
            workspace_id=context.workspace_id,
            account_id=context.account_id,
            content_id=context.content_id,
            benchmark_run_id=context.benchmark_run_id,
            snapshot_ids=[str(item) for item in context.snapshot_ids],
            status=AnalysisRunStatus.PENDING,
            trigger_kind="manual",
            cache_key="a" * 64,
            evidence_bundle=bundle.model_dump(mode="json"),
            model_version=context.model_version,
            prompt_version=context.prompt_version,
            algorithm_version=context.algorithm_version,
            benchmark_algorithm_version=context.benchmark_algorithm_version,
        )
        session.add(run)
        session.flush()

        assert lease_recoverable_analysis_runs(session) == [run.id]


def test_provider_failures_stop_after_three_attempts() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    bundle = evidence_bundle()
    context = version_context(bundle)
    with Session(engine, expire_on_commit=False) as session:
        run = AnalysisRun(
            workspace_id=context.workspace_id,
            account_id=context.account_id,
            content_id=context.content_id,
            benchmark_run_id=context.benchmark_run_id,
            snapshot_ids=[str(item) for item in context.snapshot_ids],
            status=AnalysisRunStatus.PENDING,
            trigger_kind="manual",
            cache_key="b" * 64,
            evidence_bundle=bundle.model_dump(mode="json"),
            model_version=context.model_version,
            prompt_version=context.prompt_version,
            algorithm_version=context.algorithm_version,
            benchmark_algorithm_version=context.benchmark_algorithm_version,
        )
        session.add(run)
        session.commit()
        for _ in range(3):
            assert begin_analysis_attempt(session, run.id) is True
            session.commit()
            record_analysis_provider_failure(session, run.id)
            session.commit()

            if run.status == AnalysisRunStatus.PENDING:
                assert begin_analysis_attempt(session, run.id) is False
                run.next_attempt_at = datetime.now(UTC)
                session.commit()

        assert run.status == AnalysisRunStatus.FAILED
        assert run.attempt_count == 3
        assert run.error_code == "analysis_provider_unavailable"
        assert begin_analysis_attempt(session, run.id) is False


def test_version_change_misses_analysis_cache() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    bundle = evidence_bundle()
    context = version_context(bundle)
    adapter = CountingAdapter()

    with Session(engine, expire_on_commit=False) as session:
        first = execute_bundle_analysis(session, bundle, context, adapter)
        changed = context.model_copy(update={"prompt_version": "analysis-prompt-v2"})
        second = execute_bundle_analysis(session, bundle, changed, adapter)

        assert first.id != second.id
        assert adapter.calls == 2


def test_unknown_model_citation_marks_run_failed_without_report() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    bundle = evidence_bundle()
    context = version_context(bundle)

    with Session(engine, expire_on_commit=False) as session:
        run = execute_bundle_analysis(
            session,
            bundle,
            context,
            InvalidCitationAdapter(),
        )

        assert run.status == AnalysisRunStatus.FAILED
        assert run.report is None
        assert run.error_code == "invalid_model_output"
        assert session.scalar(select(AnalysisRun).where(AnalysisRun.id == run.id))


def test_temporary_adapter_failure_rolls_back_for_queue_retry() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    bundle = evidence_bundle()

    with Session(engine) as session:
        with pytest.raises(RuntimeError, match="provider timeout"):
            execute_bundle_analysis(
                session,
                bundle,
                version_context(bundle),
                TemporarilyUnavailableAdapter(),
            )
        session.rollback()
        assert session.scalar(select(AnalysisRun)) is None


def test_manual_trigger_persists_versions_and_enqueues_after_commit() -> None:
    enqueued = []
    with configured_client() as (client, _):
        from app.main import app

        app.dependency_overrides[get_analysis_enqueuer] = lambda: enqueued.append
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="合成分析内容",
            work_url="https://example.test/synthetic-analysis",
        )
        collected_at = (
            datetime.fromisoformat(content["published_at"])
            .replace(tzinfo=UTC)
            .isoformat()
        )
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": collected_at,
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 120}],
            },
        ).json()
        confirmed = client.post(
            f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed.status_code == 200, confirmed.text

        response = client.post(
            f"/v1/contents/{content['id']}/analysis-runs",
            headers={"X-CSRF-Token": csrf},
        )

        assert response.status_code == 202, response.text
        run = response.json()
        assert run["status"] == "pending"
        assert run["model_version"] == "mock-analysis-v1"
        assert run["prompt_version"] == "analysis-prompt-v1"
        assert run["algorithm_version"] == "analysis-v1"
        assert run["benchmark_algorithm_version"] == "benchmark-v1"
        assert run["benchmark_run_id"]
        assert run["snapshot_ids"] == [snapshot["id"]]
        assert enqueued == [UUID(run["id"])]
        read = client.get(
            f"/v1/contents/{content['id']}/analysis-runs/{run['id']}"
        )
        assert read.status_code == 200
        assert read.json() == run
        repeated = client.post(
            f"/v1/contents/{content['id']}/analysis-runs",
            headers={"X-CSRF-Token": csrf},
        )
        assert repeated.status_code == 202
        assert repeated.json()["id"] == run["id"]
        assert enqueued == [UUID(run["id"]), UUID(run["id"])]


def test_account_can_opt_in_to_automatic_analysis() -> None:
    auto_enqueued = []
    with configured_client() as (client, engine):
        from app.main import app

        app.dependency_overrides[get_auto_analysis_enqueuer] = (
            lambda: auto_enqueued.append
        )
        workspace_id, csrf, account = create_workspace_account(client)
        path = (
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/analysis-settings"
        )

        assert client.get(path).json() == {"auto_analyze": False}
        updated = client.put(
            path,
            headers={"X-CSRF-Token": csrf},
            json={"auto_analyze": True},
        )

        assert updated.status_code == 200, updated.text
        assert updated.json() == {"auto_analyze": True}
        assert client.get(path).json() == {"auto_analyze": True}

        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="自动分析合成内容",
            work_url="https://example.test/auto-analysis",
        )
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": content["published_at"],
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 88}],
            },
        ).json()
        confirmed = client.post(
            f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed.status_code == 200
        assert len(auto_enqueued) == 1
        assert auto_enqueued[0] != UUID(snapshot["id"])
        with Session(engine) as session:
            auto_run = session.get(AnalysisRun, auto_enqueued[0])
            assert auto_run is not None
            assert auto_run.trigger_kind == "auto"
            assert auto_run.status == AnalysisRunStatus.PENDING


def test_feedback_saved_suggestion_and_adoption_emit_product_events() -> None:
    enqueued = []
    with configured_client() as (client, engine):
        from app.main import app

        app.dependency_overrides[get_analysis_enqueuer] = lambda: enqueued.append
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="闭环合成内容",
            work_url="https://example.test/analysis-loop",
        )
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": content["published_at"],
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 188}],
            },
        ).json()
        client.post(
            f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )
        run = client.post(
            f"/v1/contents/{content['id']}/analysis-runs",
            headers={"X-CSRF-Token": csrf},
        ).json()
        with Session(engine) as session:
            process_analysis_run(
                session,
                UUID(run["id"]),
                MockAnalysisAdapter(),
            )
            session.commit()

        feedback = client.post(
            f"/v1/contents/{content['id']}/analysis-runs/{run['id']}/feedback",
            headers={"X-CSRF-Token": csrf},
            json={"rating": "useful"},
        )
        assert feedback.status_code == 201, feedback.text
        saved = client.post(
            f"/v1/contents/{content['id']}/analysis-runs/{run['id']}"
            "/suggestions/recommendation-1",
            headers={"X-CSRF-Token": csrf},
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["adoption_status"] == "saved"
        adopted = client.patch(
            f"/v1/contents/{content['id']}/analysis-suggestions/"
            f"{saved.json()['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"adoption_status": "adopted"},
        )
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["adoption_status"] == "adopted"

        with Session(engine) as session:
            names = list(
                session.scalars(
                    select(ProductEvent.event_name).order_by(ProductEvent.occurred_at)
                )
            )
        assert names == [
            "analysis.feedback.useful",
            "analysis.suggestion.saved",
            "analysis.suggestion.adopted",
        ]


def test_e2e_snapshot_benchmark_analysis_suggestion_and_viral_confirmation() -> None:
    enqueued = []
    with configured_client() as (client, engine):
        from app.main import app

        app.dependency_overrides[get_analysis_enqueuer] = lambda: enqueued.append
        workspace_id, csrf, account = create_workspace_account(client)
        threshold = client.put(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/viral-thresholds",
            headers={"X-CSRF-Token": csrf},
            json={
                "rules": [
                    {
                        "category": "traffic",
                        "metric_key": "views",
                        "minimum_value": 950,
                    }
                ]
            },
        )
        assert threshold.status_code == 200, threshold.text

        top_content = None
        for index in range(10):
            content = create_published_content(
                client,
                workspace_id=workspace_id,
                csrf=csrf,
                account=account,
                title=f"合成闭环样本 {index + 1}",
                work_url=f"https://example.test/loop-{index + 1}",
            )
            snapshot = client.post(
                f"/v1/contents/{content['id']}/snapshots",
                headers={"X-CSRF-Token": csrf},
                json={
                    "collected_at": content["published_at"],
                    "source": "manual",
                    "metrics": [{"key": "views", "raw_value": (index + 1) * 100}],
                },
            ).json()
            confirmed = client.post(
                f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
                headers={"X-CSRF-Token": csrf},
            )
            assert confirmed.status_code == 200
            top_content = content

        assert top_content is not None
        candidates_response = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}"
            "/viral-candidates/evaluate",
            headers={"X-CSRF-Token": csrf},
            json={"content_type": "video", "maturity_bucket": "1h"},
        )
        assert candidates_response.status_code == 200, candidates_response.text
        candidate = next(
            item
            for item in candidates_response.json()
            if item["content_id"] == top_content["id"]
        )

        run = client.post(
            f"/v1/contents/{top_content['id']}/analysis-runs",
            headers={"X-CSRF-Token": csrf},
        ).json()
        with Session(engine) as session:
            completed = process_analysis_run(
                session,
                UUID(run["id"]),
                MockAnalysisAdapter(),
            )
            assert completed.status == AnalysisRunStatus.SUCCEEDED
            session.commit()
        saved = client.post(
            f"/v1/contents/{top_content['id']}/analysis-runs/{run['id']}"
            "/suggestions/recommendation-1",
            headers={"X-CSRF-Token": csrf},
        )
        assert saved.status_code == 201, saved.text
        confirmed_candidate = client.post(
            f"/v1/workspaces/{workspace_id}/viral-candidates/{candidate['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={
                "strategy_tags": ["合成强钩子"],
                "applicable_scenarios": ["自动化测试"],
                "structure_summary": "合成开场—合成证据—合成行动",
            },
        )
        assert confirmed_candidate.status_code == 201, confirmed_candidate.text
        assert confirmed_candidate.json()["generation_eligible"] is True
