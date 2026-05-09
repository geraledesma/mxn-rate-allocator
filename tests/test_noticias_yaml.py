"""Tests for optional YAML-backed Noticias rows."""

from __future__ import annotations

from pathlib import Path

import pytest

from rate_allocator.adapters.noticias_yaml import YamlNoticiaEntry, load_noticias_yaml


def test_load_noticias_yaml_missing(tmp_path: Path) -> None:
    assert load_noticias_yaml(tmp_path / "nope.yaml") == []


def test_load_noticias_yaml_entries(tmp_path: Path) -> None:
    p = tmp_path / "n.yaml"
    p.write_text(
        """
entries:
  - institution: TestBank
    tier: 2
    old_rate: 0.11
    new_rate: 0.09
    effective_from: "2026-04-01"
    applied_at: "2026-04-02T15:30:00"
    source: unit
    note: ok
""",
        encoding="utf-8",
    )
    rows = load_noticias_yaml(p)
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, YamlNoticiaEntry)
    assert r.institution == "TestBank"
    assert r.tier_display == "2"
    assert r.old_rate == pytest.approx(0.11)
    assert r.new_rate == pytest.approx(0.09)
    assert r.effective_from.year == 2026
    assert r.applied_at.month == 4


def test_load_noticias_yaml_skips_invalid(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        """
entries:
  - institution: ""
    tier: 1
    old_rate: 0.1
    new_rate: 0.2
    effective_from: "2026-01-01"
""",
        encoding="utf-8",
    )
    assert load_noticias_yaml(p) == []
