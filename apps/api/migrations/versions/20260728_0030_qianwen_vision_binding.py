"""Freeze Qianwen vision bindings on OCR business records.

Revision ID: 20260728_0030
Revises: 20260728_0029
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0030"
down_revision: str | None = "20260728_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _binding_columns(table: str, *, prefix: str) -> None:
    op.add_column(
        table,
        sa.Column(f"{prefix}model_config_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        table,
        sa.Column(
            f"{prefix}provider",
            sa.String(length=80),
            nullable=False,
            server_default="mock",
        ),
    )
    op.add_column(
        table,
        sa.Column(
            f"{prefix}model_id",
            sa.String(length=160),
            nullable=False,
            server_default="mock-vision-v1",
        ),
    )
    op.add_column(
        table,
        sa.Column(
            f"{prefix}contract_version",
            sa.String(length=80),
            nullable=False,
            server_default="mock-vision-v1",
        ),
    )
    op.add_column(
        table,
        sa.Column(
            f"{prefix}config_version",
            sa.String(length=80),
            nullable=False,
            server_default="mock-static-v1",
        ),
    )
    op.create_foreign_key(
        f"fk_{table}_{prefix}model_config_id",
        table,
        "model_configs",
        [f"{prefix}model_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    _binding_columns("import_batches", prefix="recognition_")
    op.add_column(
        "import_batches",
        sa.Column(
            "recognition_metric_labels",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column("recognition_region", sa.String(length=32), nullable=True),
    )
    _binding_columns("extension_capture_tasks", prefix="")
    op.add_column(
        "extension_capture_tasks",
        sa.Column(
            "metric_labels",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "extension_capture_tasks",
        sa.Column("region", sa.String(length=32), nullable=True),
    )
    for name, length, default in (
        ("ocr_provider", 80, "mock"),
        ("ocr_model_id", 160, "mock-ocr-v1"),
        ("ocr_contract_version", 80, "mock-ocr-v1"),
        ("ocr_config_version", 80, "mock-static-v1"),
    ):
        op.add_column(
            "risk_scans",
            sa.Column(
                name,
                sa.String(length=length),
                nullable=False,
                server_default=default,
            ),
        )


def downgrade() -> None:
    for name in (
        "ocr_config_version",
        "ocr_contract_version",
        "ocr_model_id",
        "ocr_provider",
    ):
        op.drop_column("risk_scans", name)
    op.drop_column("extension_capture_tasks", "region")
    op.drop_column("extension_capture_tasks", "metric_labels")
    op.drop_constraint(
        "fk_extension_capture_tasks_model_config_id",
        "extension_capture_tasks",
        type_="foreignkey",
    )
    for name in (
        "config_version",
        "contract_version",
        "model_id",
        "provider",
        "model_config_id",
    ):
        op.drop_column("extension_capture_tasks", name)
    op.drop_column("import_batches", "recognition_region")
    op.drop_column("import_batches", "recognition_metric_labels")
    op.drop_constraint(
        "fk_import_batches_recognition_model_config_id",
        "import_batches",
        type_="foreignkey",
    )
    for name in (
        "recognition_config_version",
        "recognition_contract_version",
        "recognition_model_id",
        "recognition_provider",
        "recognition_model_config_id",
    ):
        op.drop_column("import_batches", name)
