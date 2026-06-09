"""One-off history correction applied on 2026-05-08.

Records two business-level changes that weren't captured by the YAML ingest:

* OpenBank: 9% all-tiers from 2026-01-01 to 2026-03-10, then the current
  13% / 7.3% / 7% structure from 2026-03-10 onwards.
* PlataAhorroPlus: 12% from 2026-01-01 to 2026-05-07, then 10% from
  2026-05-07 onwards.

Three ``change_batches`` rows are created so the audit trail mirrors the
real business timeline. The script is idempotent: re-running detects the
already-applied state and is a no-op.

Usage::

    python scripts/backfill_history_2026_05_08.py
    python scripts/backfill_history_2026_05_08.py --db-url sqlite:///data/rates.db
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy import select

from rate_allocator.persistence import (
    create_db_engine,
    get_database_url,
    session_scope,
)
from rate_allocator.persistence.models import (
    ChangeBatch,
    ConstraintVersion,
    InstitutionVersion,
    TierVersion,
)

OPENBANK = "OpenBank"
PLATA = "PlataAhorroPlus"

OPENBANK_BASELINE_FROM = datetime(2026, 1, 1, tzinfo=timezone.utc)
OPENBANK_CHANGE_AT = datetime(2026, 3, 10, tzinfo=timezone.utc)

PLATA_BASELINE_FROM = datetime(2026, 1, 1, tzinfo=timezone.utc)
PLATA_CHANGE_AT = datetime(2026, 5, 7, tzinfo=timezone.utc)

OPENBANK_BASELINE_TIERS = [
    {"tier_index": 0, "limit_mxn": 40_000, "rate": 0.09},
    {"tier_index": 1, "limit_mxn": 1_000_000, "rate": 0.09},
    {"tier_index": 2, "limit_mxn": None, "rate": 0.09},
]


def _make_batch(session, applied_at, source, note):
    batch = ChangeBatch(applied_at=applied_at, source=source, note=note)
    session.add(batch)
    session.flush()
    return batch


def _already_applied(session) -> bool:
    """Detect whether this backfill has already run.

    The cheapest signal: the historical OpenBank 9% rows only exist after
    this script has been applied.
    """
    historical = session.execute(
        select(TierVersion)
        .where(TierVersion.institution_business_key == OPENBANK)
        .where(TierVersion.rate == 0.09)
    ).first()
    return historical is not None


def _current_openbank_tiers(session) -> list[TierVersion]:
    return list(
        session.execute(
            select(TierVersion)
            .where(TierVersion.institution_business_key == OPENBANK)
            .where(TierVersion.effective_to.is_(None))
            .order_by(TierVersion.tier_index)
        ).scalars()
    )


def _current_plata_tier(session) -> TierVersion | None:
    return session.execute(
        select(TierVersion)
        .where(TierVersion.institution_business_key == PLATA)
        .where(TierVersion.effective_to.is_(None))
    ).scalar_one_or_none()


def apply(session) -> None:
    if _already_applied(session):
        print("backfill already applied; nothing to do")
        return

    openbank_baseline_batch = _make_batch(
        session,
        applied_at=OPENBANK_BASELINE_FROM,
        source="manual:backfill_history_2026_05_08",
        note="OpenBank 9% all-tiers baseline (history backfill)",
    )
    openbank_change_batch = _make_batch(
        session,
        applied_at=OPENBANK_CHANGE_AT,
        source="manual:backfill_history_2026_05_08",
        note="OpenBank rate cut to 13/7.3/7 (history backfill)",
    )
    plata_change_batch = _make_batch(
        session,
        applied_at=PLATA_CHANGE_AT,
        source="manual:backfill_history_2026_05_08",
        note="PlataAhorroPlus rate cut from 12% to 10%",
    )

    current_openbank = _current_openbank_tiers(session)
    if not current_openbank:
        raise RuntimeError(
            "OpenBank has no current tiers; ingest sample1.yaml first."
        )

    for current_tier in current_openbank:
        current_tier.effective_from = OPENBANK_CHANGE_AT
        current_tier.change_id = openbank_change_batch.change_id

    for spec in OPENBANK_BASELINE_TIERS:
        session.add(
            TierVersion(
                institution_business_key=OPENBANK,
                tier_index=spec["tier_index"],
                limit_mxn=spec["limit_mxn"],
                rate=spec["rate"],
                effective_from=OPENBANK_BASELINE_FROM,
                effective_to=OPENBANK_CHANGE_AT,
                change_id=openbank_baseline_batch.change_id,
            )
        )

    plata_current = _current_plata_tier(session)
    if plata_current is None:
        raise RuntimeError(
            "PlataAhorroPlus has no current tier; ingest sample1.yaml first."
        )

    plata_current.effective_from = PLATA_BASELINE_FROM
    plata_current.effective_to = PLATA_CHANGE_AT

    for business_key, baseline_from in (
        (OPENBANK, OPENBANK_BASELINE_FROM),
        (PLATA, PLATA_BASELINE_FROM),
    ):
        inst = session.execute(
            select(InstitutionVersion)
            .where(InstitutionVersion.business_key == business_key)
            .where(InstitutionVersion.effective_to.is_(None))
        ).scalar_one_or_none()
        if inst is not None:
            inst.effective_from = baseline_from

        constraints = session.execute(
            select(ConstraintVersion)
            .where(ConstraintVersion.institution_business_key == business_key)
            .where(ConstraintVersion.effective_to.is_(None))
        ).scalars()
        for c in constraints:
            c.effective_from = baseline_from

    session.add(
        TierVersion(
            institution_business_key=PLATA,
            tier_index=plata_current.tier_index,
            limit_mxn=plata_current.limit_mxn,
            rate=0.10,
            effective_from=PLATA_CHANGE_AT,
            effective_to=None,
            change_id=plata_change_batch.change_id,
        )
    )

    print("applied:")
    print(
        f"  OpenBank: 9% all-tiers {OPENBANK_BASELINE_FROM.date()} -> "
        f"{OPENBANK_CHANGE_AT.date()}, then 13/7.3/7 from "
        f"{OPENBANK_CHANGE_AT.date()}"
    )
    print(
        f"  PlataAhorroPlus: 12% {PLATA_BASELINE_FROM.date()} -> "
        f"{PLATA_CHANGE_AT.date()}, then 10% from {PLATA_CHANGE_AT.date()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "Override the DB URL; otherwise read from RATE_ALLOCATOR_DB_URL "
            "or fall back to the local SQLite default."
        ),
    )
    args = parser.parse_args(argv)

    db_url = args.db_url or get_database_url()
    engine = create_db_engine(db_url)
    print(f"db_url: {db_url}")

    with session_scope(engine) as session:
        apply(session)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
