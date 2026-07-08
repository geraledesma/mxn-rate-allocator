"""Tests for optional YAML-backed Noticias rows."""

from __future__ import annotations

from pathlib import Path

import pytest

from rate_allocator.adapters.noticias_yaml import YamlNoticiaEntry, load_noticias_yaml


def test_load_noticias_yaml_missing(tmp_path: Path) -> None:
    assert load_noticias_yaml(tmp_path / "nope.yaml") == []


def test_load_noticias_yaml_flat_entry(tmp_path: Path) -> None:
    """Backward-compat: flat entry with old_rate/new_rate directly (no cambios list)."""
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
    assert len(r.cambios) == 1
    assert r.cambios[0].tier_display == "2"
    assert r.cambios[0].old_rate == pytest.approx(0.11)
    assert r.cambios[0].new_rate == pytest.approx(0.09)
    assert r.effective_from.year == 2026
    assert r.applied_at.month == 4


def test_load_noticias_yaml_grouped_entry(tmp_path: Path) -> None:
    """New grouped format with descripcion and cambios list."""
    p = tmp_path / "n.yaml"
    p.write_text(
        """
entries:
  - institution: TestBank
    effective_from: "2026-04-01"
    descripcion: Subió tramo 1, bajó tramo 2.
    cambios:
      - tier: 1
        old_rate: 0.09
        new_rate: 0.13
      - tier: 2
        old_rate: 0.09
        new_rate: 0.07
""",
        encoding="utf-8",
    )
    rows = load_noticias_yaml(p)
    assert len(rows) == 1
    r = rows[0]
    assert r.institution == "TestBank"
    assert r.descripcion == "Subió tramo 1, bajó tramo 2."
    assert len(r.cambios) == 2
    assert r.cambios[0].tier_display == "1"
    assert r.cambios[0].new_rate == pytest.approx(0.13)
    assert r.cambios[1].tier_display == "2"
    assert r.cambios[1].new_rate == pytest.approx(0.07)


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
