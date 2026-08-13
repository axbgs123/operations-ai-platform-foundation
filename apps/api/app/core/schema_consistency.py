from collections.abc import Collection
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine, inspect, text

from app.core.config import get_settings


class SchemaConsistencyError(RuntimeError):
    pass


RUNTIME_REQUIRED_TABLES = {
    "workspaces",
    "contents",
    "risk_documents",
    "risk_chunks",
    "risk_chunk_embeddings",
    "risk_scans",
    "risk_scan_feedback",
    "risk_feedback_events",
    "extension_tokens",
    "extension_pairing_codes",
    "extension_device_bindings",
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
    "cover_generation_runs",
    "cover_artifact_attempts",
    "model_usage_policies",
    "model_usage_reservations",
    "model_usage_attempts",
    "model_contract_validation_runs",
    "agent_briefings",
    "agent_plans",
    "agent_runs",
    "agent_run_steps",
    "agent_confirmations",
    "agent_artifacts",
    "agent_events",
    "agent_chat_sessions",
    "agent_chat_messages",
    "hotspot_capture_tasks",
    "hotspot_snapshots",
    "hotspot_entries",
}


def assert_schema_consistent(
    connection: Connection,
    *,
    expected_head: str,
    required_tables: Collection[str],
) -> None:
    try:
        versions = set(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars()
        )
    except Exception as error:
        raise SchemaConsistencyError(
            "database is missing alembic_version"
        ) from error
    if versions != {expected_head}:
        rendered = ", ".join(sorted(versions)) or "none"
        raise SchemaConsistencyError(
            f"database revision is {rendered}; expected head {expected_head}"
        )
    present = set(inspect(connection).get_table_names())
    missing = sorted(set(required_tables) - present)
    if missing:
        raise SchemaConsistencyError(
            f"schema at head {expected_head} is missing required tables: "
            f"{', '.join(missing)}"
        )


def verify_configured_database() -> None:
    api_root = Path(__file__).parents[2]
    config = Config(str(api_root / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise SchemaConsistencyError("migration graph has no head")
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as connection:
            assert_schema_consistent(
                connection,
                expected_head=head,
                required_tables=RUNTIME_REQUIRED_TABLES,
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    verify_configured_database()
