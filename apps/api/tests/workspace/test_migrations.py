import os
from pathlib import Path
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
            "workspaces",
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
        command.check(config)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
