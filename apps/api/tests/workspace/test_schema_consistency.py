from sqlalchemy import create_engine, text

import pytest

from app.core.schema_consistency import (
    SchemaConsistencyError,
    assert_schema_consistent,
)


HEAD = "20260728_0030"


def _database_with_version(*, include_required_tables: bool):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        )
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES (:version)"
            ),
            {"version": HEAD},
        )
        if include_required_tables:
            connection.execute(text("CREATE TABLE risk_scans (id VARCHAR)"))
            connection.execute(
                text("CREATE TABLE risk_scan_feedback (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE risk_feedback_events (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE extension_capture_tasks (id VARCHAR)")
            )
            connection.execute(text("CREATE TABLE export_jobs (id VARCHAR)"))
            connection.execute(text("CREATE TABLE restore_jobs (id VARCHAR)"))
            connection.execute(
                text("CREATE TABLE knowledge_index_rebuilds (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE retention_policies (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE managed_objects (id VARCHAR)")
            )
            connection.execute(
                text(
                    "CREATE TABLE workspace_deletion_confirmations "
                    "(id VARCHAR)"
                )
            )
            connection.execute(
                text("CREATE TABLE workspace_deletion_jobs (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE deletion_audits (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE product_event_outbox (id VARCHAR)")
            )
            connection.execute(
                text("CREATE TABLE task_operation_events (id VARCHAR)")
            )
    return engine


def test_head_version_without_required_tables_fails_schema_consistency() -> None:
    engine = _database_with_version(include_required_tables=False)

    with engine.connect() as connection:
        with pytest.raises(
            SchemaConsistencyError,
            match="head.*missing.*risk_feedback_events.*risk_scan_feedback",
        ):
            assert_schema_consistent(
                connection,
                expected_head=HEAD,
                required_tables={
                    "risk_scans",
                    "risk_scan_feedback",
                    "risk_feedback_events",
                    "extension_capture_tasks",
                    "export_jobs",
                    "restore_jobs",
                    "knowledge_index_rebuilds",
                    "retention_policies",
                    "managed_objects",
                    "workspace_deletion_confirmations",
                    "workspace_deletion_jobs",
                    "deletion_audits",
                    "product_event_outbox",
                    "task_operation_events",
                },
            )


def test_head_version_with_required_tables_passes_schema_consistency() -> None:
    engine = _database_with_version(include_required_tables=True)

    with engine.connect() as connection:
        assert_schema_consistent(
            connection,
            expected_head=HEAD,
            required_tables={
                "risk_scans",
                "risk_scan_feedback",
                "risk_feedback_events",
                "extension_capture_tasks",
                "export_jobs",
                "restore_jobs",
                    "knowledge_index_rebuilds",
                    "retention_policies",
                    "managed_objects",
                    "workspace_deletion_confirmations",
                    "workspace_deletion_jobs",
                    "deletion_audits",
                    "product_event_outbox",
                    "task_operation_events",
                },
        )
