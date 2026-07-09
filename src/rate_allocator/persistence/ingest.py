"""Idempotent SCD2 ingestion of institutions and regulatory rules.

The contract is:

* Each call corresponds to at most one ``change_batches`` row, created lazily
  on the first real change. Re-applying the same input is a no-op (no batch,
  no new versions, no closes).
* For every changed natural key, the previous current row is closed
  (``effective_to`` set) and a new row is inserted with the new attributes.
* Natural key hierarchy:
    institutions_v:  (business_key)
    plans_v:         (institution_business_key, plan_key)
    tiers_v:         (institution_business_key, plan_key, tier_index)
    constraints_v:   (institution_business_key, plan_key, tier_index, constraint_position)
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from rate_allocator.domain.models import (
    Constraint,
    Institution,
    Plan,
    RegulatoryRules,
    Tier,
)
from rate_allocator.persistence.models import (
    ChangeBatch,
    ConstraintVersion,
    InstitutionVersion,
    PlanVersion,
    RegulatoryRulesVersion,
    TierVersion,
)

_FLOAT_TOL = 1e-9


@dataclass
class IngestStats:
    """Counters returned by an ingest call; useful for tests and logging."""

    batches_created: int = 0
    institution_versions_inserted: int = 0
    institution_versions_closed: int = 0
    plan_versions_inserted: int = 0
    plan_versions_closed: int = 0
    tier_versions_inserted: int = 0
    tier_versions_closed: int = 0
    constraint_versions_inserted: int = 0
    constraint_versions_closed: int = 0
    deactivated_institutions: int = 0
    rule_versions_inserted: int = 0
    rule_versions_closed: int = 0

    @property
    def has_changes(self) -> bool:
        return self.batches_created > 0


def _to_business_key(name: str) -> str:
    return name


def _limit_to_db(limit: float) -> float | None:
    return None if limit == float("inf") else float(limit)


def _limit_from_db(value) -> float:
    return float("inf") if value is None else float(value)


def _opt_float(value) -> float | None:
    return None if value is None else float(value)


def _floats_close(a: float | None, b: float | None, tol: float = _FLOAT_TOL) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a == float("inf") or b == float("inf"):
        return a == b
    return abs(float(a) - float(b)) <= tol


def _institution_attrs_equal(current: InstitutionVersion, inst: Institution) -> bool:
    return (
        current.name == inst.name
        and current.institution_type == inst.institution_type
        and _floats_close(_opt_float(current.protection_limit), inst.protection_limit)
    )


def _plan_attrs_equal(current: PlanVersion, plan: Plan) -> bool:
    return (
        current.display_name == plan.display_name
        and _floats_close(float(current.monthly_cost), plan.monthly_cost, tol=1e-4)
    )


def _tier_attrs_equal(current: TierVersion, tier: Tier) -> bool:
    return (
        _floats_close(_limit_from_db(current.limit_mxn), tier.limit, tol=1e-4)
        and _floats_close(float(current.rate), tier.rate, tol=1e-9)
    )


def _constraint_attrs_equal(current: ConstraintVersion, constraint: Constraint) -> bool:
    return (
        current.type == constraint.type
        and _floats_close(float(current.cost), constraint.cost, tol=1e-6)
        and current.benefit == constraint.benefit
        and _floats_close(
            _opt_float(current.condition_value), constraint.condition_value, tol=1e-6
        )
        and bool(current.active) == bool(constraint.active)
        and current.constraint_condition == constraint.constraint_condition
        and current.benefit_condition == constraint.benefit_condition
    )


def _regulatory_payload(rules: RegulatoryRules) -> dict:
    return asdict(rules)


def _regulatory_payload_equal(current_payload: dict, expected: dict) -> bool:
    if set(current_payload.keys()) != set(expected.keys()):
        return False
    for key, expected_value in expected.items():
        actual_value = current_payload[key]
        if isinstance(expected_value, float) or isinstance(actual_value, float):
            if not _floats_close(_opt_float(actual_value), _opt_float(expected_value), tol=1e-9):
                return False
        else:
            if actual_value != expected_value:
                return False
    return True


@dataclass
class _BatchHandle:
    session: Session
    applied_at: datetime
    source: str
    actor: str | None
    note: str | None
    stats: IngestStats
    _batch: ChangeBatch | None = field(default=None, init=False, repr=False)

    def get(self) -> ChangeBatch:
        if self._batch is None:
            self._batch = ChangeBatch(
                applied_at=self.applied_at,
                source=self.source,
                actor=self.actor,
                note=self.note,
            )
            self.session.add(self._batch)
            self.session.flush()
            self.stats.batches_created += 1
        return self._batch


def ingest_institutions(
    session: Session,
    institutions: Iterable[Institution],
    *,
    source: str,
    actor: str | None = None,
    note: str | None = None,
    deactivate_missing: bool = False,
    now: datetime | None = None,
) -> IngestStats:
    """Apply an SCD2 update for the given institutions.

    Args:
        session: An active SQLAlchemy session. The caller controls commit/rollback.
        institutions: Domain ``Institution`` objects (e.g. parsed from YAML).
        source: Origin label for the audit trail (e.g. ``"yaml:data/sample1.yaml"``).
        actor: Optional human/service identifier.
        note: Optional free-text note.
        deactivate_missing: If True, current institutions absent from ``institutions``
            are closed (treated as a tombstone). Defaults to False.
        now: Override the SCD2 timestamp; defaults to ``datetime.now(timezone.utc)``.
    """
    institutions = list(institutions)
    timestamp = now or datetime.now(timezone.utc)
    stats = IngestStats()
    batch = _BatchHandle(
        session=session,
        applied_at=timestamp,
        source=source,
        actor=actor,
        note=note,
        stats=stats,
    )

    # Load all current (active) rows up front
    current_inst: dict[str, InstitutionVersion] = {
        v.business_key: v
        for v in session.execute(
            select(InstitutionVersion).where(InstitutionVersion.effective_to.is_(None))
        ).scalars()
    }
    current_plans: dict[tuple[str, str], PlanVersion] = {
        (v.institution_business_key, v.plan_key): v
        for v in session.execute(
            select(PlanVersion).where(PlanVersion.effective_to.is_(None))
        ).scalars()
    }
    current_tiers: dict[tuple[str, str, int], TierVersion] = {
        (v.institution_business_key, v.plan_key, v.tier_index): v
        for v in session.execute(
            select(TierVersion).where(TierVersion.effective_to.is_(None))
        ).scalars()
    }
    current_constraints: dict[tuple[str, str, int, int], ConstraintVersion] = {
        (v.institution_business_key, v.plan_key, v.tier_index, v.constraint_position): v
        for v in session.execute(
            select(ConstraintVersion).where(ConstraintVersion.effective_to.is_(None))
        ).scalars()
    }

    seen_inst_keys: set[str] = set()
    seen_plan_keys: set[tuple[str, str]] = set()
    seen_tier_keys: set[tuple[str, str, int]] = set()
    seen_constraint_keys: set[tuple[str, str, int, int]] = set()

    for inst in institutions:
        bk = _to_business_key(inst.name)
        seen_inst_keys.add(bk)

        # ── Institution ────────────────────────────────────────────────────────
        current = current_inst.get(bk)
        if current is None or not _institution_attrs_equal(current, inst):
            if current is not None:
                current.effective_to = timestamp
                stats.institution_versions_closed += 1
            session.add(
                InstitutionVersion(
                    business_key=bk,
                    name=inst.name,
                    institution_type=inst.institution_type,
                    protection_limit=inst.protection_limit,
                    effective_from=timestamp,
                    effective_to=None,
                    change_id=batch.get().change_id,
                )
            )
            stats.institution_versions_inserted += 1

        # ── Plans ──────────────────────────────────────────────────────────────
        for plan in inst.plans:
            plan_key = (bk, plan.plan_key)
            seen_plan_keys.add(plan_key)

            current_plan = current_plans.get(plan_key)
            if current_plan is None or not _plan_attrs_equal(current_plan, plan):
                if current_plan is not None:
                    current_plan.effective_to = timestamp
                    stats.plan_versions_closed += 1
                session.add(
                    PlanVersion(
                        institution_business_key=bk,
                        plan_key=plan.plan_key,
                        display_name=plan.display_name,
                        monthly_cost=plan.monthly_cost,
                        effective_from=timestamp,
                        effective_to=None,
                        change_id=batch.get().change_id,
                    )
                )
                stats.plan_versions_inserted += 1

            # ── Tiers ──────────────────────────────────────────────────────────
            for tier_index, tier in enumerate(plan.tiers):
                tier_key = (bk, plan.plan_key, tier_index)
                seen_tier_keys.add(tier_key)

                current_tier = current_tiers.get(tier_key)
                if current_tier is None or not _tier_attrs_equal(current_tier, tier):
                    if current_tier is not None:
                        current_tier.effective_to = timestamp
                        stats.tier_versions_closed += 1
                    session.add(
                        TierVersion(
                            institution_business_key=bk,
                            plan_key=plan.plan_key,
                            tier_index=tier_index,
                            limit_mxn=_limit_to_db(tier.limit),
                            rate=tier.rate,
                            effective_from=timestamp,
                            effective_to=None,
                            change_id=batch.get().change_id,
                        )
                    )
                    stats.tier_versions_inserted += 1

                # ── Constraints ────────────────────────────────────────────────
                for position, constraint in enumerate(tier.constraints):
                    constraint_key = (bk, plan.plan_key, tier_index, position)
                    seen_constraint_keys.add(constraint_key)

                    current_c = current_constraints.get(constraint_key)
                    if current_c is None or not _constraint_attrs_equal(current_c, constraint):
                        if current_c is not None:
                            current_c.effective_to = timestamp
                            stats.constraint_versions_closed += 1
                        session.add(
                            ConstraintVersion(
                                institution_business_key=bk,
                                plan_key=plan.plan_key,
                                tier_index=tier_index,
                                constraint_position=position,
                                type=constraint.type,
                                cost=constraint.cost,
                                benefit=constraint.benefit,
                                condition_value=constraint.condition_value,
                                active=constraint.active,
                                constraint_condition=constraint.constraint_condition,
                                benefit_condition=constraint.benefit_condition,
                                effective_from=timestamp,
                                effective_to=None,
                                change_id=batch.get().change_id,
                            )
                        )
                        stats.constraint_versions_inserted += 1

    # ── Close orphaned tiers/constraints for institutions we touched ───────────
    for tier_key, current_tier in current_tiers.items():
        bk = tier_key[0]
        if bk in seen_inst_keys and tier_key not in seen_tier_keys:
            warnings.warn(
                f"Closing tier {tier_key} for institution '{bk}': "
                "tier not present in new data. Verify against official T&Cs.",
                stacklevel=2,
            )
            current_tier.effective_to = timestamp
            stats.tier_versions_closed += 1
            batch.get()

    for constraint_key, current_c in current_constraints.items():
        bk = constraint_key[0]
        if bk in seen_inst_keys and constraint_key not in seen_constraint_keys:
            current_c.effective_to = timestamp
            stats.constraint_versions_closed += 1
            batch.get()

    # ── Close plans for institutions we touched ────────────────────────────────
    for plan_key_tuple, current_plan in current_plans.items():
        bk = plan_key_tuple[0]
        if bk in seen_inst_keys and plan_key_tuple not in seen_plan_keys:
            current_plan.effective_to = timestamp
            stats.plan_versions_closed += 1
            batch.get()

    # ── Deactivate institutions absent from input (tombstone mode) ────────────
    if deactivate_missing:
        for bk, current in current_inst.items():
            if bk in seen_inst_keys:
                continue
            current.effective_to = timestamp
            stats.institution_versions_closed += 1
            stats.deactivated_institutions += 1
            batch.get()
            for tk, ct in current_tiers.items():
                if tk[0] == bk and ct.effective_to is None:
                    ct.effective_to = timestamp
                    stats.tier_versions_closed += 1
            for pk, cp in current_plans.items():
                if pk[0] == bk and cp.effective_to is None:
                    cp.effective_to = timestamp
                    stats.plan_versions_closed += 1
            for ck, cc in current_constraints.items():
                if ck[0] == bk and cc.effective_to is None:
                    cc.effective_to = timestamp
                    stats.constraint_versions_closed += 1

    return stats


def ingest_regulatory_rules(
    session: Session,
    rules: RegulatoryRules,
    *,
    source: str,
    actor: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> IngestStats:
    """SCD2-ingest a regulatory-rules snapshot for one country."""
    timestamp = now or datetime.now(timezone.utc)
    stats = IngestStats()
    batch = _BatchHandle(
        session=session,
        applied_at=timestamp,
        source=source,
        actor=actor,
        note=note,
        stats=stats,
    )

    expected_payload = _regulatory_payload(rules)
    current = session.execute(
        select(RegulatoryRulesVersion).where(
            RegulatoryRulesVersion.country == rules.country,
            RegulatoryRulesVersion.effective_to.is_(None),
        )
    ).scalar_one_or_none()

    if current is not None and _regulatory_payload_equal(current.payload, expected_payload):
        return stats

    if current is not None:
        current.effective_to = timestamp
        stats.rule_versions_closed += 1

    session.add(
        RegulatoryRulesVersion(
            country=rules.country,
            payload=expected_payload,
            effective_from=timestamp,
            effective_to=None,
            change_id=batch.get().change_id,
        )
    )
    stats.rule_versions_inserted += 1
    return stats


__all__ = [
    "IngestStats",
    "ingest_institutions",
    "ingest_regulatory_rules",
]
