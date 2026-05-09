"""Initial SCD2 schema for institutions, tiers, constraints and regulatory rules.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_batches",
        sa.Column("change_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=2048), nullable=True),
    )

    op.create_table(
        "institutions_v",
        sa.Column(
            "institution_row_id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("business_key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("institution_type", sa.String(length=32), nullable=False),
        sa.Column("protection_limit", sa.Numeric(20, 4), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "change_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("change_batches.change_id"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_institutions_v_business_key", "institutions_v", ["business_key"]
    )
    op.create_index(
        "ix_institutions_v_history",
        "institutions_v",
        ["business_key", "effective_from"],
    )
    op.create_index(
        "ux_institutions_v_current_business_key",
        "institutions_v",
        ["business_key"],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    op.create_table(
        "tiers_v",
        sa.Column(
            "tier_row_id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column("institution_business_key", sa.String(length=255), nullable=False),
        sa.Column("tier_index", sa.Integer(), nullable=False),
        sa.Column("limit_mxn", sa.Numeric(20, 4), nullable=True),
        sa.Column("rate", sa.Numeric(10, 8), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "change_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("change_batches.change_id"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tiers_v_institution_business_key",
        "tiers_v",
        ["institution_business_key"],
    )
    op.create_index(
        "ix_tiers_v_history",
        "tiers_v",
        ["institution_business_key", "tier_index", "effective_from"],
    )
    op.create_index(
        "ux_tiers_v_current",
        "tiers_v",
        ["institution_business_key", "tier_index"],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    op.create_table(
        "constraints_v",
        sa.Column(
            "constraint_row_id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("institution_business_key", sa.String(length=255), nullable=False),
        sa.Column("tier_index", sa.Integer(), nullable=False),
        sa.Column("constraint_position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("benefit", sa.String(length=128), nullable=True),
        sa.Column("condition_value", sa.Numeric(20, 6), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("constraint_condition", sa.String(length=255), nullable=True),
        sa.Column("benefit_condition", sa.String(length=255), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "change_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("change_batches.change_id"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_constraints_v_institution_business_key",
        "constraints_v",
        ["institution_business_key"],
    )
    op.create_index(
        "ix_constraints_v_history",
        "constraints_v",
        [
            "institution_business_key",
            "tier_index",
            "constraint_position",
            "effective_from",
        ],
    )
    op.create_index(
        "ux_constraints_v_current",
        "constraints_v",
        ["institution_business_key", "tier_index", "constraint_position"],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    op.create_table(
        "regulatory_rules_v",
        sa.Column(
            "rule_row_id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column("country", sa.String(length=8), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "change_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("change_batches.change_id"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_regulatory_rules_v_country", "regulatory_rules_v", ["country"]
    )
    op.create_index(
        "ix_regulatory_rules_v_history",
        "regulatory_rules_v",
        ["country", "effective_from"],
    )
    op.create_index(
        "ux_regulatory_rules_v_current",
        "regulatory_rules_v",
        ["country"],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("regulatory_rules_v")
    op.drop_table("constraints_v")
    op.drop_table("tiers_v")
    op.drop_table("institutions_v")
    op.drop_table("change_batches")
