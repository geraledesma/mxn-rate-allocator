"""Drop legacy flat tables: institution, tier, tier_constraint.

These were created by sqlite_loader.py (pre-SCD2 approach) and are no longer
used by the application. All institution data lives in institutions_v / plans_v /
tiers_v / constraints_v.

Revision ID: 0004_drop_legacy_tables
Revises: 0003_plans_schema
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_drop_legacy_tables"
down_revision: Union[str, None] = "0003_plans_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {r[0] for r in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
    for table in ("tier_constraint", "tier", "institution"):
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    op.create_table(
        "institution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("institution_type", sa.Text(), nullable=False, server_default="none"),
        sa.Column("protection_limit", sa.Real(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "tier",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institution.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tier_order", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Real(), nullable=False),
        sa.Column("limit_value", sa.Real(), nullable=False, server_default="0"),
        sa.Column("limit_is_inf", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("institution_id", "tier_order"),
    )
    op.create_table(
        "tier_constraint",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tier_id", sa.Integer(), sa.ForeignKey("tier.id", ondelete="CASCADE"), nullable=False),
        sa.Column("constraint_order", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("cost", sa.Real(), nullable=False, server_default="0"),
        sa.Column("benefit", sa.Text(), nullable=True),
        sa.Column("condition_value", sa.Real(), nullable=True),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("constraint_condition", sa.Text(), nullable=True),
        sa.Column("benefit_condition", sa.Text(), nullable=True),
        sa.UniqueConstraint("tier_id", "constraint_order"),
    )
    op.create_index("idx_tier_inst", "tier", ["institution_id"])
    op.create_index("idx_constraint_tier", "tier_constraint", ["tier_id"])
