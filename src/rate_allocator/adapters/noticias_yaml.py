"""Curated YAML source for rate-change announcements (noticias section)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class YamlCambio:
    """One tier's rate change within a noticias entry."""

    tier_display: str
    old_rate: float
    new_rate: float


@dataclass(frozen=True)
class YamlNoticiaEntry:
    """One grouped announcement: institution + effective date + narrative + tier changes."""

    institution: str
    effective_from: datetime
    applied_at: datetime
    descripcion: str
    cambios: tuple[YamlCambio, ...]
    source: str


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "T" in s or s.count(":") >= 2:
            dt = datetime.fromisoformat(s)
        else:
            d = date.fromisoformat(s)
            dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _parse_cambios(raw: dict) -> list[YamlCambio]:
    """Parse cambios list from a grouped entry, or synthesize from flat entry."""
    if "cambios" in raw and isinstance(raw["cambios"], list):
        out = []
        for c in raw["cambios"]:
            if not isinstance(c, dict):
                continue
            tier_raw = c.get("tier")
            try:
                tier_disp = str(int(tier_raw)) if tier_raw is not None else "—"
            except (TypeError, ValueError):
                tier_disp = str(tier_raw).strip() or "—"
            try:
                old_r = float(c["old_rate"])
                new_r = float(c["new_rate"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append(YamlCambio(tier_display=tier_disp, old_rate=old_r, new_rate=new_r))
        return out

    # Backward-compat: flat entry with old_rate/new_rate directly on the row
    try:
        old_r = float(raw["old_rate"])
        new_r = float(raw["new_rate"])
    except (KeyError, TypeError, ValueError):
        return []
    tier_raw = raw.get("tier") if raw.get("tier") is not None else raw.get("tier_index")
    try:
        tier_disp = str(int(tier_raw)) if tier_raw is not None else "—"
    except (TypeError, ValueError):
        tier_disp = str(tier_raw).strip() or "—"
    return [YamlCambio(tier_display=tier_disp, old_rate=old_r, new_rate=new_r)]


def load_noticias_yaml(path: Path) -> list[YamlNoticiaEntry]:
    """Load entries from a YAML file; return an empty list if missing or invalid."""
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return []
    if not doc:
        return []
    raw_list = doc.get("entries")
    if raw_list is None and isinstance(doc, list):
        raw_list = doc
    if not isinstance(raw_list, list):
        return []

    out: list[YamlNoticiaEntry] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("institution") or raw.get("institution_name") or "").strip()
        if not name:
            continue
        ef = _parse_ts(raw.get("effective_from") or raw.get("vigente_desde"))
        if ef is None:
            continue
        ap = _parse_ts(raw.get("applied_at") or raw.get("fecha_aplicada")) or ef
        descripcion = str(raw.get("descripcion") or raw.get("note") or "").strip()
        src = str(raw.get("source") or "noticias.yaml").strip() or "—"
        cambios = _parse_cambios(raw)
        if not cambios:
            continue
        out.append(YamlNoticiaEntry(
            institution=name,
            effective_from=ef,
            applied_at=ap,
            descripcion=descripcion,
            cambios=tuple(cambios),
            source=src,
        ))
    return out


__all__ = ["YamlCambio", "YamlNoticiaEntry", "load_noticias_yaml"]
