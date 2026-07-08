"""Add vigente_desde to change_batches (institution's stated effective date, separate from discovery).

Revision ID: 0002_vigente_desde
Revises: 0001_initial_schema
Create Date: 2026-07-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_vigente_desde"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("change_batches", sa.Column("vigente_desde", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("change_batches", "vigente_desde")
