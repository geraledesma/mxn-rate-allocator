"""Tests for the SCD2 persistence layer.

Covers:
- Schema bootstrap (Alembic migration runs to head against a fresh DB).
- Idempotent re-ingest (no new versions when input is unchanged).
- Diff isolation (changing one tier's rate produces exactly one closed +
  one new tier row, with everything else untouched).
- Time-travel (``as_of`` returns the historical snapshot, no ``as_of``
  returns the current snapshot).
- Allocator parity (DB-loaded institutions yield the same expected_return
  as YAML-loaded institutions for the same input).
- Regulatory rules round-trip and idempotency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from rate_allocator import allocate
from rate_allocator.adapters.db_loader import (
    load_institutions_from_db,
    load_regulatory_rules_from_db,
)
from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml
from rate_allocator.domain.models import Constraint, Institution, Tier
from rate_allocator.persistence import (
    create_db_engine,
    init_schema,
    session_scope,
)
from rate_allocator.persistence.history import load_recent_tier_rate_changes
from rate_allocator.persistence.ingest import (
    ingest_institutions,
    ingest_regulatory_rules,
)
from rate_allocator.persistence.models import (
    ChangeBatch,
    InstitutionVersion,
    TierVersion,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_YAML = REPO_ROOT / "data" / "sample1.yaml"
RULES_YAML = REPO_ROOT / "data" / "regulatory_rules.mx.yaml"


@pytest.fixture
def engine(tmp_path):
    """Fresh in-memory SQLite engine with the schema created."""
    engine = create_db_engine("sqlite:///:memory:")
    init_schema(engine)
    return engine


def _count_current(session, model_cls) -> int:
    return len(
        list(
            session.execute(
                select(model_cls).where(model_cls.effective_to.is_(None))
            ).scalars()
        )
    )


def _count_total(session, model_cls) -> int:
    return len(list(session.execute(select(model_cls)).scalars()))


class TestSchemaMigration:
    def test_alembic_upgrade_runs_to_head(self, tmp_path):
        db_file = tmp_path / "rates.db"
        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url", f"sqlite:///{db_file}"
        )
        command.upgrade(config, "head")

        from sqlalchemy import create_engine, inspect

        inspector = inspect(create_engine(f"sqlite:///{db_file}"))
        tables = set(inspector.get_table_names())
        assert {
            "alembic_version",
            "change_batches",
            "institutions_v",
            "tiers_v",
            "constraints_v",
            "regulatory_rules_v",
        }.issubset(tables)

        idx_names = {ix["name"] for ix in inspector.get_indexes("institutions_v")}
        assert "ux_institutions_v_current_business_key" in idx_names


class TestIdempotentReingest:
    def test_first_run_writes_one_batch_then_noop(self, engine):
        institutions = load_institutions_from_yaml(SAMPLE_YAML)

        with session_scope(engine) as session:
            stats = ingest_institutions(
                session, institutions, source="yaml:test"
            )
        assert stats.batches_created == 1
        assert stats.institution_versions_inserted == len(institutions)
        assert stats.tier_versions_inserted == sum(
            len(i.tiers) for i in institutions
        )

        with session_scope(engine) as session:
            stats = ingest_institutions(
                session, institutions, source="yaml:test"
            )
        assert stats.batches_created == 0
        assert stats.institution_versions_inserted == 0
        assert stats.tier_versions_inserted == 0
        assert stats.constraint_versions_inserted == 0
        assert stats.institution_versions_closed == 0


class TestSingleRateChangeDiff:
    def test_changing_one_tier_rate_writes_exactly_one_closed_and_one_new_tier(
        self, engine
    ):
        institutions = load_institutions_from_yaml(SAMPLE_YAML)
        with session_scope(engine) as session:
            ingest_institutions(session, institutions, source="yaml:test")
            tier_total_before = _count_total(session, TierVersion)
            tier_current_before = _count_current(session, TierVersion)
            inst_current_before = _count_current(session, InstitutionVersion)

        revised = []
        for inst in institutions:
            if inst.name == "Nu":
                first = inst.tiers[0]
                revised_first = Tier(
                    limit=first.limit,
                    rate=first.rate + 0.01,
                    constraints=first.constraints,
                )
                revised.append(
                    Institution(
                        name=inst.name,
                        tiers=(revised_first, *inst.tiers[1:]),
                        institution_type=inst.institution_type,
                        protection_limit=inst.protection_limit,
                    )
                )
            else:
                revised.append(inst)

        with session_scope(engine) as session:
            stats = ingest_institutions(session, revised, source="yaml:test")

        assert stats.batches_created == 1
        assert stats.tier_versions_inserted == 1
        assert stats.tier_versions_closed == 1
        assert stats.institution_versions_inserted == 0
        assert stats.constraint_versions_inserted == 0
        assert stats.constraint_versions_closed == 0

        with session_scope(engine) as session:
            assert _count_current(session, TierVersion) == tier_current_before
            assert _count_current(session, InstitutionVersion) == inst_current_before
            assert _count_total(session, TierVersion) == tier_total_before + 1


class TestTimeTravel:
    def test_as_of_returns_historical_snapshot(self, engine):
        institutions = load_institutions_from_yaml(SAMPLE_YAML)
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 2, 1, tzinfo=timezone.utc)

        with session_scope(engine) as session:
            ingest_institutions(
                session, institutions, source="yaml:test", now=t0
            )

        new_inst = Institution(
            name="Nu",
            tiers=(
                Tier(
                    limit=25_000,
                    rate=0.20,
                    constraints=(
                        Constraint(
                            type="monthly_expense",
                            cost=1.0,
                            benefit="high_rate_tier",
                            condition_value=1.0,
                            active=True,
                        ),
                    ),
                ),
                Tier(limit=float("inf"), rate=0.0675),
            ),
            institution_type="sofipo",
        )
        revised = [new_inst if i.name == "Nu" else i for i in institutions]

        with session_scope(engine) as session:
            ingest_institutions(session, revised, source="yaml:test", now=t1)

        with session_scope(engine) as session:
            current = {i.name: i for i in load_institutions_from_db(session)}
            historical = {
                i.name: i
                for i in load_institutions_from_db(
                    session, as_of=t0 + timedelta(days=1)
                )
            }

        assert current["Nu"].tiers[0].rate == pytest.approx(0.20, abs=1e-9)
        assert historical["Nu"].tiers[0].rate == pytest.approx(0.13, abs=1e-9)


class TestYamlVsDbAllocateParity:
    def test_db_loaded_allocation_matches_yaml(self, engine):
        yaml_institutions = load_institutions_from_yaml(SAMPLE_YAML)
        with session_scope(engine) as session:
            ingest_institutions(
                session, yaml_institutions, source="yaml:test"
            )
            db_institutions = load_institutions_from_db(session)

        yaml_by_name = {i.name: i for i in yaml_institutions}
        db_by_name = {i.name: i for i in db_institutions}
        assert yaml_by_name.keys() == db_by_name.keys()

        for total in (1_000, 50_000, 250_000, 1_200_000):
            y = allocate(total=total, institutions=yaml_institutions)
            d = allocate(total=total, institutions=db_institutions)
            assert y.expected_return == pytest.approx(
                d.expected_return, rel=1e-9, abs=1e-6
            )
            assert y.total_allocated == pytest.approx(
                d.total_allocated, rel=1e-9, abs=1e-6
            )


class TestDeactivateMissing:
    def test_missing_institution_is_closed_only_when_flag_set(self, engine):
        institutions = load_institutions_from_yaml(SAMPLE_YAML)
        with session_scope(engine) as session:
            ingest_institutions(session, institutions, source="yaml:test")

        partial = [i for i in institutions if i.name != "Mifel"]

        with session_scope(engine) as session:
            stats = ingest_institutions(
                session,
                partial,
                source="yaml:test",
                deactivate_missing=False,
            )
        assert stats.deactivated_institutions == 0

        with session_scope(engine) as session:
            current_names = {
                i.name for i in load_institutions_from_db(session)
            }
        assert "Mifel" in current_names

        with session_scope(engine) as session:
            stats = ingest_institutions(
                session,
                partial,
                source="yaml:test",
                deactivate_missing=True,
            )
        assert stats.deactivated_institutions == 1
        assert stats.batches_created == 1

        with session_scope(engine) as session:
            current_names = {
                i.name for i in load_institutions_from_db(session)
            }
        assert "Mifel" not in current_names


class TestRegulatoryRules:
    def test_round_trip_and_idempotent(self, engine):
        rules = load_regulatory_rules_from_yaml(RULES_YAML)

        with session_scope(engine) as session:
            stats = ingest_regulatory_rules(session, rules, source="yaml:test")
        assert stats.batches_created == 1
        assert stats.rule_versions_inserted == 1
        assert stats.rule_versions_closed == 0

        with session_scope(engine) as session:
            stats = ingest_regulatory_rules(session, rules, source="yaml:test")
        assert stats.batches_created == 0
        assert stats.rule_versions_inserted == 0

        with session_scope(engine) as session:
            loaded = load_regulatory_rules_from_db(session, country=rules.country)

        assert loaded == rules

    def test_changed_field_creates_new_version(self, engine):
        rules = load_regulatory_rules_from_yaml(RULES_YAML)
        with session_scope(engine) as session:
            ingest_regulatory_rules(session, rules, source="yaml:test")

        from dataclasses import replace

        bumped = replace(
            rules, inflation_proxy_annual=rules.inflation_proxy_annual + 0.001
        )

        with session_scope(engine) as session:
            stats = ingest_regulatory_rules(session, bumped, source="yaml:test")
        assert stats.rule_versions_inserted == 1
        assert stats.rule_versions_closed == 1
        assert stats.batches_created == 1

        with session_scope(engine) as session:
            loaded = load_regulatory_rules_from_db(session)
        assert loaded == bumped


class TestChangeBatchAudit:
    def test_each_change_writes_a_distinct_batch(self, engine):
        institutions = load_institutions_from_yaml(SAMPLE_YAML)
        with session_scope(engine) as session:
            ingest_institutions(
                session, institutions, source="yaml:first", note="first"
            )

        revised = list(institutions)
        for i, inst in enumerate(revised):
            if inst.name == "Nu":
                first = inst.tiers[0]
                revised[i] = Institution(
                    name=inst.name,
                    tiers=(
                        Tier(
                            limit=first.limit,
                            rate=first.rate + 0.005,
                            constraints=first.constraints,
                        ),
                        *inst.tiers[1:],
                    ),
                    institution_type=inst.institution_type,
                )

        with session_scope(engine) as session:
            ingest_institutions(
                session, revised, source="yaml:second", note="second"
            )

        with session_scope(engine) as session:
            batches = list(session.execute(select(ChangeBatch)).scalars())
        sources = sorted(b.source for b in batches)
        notes = sorted([b.note for b in batches])
        assert len(batches) == 2
        assert sources == ["yaml:first", "yaml:second"]
        assert notes == ["first", "second"]


class TestTierRateHistory:
    def test_load_recent_tier_rate_changes_after_rate_bump(self, engine):
        institutions = load_institutions_from_yaml(SAMPLE_YAML)
        nu_before = next(i for i in institutions if i.name == "Nu")
        r0 = nu_before.tiers[0].rate

        with session_scope(engine) as session:
            ingest_institutions(session, institutions, source="yaml:v1")

        revised = []
        for inst in institutions:
            if inst.name == "Nu":
                first = inst.tiers[0]
                revised.append(
                    Institution(
                        name=inst.name,
                        tiers=(
                            Tier(
                                limit=first.limit,
                                rate=first.rate + 0.01,
                                constraints=first.constraints,
                            ),
                            *inst.tiers[1:],
                        ),
                        institution_type=inst.institution_type,
                    )
                )
            else:
                revised.append(inst)

        with session_scope(engine) as session:
            ingest_institutions(session, revised, source="yaml:v2")

        with session_scope(engine) as session:
            events = load_recent_tier_rate_changes(session, limit=50)

        assert events

        def _utc(d: datetime) -> datetime:
            if d.tzinfo is None:
                return d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)

        vigencias = [_utc(e.effective_from) for e in events]
        assert vigencias == sorted(vigencias, reverse=True)

        nu_ev = next(
            e
            for e in events
            if e.institution_name == "Nu" and e.tier_index == 0
        )
        assert abs(nu_ev.old_rate - r0) < 1e-9
        assert abs(nu_ev.new_rate - (r0 + 0.01)) < 1e-9
        assert nu_ev.source == "yaml:v2"
