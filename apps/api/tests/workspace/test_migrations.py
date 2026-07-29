import os
from pathlib import Path
from datetime import UTC, datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.schema_consistency import assert_schema_consistent

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
            "risk_documents",
            "risk_chunks",
            "risk_chunk_embeddings",
            "risk_scans",
            "risk_scan_feedback",
                "risk_feedback_events",
                "extension_tokens",
                "extension_capture_tasks",
                "export_jobs",
                "restore_jobs",
                "knowledge_index_rebuilds",
                "retention_policies",
                "managed_objects",
                "workspace_deletion_confirmations",
                "workspace_deletion_jobs",
                "deletion_audits",
                "task_operation_events",
                "cover_generation_runs",
                "cover_artifact_attempts",
                "model_usage_policies",
                "model_usage_reservations",
                "model_usage_attempts",
                "model_contract_validation_runs",
            } <= tables

        cover_attempt_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "cover_artifact_attempts"
            )
        }
        assert {
            "workspace_id",
            "run_id",
            "attempt_number",
            "previous_attempt_id",
            "provider",
            "model_id",
            "region",
            "model_config_id",
            "configuration_version",
            "contract_version",
            "cover_mode",
            "request_fingerprint",
            "prompt_hash",
            "seed",
            "input_assets",
            "provider_request_id",
            "billed_attempt_status",
            "output_object_key",
            "output_sha256",
            "layout_version",
            "ocr_model_version",
            "risk_scan_id",
            "operation_version",
        } <= cover_attempt_columns
        assert {
            "encrypted_api_key",
            "provider_workspace_id",
            "provider_output_url",
            "image_base64",
        }.isdisjoint(cover_attempt_columns)

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
        model_config_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("model_configs")
        }
        assert {
            "region",
            "provider_workspace_id",
            "encrypted_api_key",
        } <= model_config_columns
        analysis_run_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "analysis_runs"
            )
        }
        assert {
            "model_config_id",
            "model_provider",
            "model_version",
            "model_config_version",
            "provider_contract_version",
        } <= analysis_run_columns
        import_batch_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("import_batches")
        }
        for fenced_table in (
            "text_generation_runs",
            "restore_jobs",
            "workspace_deletion_jobs",
            "extension_capture_tasks",
        ):
            assert "operation_version" in {
                column["name"]
                for column in inspect(migrated_engine).get_columns(fenced_table)
            }
        assert {
            "recognition_status",
            "recognition_error",
            "screenshot_bytes",
            "screenshot_sha256",
            "screenshot_retention_policy",
            "recognition_output",
            "recognition_model_config_id",
            "recognition_provider",
            "recognition_model_id",
            "recognition_contract_version",
            "recognition_config_version",
            "recognition_region",
            "recognition_metric_labels",
        } <= import_batch_columns
        capture_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "extension_capture_tasks"
            )
        }
        assert {
            "model_config_id",
            "provider",
            "model_id",
            "contract_version",
            "config_version",
            "region",
            "metric_labels",
        } <= capture_columns
        fact_item_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("fact_items")
        }
        assert "field_code" in fact_item_columns
        risk_document_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("risk_documents")
        }
        assert {
            "workspace_id",
            "platform",
            "scope",
            "source_level",
            "source_url",
            "private_document_id",
            "published_at",
            "effective_at",
            "accessed_at",
            "authorization_status",
            "reviewed_by",
            "previous_version_id",
            "version",
            "status",
            "file_name",
            "mime_type",
            "object_key",
            "content_sha256",
            "resolved_ips",
            "untrusted_data",
            "redistribution_authorized",
        } <= risk_document_columns
        risk_chunk_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("risk_chunks")
        }
        assert {
            "workspace_id",
            "document_id",
            "platform",
            "scope",
            "chunk_index",
            "source_location",
            "text",
            "metadata",
        } <= risk_chunk_columns
        risk_embedding_columns = {
            column["name"]: column
            for column in inspect(migrated_engine).get_columns(
                "risk_chunk_embeddings"
            )
        }
        assert {
            "workspace_id",
            "chunk_id",
            "platform",
            "scope",
            "model_id",
            "dimension",
            "embedding_version",
            "provider",
            "model_config_id",
            "contract_version",
            "config_version",
            "index_generation",
            "is_active",
            "vector",
        } <= risk_embedding_columns.keys()
        risk_scan_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("risk_scans")
        }
        assert {
            "workspace_id",
            "account_id",
            "content_id",
            "cover_asset_id",
            "previous_scan_id",
            "requested_by",
            "platform",
            "node",
            "status",
            "idempotency_key",
            "input_fingerprint",
            "input_snapshot",
            "result",
            "error_code",
            "diagnostics",
            "rule_version",
            "evidence_version",
            "embedding_model_id",
            "embedding_version",
            "embedding_dimension",
            "rag_model_version",
            "scanner_version",
            "ocr_provider",
            "ocr_model_id",
            "ocr_contract_version",
            "ocr_config_version",
        } <= risk_scan_columns
        risk_feedback_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "risk_scan_feedback"
            )
        }
        assert {
            "workspace_id",
            "scan_id",
            "platform",
            "feedback_type",
            "status",
            "idempotency_key",
            "input_fingerprint",
            "finding_reference",
            "rule_version",
            "evidence_version",
            "submitted_by",
            "comment",
            "comment_untrusted_data",
            "reviewed_by",
            "reviewed_at",
            "review_note",
        } <= risk_feedback_columns
        risk_feedback_event_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "risk_feedback_events"
            )
        }
        assert {
            "workspace_id",
            "feedback_id",
            "event_type",
            "actor_id",
            "safe_note",
        } <= risk_feedback_event_columns
        extension_token_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns(
                "extension_tokens"
            )
        }
        assert {
            "workspace_id",
            "member_id",
            "token_hash",
            "client_id",
            "exchange_fingerprint",
            "scopes",
            "issued_at",
            "expires_at",
            "revoked_at",
        } <= extension_token_columns
        export_job_columns = {
            column["name"]
            for column in inspect(migrated_engine).get_columns("export_jobs")
        }
        assert {
            "workspace_id",
            "requested_by",
            "kind",
            "content_id",
            "idempotency_key",
            "request_fingerprint",
            "status",
            "object_key",
            "file_name",
            "mime_type",
            "error_code",
            "enqueued_at",
            "claim_token",
            "lease_expires_at",
            "completed_at",
        } <= export_job_columns
        with migrated_engine.connect() as connection:
            assert_schema_consistent(
                connection,
                    expected_head="20260729_0033",
                required_tables={
                    "risk_documents",
                    "risk_chunks",
                    "risk_chunk_embeddings",
                    "risk_scans",
                    "risk_scan_feedback",
                    "risk_feedback_events",
                    "extension_tokens",
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
                        "cover_generation_runs",
                        "cover_artifact_attempts",
                        "model_usage_policies",
                        "model_usage_reservations",
                        "model_usage_attempts",
                        "model_contract_validation_runs",
                    },
            )
            extensions = set(
                connection.execute(
                    text("SELECT extname FROM pg_extension")
                ).scalars()
            )
            vector_type = connection.scalar(
                text(
                    """
                    SELECT format_type(attribute.atttypid, attribute.atttypmod)
                    FROM pg_attribute AS attribute
                    WHERE attribute.attrelid =
                        'risk_chunk_embeddings'::regclass
                      AND attribute.attname = 'vector'
                      AND NOT attribute.attisdropped
                    """
                )
            )
        assert "vector" in extensions
        assert vector_type in {"vector", "public.vector"}
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
