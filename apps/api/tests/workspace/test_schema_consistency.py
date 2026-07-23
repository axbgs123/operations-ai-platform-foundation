from sqlalchemy import create_engine, text

import pytest

from app.core.schema_consistency import (
    SchemaConsistencyError,
    assert_schema_consistent,
)


HEAD = "20260723_0019"


def _database_with_version(*, include_risk_scans: bool):
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
        if include_risk_scans:
            connection.execute(text("CREATE TABLE risk_scans (id VARCHAR)"))
    return engine


def test_head_version_without_required_tables_fails_schema_consistency() -> None:
    engine = _database_with_version(include_risk_scans=False)

    with engine.connect() as connection:
        with pytest.raises(
            SchemaConsistencyError,
            match="head.*missing.*risk_scans",
        ):
            assert_schema_consistent(
                connection,
                expected_head=HEAD,
                required_tables={"risk_scans"},
            )


def test_head_version_with_required_tables_passes_schema_consistency() -> None:
    engine = _database_with_version(include_risk_scans=True)

    with engine.connect() as connection:
        assert_schema_consistent(
            connection,
            expected_head=HEAD,
            required_tables={"risk_scans"},
        )
