"""SQLAlchemy ORM models for the SCD2 institution-rates schema.

Every versioned row carries ``effective_from`` and ``effective_to``. A NULL
``effective_to`` marks the row as currently active. Updates close the old row
(set ``effective_to`` to the new ``effective_from``) and insert a new row in
the same transaction. Each ingest gets a single ``change_batches`` row that
all touched versions reference, so the whole change is atomic and auditable.

The schema is portable across SQLite and PostgreSQL. Partial unique indexes
("only one current row per natural key") are expressed with the SQL
``WHERE effective_to IS NULL`` clause, which both engines support.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all persistence models."""


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class ChangeBatch(Base):
    """One row per ingestion event; groups all SCD2 versions written together."""

    __tablename__ = "change_batches"

    change_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=_new_uuid
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    vigente_desde: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)


class InstitutionVersion(Base):
    """SCD2 row for an institution's identity and type-level attributes."""

    __tablename__ = "institutions_v"

    institution_row_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    business_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_type: Mapped[str] = mapped_column(String(32), nullable=False)
    protection_limit: Mapped[Optional[float]] = mapped_column(
        Numeric(20, 4), nullable=True
    )

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    change_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("change_batches.change_id"), nullable=False
    )

    batch: Mapped[ChangeBatch] = relationship(ChangeBatch)

    __table_args__ = (
        Index(
            "ux_institutions_v_current_business_key",
            "business_key",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_institutions_v_history",
            "business_key",
            "effective_from",
        ),
    )


class TierVersion(Base):
    """SCD2 row for a single rate tier within an institution.

    The natural key is ``(institution_business_key, tier_index)``. Tier order
    is meaningful in this domain (sequential filling), so the ordinal position
    is part of identity, not just data. ``limit_mxn = NULL`` represents the
    open-ended (``inf``) tier; the loader maps it back to ``float("inf")``.
    """

    __tablename__ = "tiers_v"

    tier_row_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    institution_business_key: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    tier_index: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_mxn: Mapped[Optional[float]] = mapped_column(Numeric(20, 4), nullable=True)
    rate: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    change_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("change_batches.change_id"), nullable=False
    )

    __table_args__ = (
        Index(
            "ux_tiers_v_current",
            "institution_business_key",
            "tier_index",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_tiers_v_history",
            "institution_business_key",
            "tier_index",
            "effective_from",
        ),
    )


class ConstraintVersion(Base):
    """SCD2 row for a constraint attached to a specific tier.

    Natural key: ``(institution_business_key, tier_index, constraint_position)``.
    ``constraint_position`` disambiguates multiple constraints of the same type
    on the same tier and preserves YAML order.
    """

    __tablename__ = "constraints_v"

    constraint_row_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    institution_business_key: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    tier_index: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_position: Mapped[int] = mapped_column(Integer, nullable=False)

    type: Mapped[str] = mapped_column(String(64), nullable=False)
    cost: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, default=0.0)
    benefit: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    condition_value: Mapped[Optional[float]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    constraint_condition: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    benefit_condition: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    change_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("change_batches.change_id"), nullable=False
    )

    __table_args__ = (
        Index(
            "ux_constraints_v_current",
            "institution_business_key",
            "tier_index",
            "constraint_position",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_constraints_v_history",
            "institution_business_key",
            "tier_index",
            "constraint_position",
            "effective_from",
        ),
    )


class RegulatoryRulesVersion(Base):
    """SCD2 row holding the full regulatory-rules payload for one country.

    Rule fields evolve and are interconnected (insurance, tax, exemptions),
    so we store them as a JSON payload rather than a wide column list.
    """

    __tablename__ = "regulatory_rules_v"

    rule_row_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    country: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    change_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("change_batches.change_id"), nullable=False
    )

    __table_args__ = (
        Index(
            "ux_regulatory_rules_v_current",
            "country",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index(
            "ix_regulatory_rules_v_history",
            "country",
            "effective_from",
        ),
    )


__all__ = [
    "Base",
    "ChangeBatch",
    "ConstraintVersion",
    "InstitutionVersion",
    "RegulatoryRulesVersion",
    "TierVersion",
]
