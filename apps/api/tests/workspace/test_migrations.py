import os
from pathlib import Path
from datetime import UTC, datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).parents[4]
DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://operations_ai:local-development-only@localhost:55432/operations_ai",
)


def test_migrations_upgrade_an_empty_postgres_schema() -> None:
    schema = f"migration_test_{uuid4().hex}"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    schema_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        schema_url.render_as_string(hide_password=False).replace("%", "%%"),
    )

    try:
        command.upgrade(config, "head")
        migrated_engine = create_engine(schema_url)
        tables = set(inspect(migrated_engine).get_table_names())

        assert {
            "alembic_version",
            "audit_logs",
            "workspace_access_codes",
            "workspace_members",
            "workspace_sessions",
            "workspaces",
            "metric_definitions",
            "data_snapshots",
            "snapshot_metric_values",
            "metric_outbox_events",
            "benchmark_runs",
            "import_batches",
            "import_rows",
            "analysis_runs",
            "account_analysis_settings",
            "analysis_suggestions",
            "product_events",
            "fact_sources",
            "fact_items",
        } <= tables

        access_code_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "workspace_access_codes"
            )
        }
        assert "code_hash" in access_code_columns
        assert "code" not in access_code_columns
        assert "plain_code" not in access_code_columns
        metric_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("metric_definitions")
        }
        assert {
            "workspace_id",
            "platform",
            "content_type",
            "key",
            "unit",
            "aggregation",
            "higher_is_better",
        } <= metric_columns
        content_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("contents")
        }
        assert "content_type" in content_columns
        assert "platform_content_id" in content_columns
        import_batch_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("import_batches")
        }
        assert {
            "recognition_status",
            "recognition_error",
            "screenshot_bytes",
            "screenshot_sha256",
            "screenshot_retention_policy",
            "recognition_output",
        } <= import_batch_columns
        fact_item_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("fact_items")
        }
        assert "field_code" in fact_item_columns
        command.check(config)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_fact_field_code_backfill_matches_runtime_canonicalization() -> None:
    schema = f"fact_backfill_test_{uuid4().hex}"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    schema_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        schema_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    migrated_engine = create_engine(schema_url)
    now = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    workspace_id = uuid4()
    source_id = uuid4()
    expected = {
        "价.格": "price",
        "ＰＲＩＣＥ": "price",
        "面料_成分": "composition",
        "主_色": "color",
        "产品.名称": "custom:产品名称",
        "-": "custom:unclassified",
        "Straße": "custom:straße",
        "ẞ": "custom:ß",
    }

    try:
        command.upgrade(config, "20260723_0014")
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO workspaces (id, name, created_at, updated_at)
                    VALUES (:id, '历史事实迁移', :now, :now)
                    """
                ),
                {"id": workspace_id, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO fact_sources (
                        id, workspace_id, kind, level, title, status,
                        resolved_ips, untrusted_data, status_detail,
                        created_at, updated_at
                    )
                    VALUES (
                        :id, :workspace_id, 'text', 'L2', '历史来源', 'parsed',
                        '[]'::json, true, '{}'::json, :now, :now
                    )
                    """
                ),
                {
                    "id": source_id,
                    "workspace_id": workspace_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO fact_items (
                        id, workspace_id, source_id, field_name, value,
                        source_location, confidence, status, conflict_status,
                        created_at, updated_at
                    )
                    VALUES (
                        :id, :workspace_id, :source_id, :field_name, '测试值',
                        'line 1', 1.0, 'candidate', 'clear', :now, :now
                    )
                    """
                ),
                [
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "source_id": source_id,
                        "field_name": field_name,
                        "now": now,
                    }
                    for field_name in expected
                ],
            )

        command.upgrade(config, "head")
        with migrated_engine.connect() as connection:
            rows = connection.execute(
                text("SELECT field_name, field_code FROM fact_items")
            ).all()

        assert dict(rows) == expected
        command.check(config)
    finally:
        migrated_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
