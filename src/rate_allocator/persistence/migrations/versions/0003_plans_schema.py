"""Add plans_v (SCD2) + plan_key to tiers_v and constraints_v.

Introduces the Institution → Plan → Tier hierarchy:
  - plans_v: one SCD2 row per (institution, plan). Holds display_name and monthly_cost.
  - tiers_v.plan_key: discriminates tiers by plan within an institution.
  - constraints_v.plan_key: mirrors tiers_v so the natural key stays consistent.

Natural keys after this migration:
  - plans_v:       (institution_business_key, plan_key)           WHERE effective_to IS NULL
  - tiers_v:       (institution_business_key, plan_key, tier_index) WHERE effective_to IS NULL
  - constraints_v: (institution_business_key, plan_key, tier_index, constraint_position) WHERE effective_to IS NULL

Revision ID: 0003_plans_schema
Revises: 0002_vigente_desde
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_plans_schema"
down_revision: Union[str, None] = "0002_vigente_desde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── plans_v ────────────────────────────────────────────────────────────────
    op.create_table(
        "plans_v",
        sa.Column("plan_row_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("institution_business_key", sa.String(255), nullable=False, index=True),
        sa.Column("plan_key", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("monthly_cost", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "change_id",
            sa.String(32),
            sa.ForeignKey("change_batches.change_id"),
            nullable=False,
        ),
    )
    with op.batch_alter_table("plans_v") as batch_op:
        batch_op.create_index(
            "ux_plans_v_current",
            ["institution_business_key", "plan_key"],
            unique=True,
            sqlite_where=sa.text("effective_to IS NULL"),
        )
        batch_op.create_index(
            "ix_plans_v_history",
            ["institution_business_key", "plan_key", "effective_from"],
        )

    # ── tiers_v: add plan_key, rebuild unique index ────────────────────────────
    with op.batch_alter_table("tiers_v") as batch_op:
        batch_op.add_column(
            sa.Column("plan_key", sa.String(64), nullable=False, server_default="base")
        )
        batch_op.drop_index("ux_tiers_v_current")
        batch_op.create_index(
            "ux_tiers_v_current",
            ["institution_business_key", "plan_key", "tier_index"],
            unique=True,
            sqlite_where=sa.text("effective_to IS NULL"),
        )
        batch_op.drop_index("ix_tiers_v_history")
        batch_op.create_index(
            "ix_tiers_v_history",
            ["institution_business_key", "plan_key", "tier_index", "effective_from"],
        )

    # ── constraints_v: add plan_key, rebuild unique index ─────────────────────
    with op.batch_alter_table("constraints_v") as batch_op:
        batch_op.add_column(
            sa.Column("plan_key", sa.String(64), nullable=False, server_default="base")
        )
        batch_op.drop_index("ux_constraints_v_current")
        batch_op.create_index(
            "ux_constraints_v_current",
            ["institution_business_key", "plan_key", "tier_index", "constraint_position"],
            unique=True,
            sqlite_where=sa.text("effective_to IS NULL"),
        )
        batch_op.drop_index("ix_constraints_v_history")
        batch_op.create_index(
            "ix_constraints_v_history",
            ["institution_business_key", "plan_key", "tier_index", "constraint_position", "effective_from"],
        )


def downgrade() -> None:
    with op.batch_alter_table("constraints_v") as batch_op:
        batch_op.drop_index("ux_constraints_v_current")
        batch_op.drop_index("ix_constraints_v_history")
        batch_op.drop_column("plan_key")
        batch_op.create_index(
            "ux_constraints_v_current",
            ["institution_business_key", "tier_index", "constraint_position"],
            unique=True,
            sqlite_where=sa.text("effective_to IS NULL"),
        )
        batch_op.create_index(
            "ix_constraints_v_history",
            ["institution_business_key", "tier_index", "constraint_position", "effective_from"],
        )

    with op.batch_alter_table("tiers_v") as batch_op:
        batch_op.drop_index("ux_tiers_v_current")
        batch_op.drop_index("ix_tiers_v_history")
        batch_op.drop_column("plan_key")
        batch_op.create_index(
            "ux_tiers_v_current",
            ["institution_business_key", "tier_index"],
            unique=True,
            sqlite_where=sa.text("effective_to IS NULL"),
        )
        batch_op.create_index(
            "ix_tiers_v_history",
            ["institution_business_key", "tier_index", "effective_from"],
        )

    op.drop_table("plans_v")
