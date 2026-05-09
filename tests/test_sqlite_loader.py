"""SQLite adapter must round-trip YAML snapshot institutions."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE1 = REPO_ROOT / "data" / "sample1.yaml"


def test_seed_and_load_equals_yaml(tmp_path):
    pytest.importorskip("yaml")

    db_path = tmp_path / "rates.db"

    from rate_allocator.adapters.sqlite_loader import (
        load_institutions_from_sqlite,
        seed_rates_database,
    )
    from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

    seed_rates_database(SAMPLE1, db_path)
    expected = load_institutions_from_yaml(SAMPLE1)
    got = load_institutions_from_sqlite(db_path)

    assert [i.name for i in got] == [i.name for i in expected]
    assert got == expected


def test_raises_when_db_missing(tmp_path):
    from rate_allocator.adapters.sqlite_loader import load_institutions_from_sqlite

    missing = tmp_path / "nope.db"
    with pytest.raises(FileNotFoundError, match="SQLite DB not found"):
        load_institutions_from_sqlite(missing)
