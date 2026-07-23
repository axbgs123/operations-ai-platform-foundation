"""Persist canonical fact field codes.

Revision ID: 20260723_0015
Revises: 20260723_0014
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0015"
down_revision: str | None = "20260723_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fact_items",
        sa.Column("field_code", sa.String(length=160), nullable=True),
    )
    op.execute(
        sa.text(
            """
            WITH normalized_fact_fields AS (
                SELECT
                    id,
                    regexp_replace(
                        lower(normalize(field_name, NFKC)),
                        '[^[:alnum:]]+',
                        '',
                        'g'
                    ) AS normalized
                FROM fact_items
            )
            UPDATE fact_items
            SET field_code = CASE
                WHEN normalized IN (
                    '面料成分', '成分', 'composition', 'ingredient', 'fibercontent'
                )
                    THEN 'composition'
                WHEN normalized IN (
                    '价格', '售价', '吊牌价', '零售价', 'price', 'msrp', 'rrp', 'cost'
                )
                    THEN 'price'
                WHEN normalized IN (
                    '尺码参数', '尺码', '规格尺寸', '尺寸', 'sizeparameters',
                    'sizeparameter', 'size', 'dimension', 'measurement'
                )
                    THEN 'size_parameters'
                WHEN normalized IN (
                    '功效', '效果', 'efficacy', 'benefit', 'effect'
                )
                    THEN 'efficacy'
                WHEN normalized IN (
                    '认证', '资质', 'certification', 'certificate', 'certified'
                )
                    THEN 'certification'
                WHEN normalized IN (
                    '原产地', '产地', 'countryoforigin', 'madein', 'origin'
                )
                    THEN 'origin'
                WHEN normalized IN (
                    '安全承诺', '安全性', '无毒', 'safetyclaim', 'safety', 'nontoxic'
                )
                    THEN 'safety_claim'
                WHEN normalized IN ('面料', '材质', 'fabric', 'material')
                    THEN 'fabric'
                WHEN normalized IN ('主色', '颜色', 'color', 'primarycolor')
                    THEN 'color'
                WHEN normalized = '' THEN 'custom:unclassified'
                ELSE 'custom:' || normalized
            END
            FROM normalized_fact_fields
            WHERE fact_items.id = normalized_fact_fields.id
            """
        )
    )
    op.alter_column("fact_items", "field_code", nullable=False)
    op.create_index("ix_fact_items_field_code", "fact_items", ["field_code"])


def downgrade() -> None:
    op.drop_index("ix_fact_items_field_code", table_name="fact_items")
    op.drop_column("fact_items", "field_code")
