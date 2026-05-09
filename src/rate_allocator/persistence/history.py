"""Read-side helpers for SCD2 audit trails (tier rate history, etc.)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rate_allocator.persistence.models import ChangeBatch, InstitutionVersion, TierVersion

_FLOAT_TOL = 1e-9


@dataclass(frozen=True)
class TierRateChangeEvent:
    """One detected tier nominal-rate change across SCD2 versions."""

    effective_from: datetime
    applied_at: datetime
    institution_name: str
    institution_key: str
    tier_index: int
    old_rate: float
    new_rate: float
    source: str
    note: str | None


def _current_institution_names(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(InstitutionVersion.business_key, InstitutionVersion.name).where(
            InstitutionVersion.effective_to.is_(None)
        )
    ).all()
    return {bk: name for bk, name in rows}


def load_recent_tier_rate_changes(
    session: Session,
    *,
    limit: int = 50,
) -> list[TierRateChangeEvent]:
    """Return the most recent tier nominal-rate changes (newest first).

    Walks tier version history in effective order and emits an event whenever
    the stored ``rate`` differs from the immediately prior version for the same
    ``(institution_business_key, tier_index)``.
    """
    rows = list(
        session.execute(
            select(TierVersion).order_by(
                TierVersion.institution_business_key,
                TierVersion.tier_index,
                TierVersion.effective_from,
                TierVersion.tier_row_id,
            )
        ).scalars()
    )

    names = _current_institution_names(session)
    prev_by_key: dict[tuple[str, int], TierVersion] = {}
    events_raw: list[tuple[TierVersion, TierVersion]] = []

    for row in rows:
        key = (row.institution_business_key, row.tier_index)
        prev = prev_by_key.get(key)
        if prev is None:
            prev_by_key[key] = row
            continue
        old_r = float(prev.rate)
        new_r = float(row.rate)
        if abs(old_r - new_r) > _FLOAT_TOL:
            events_raw.append((prev, row))
        prev_by_key[key] = row

    batch_cache: dict[Any, ChangeBatch | None] = {}

    def _batch(cid) -> ChangeBatch | None:
        if cid not in batch_cache:
            batch_cache[cid] = session.get(ChangeBatch, cid)
        return batch_cache[cid]

    events: list[TierRateChangeEvent] = []
    for prev, row in reversed(events_raw):
        batch = _batch(row.change_id)
        applied = batch.applied_at if batch is not None else row.effective_from
        bk = row.institution_business_key
        events.append(
            TierRateChangeEvent(
                effective_from=row.effective_from,
                applied_at=applied,
                institution_name=names.get(bk, bk),
                institution_key=bk,
                tier_index=row.tier_index,
                old_rate=float(prev.rate),
                new_rate=float(row.rate),
                source=batch.source if batch else "",
                note=batch.note if batch else None,
            )
        )
        if len(events) >= limit:
            break

    return events


__all__ = ["TierRateChangeEvent", "load_recent_tier_rate_changes"]
