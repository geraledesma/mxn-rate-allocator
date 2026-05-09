"""Database adapter that returns the same domain objects as the YAML loader.

This is the read side of the SCD2 schema. Without ``as_of`` it returns the
current snapshot (rows where ``effective_to IS NULL``). With ``as_of`` it
returns the point-in-time snapshot (``effective_from <= as_of <
effective_to``), which is useful for backtesting historical rate changes
through the same allocator code.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from rate_allocator.domain.models import (
    Constraint,
    Institution,
    InstitutionType,
    RegulatoryRules,
    Tier,
)
from rate_allocator.persistence.models import (
    ConstraintVersion,
    InstitutionVersion,
    RegulatoryRulesVersion,
    TierVersion,
)


def _current_filter(model_cls, as_of: datetime | None):
    if as_of is None:
        return model_cls.effective_to.is_(None)
    return and_(
        model_cls.effective_from <= as_of,
        or_(model_cls.effective_to.is_(None), model_cls.effective_to > as_of),
    )


def _limit_from_db(value) -> float:
    if value is None:
        return float("inf")
    return float(value)


def _build_constraints_for_tier(
    rows: list[ConstraintVersion],
) -> tuple[Constraint, ...]:
    rows.sort(key=lambda r: r.constraint_position)
    return tuple(
        Constraint(
            type=row.type,
            cost=float(row.cost),
            benefit=row.benefit,
            condition_value=(
                None if row.condition_value is None else float(row.condition_value)
            ),
            active=bool(row.active),
            constraint_condition=row.constraint_condition,
            benefit_condition=row.benefit_condition,
        )
        for row in rows
    )


def load_institutions_from_db(
    session: Session, *, as_of: datetime | None = None
) -> list[Institution]:
    """Return ``Institution`` dataclasses matching the YAML loader's output.

    Args:
        session: An active SQLAlchemy session bound to a schema-initialized DB.
        as_of: If provided, return the snapshot effective at that timestamp.
            Defaults to None (current).
    """
    inst_rows = list(
        session.execute(
            select(InstitutionVersion).where(
                _current_filter(InstitutionVersion, as_of)
            )
        ).scalars()
    )
    inst_rows.sort(key=lambda r: r.business_key)

    business_keys = [row.business_key for row in inst_rows]
    if not business_keys:
        return []

    tier_rows = list(
        session.execute(
            select(TierVersion).where(
                TierVersion.institution_business_key.in_(business_keys),
                _current_filter(TierVersion, as_of),
            )
        ).scalars()
    )
    constraint_rows = list(
        session.execute(
            select(ConstraintVersion).where(
                ConstraintVersion.institution_business_key.in_(business_keys),
                _current_filter(ConstraintVersion, as_of),
            )
        ).scalars()
    )

    tiers_by_inst: dict[str, list[TierVersion]] = {}
    for row in tier_rows:
        tiers_by_inst.setdefault(row.institution_business_key, []).append(row)

    constraints_by_tier: dict[tuple[str, int], list[ConstraintVersion]] = {}
    for row in constraint_rows:
        key = (row.institution_business_key, row.tier_index)
        constraints_by_tier.setdefault(key, []).append(row)

    institutions: list[Institution] = []
    for inst_row in inst_rows:
        owned_tiers = sorted(
            tiers_by_inst.get(inst_row.business_key, []),
            key=lambda t: t.tier_index,
        )
        if not owned_tiers:
            continue
        tiers = tuple(
            Tier(
                limit=_limit_from_db(tier_row.limit_mxn),
                rate=float(tier_row.rate),
                constraints=_build_constraints_for_tier(
                    list(
                        constraints_by_tier.get(
                            (inst_row.business_key, tier_row.tier_index), []
                        )
                    )
                ),
            )
            for tier_row in owned_tiers
        )
        institutions.append(
            Institution(
                name=inst_row.name,
                tiers=tiers,
                institution_type=cast(InstitutionType, inst_row.institution_type),
                protection_limit=(
                    None
                    if inst_row.protection_limit is None
                    else float(inst_row.protection_limit)
                ),
            )
        )
    return institutions


def load_regulatory_rules_from_db(
    session: Session,
    *,
    country: str = "MX",
    as_of: datetime | None = None,
) -> RegulatoryRules | None:
    """Return the active ``RegulatoryRules`` for a country, or None if absent."""
    row = session.execute(
        select(RegulatoryRulesVersion).where(
            RegulatoryRulesVersion.country == country,
            _current_filter(RegulatoryRulesVersion, as_of),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    payload = dict(row.payload)
    return RegulatoryRules(**payload)


__all__ = [
    "load_institutions_from_db",
    "load_regulatory_rules_from_db",
]
