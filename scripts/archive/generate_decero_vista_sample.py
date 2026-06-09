#!/usr/bin/env python3
"""Fetch De Cero al Infinito inversiones.json and write Vista-only institutions YAML."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "https://deceroalinfinito.com/data/inversiones.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "data" / "sample3.yaml"

_TIPO_TO_INSTITUTION_TYPE: dict[str, str] = {
    "banco": "banco",
    "sofipo": "sofipo",
}


def _institution_type(raw: Any) -> str:
    if raw is None or not isinstance(raw, str):
        return "none"
    key = raw.strip().casefold()
    return _TIPO_TO_INSTITUTION_TYPE.get(key, "none")


def _vista_percent(record: dict[str, Any]) -> float | None:
    plazos = record.get("plazos")
    if not isinstance(plazos, dict):
        return None
    v = plazos.get("Vista")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    if x != x or abs(x) == float("inf"):
        return None
    return x


def _vista_footnote(record: dict[str, Any]) -> str | None:
    """Text from the Vista column — JSON field notas.Vista only."""
    notas = record.get("notas")
    if not isinstance(notas, dict):
        return None
    v = notas.get("Vista")
    if not isinstance(v, str) or not v.strip():
        return None
    return v.strip()


def _disclosure_text_from_notas(record: dict[str, Any]) -> str | None:
    """Merge Vista + other notas strings (De Cero splits footnotes across keys, e.g. Condiciones, 12 meses)."""
    notas = record.get("notas")
    if not isinstance(notas, dict):
        return None
    mem = _membership_fee_constraint(record)
    skip_nombre_text = mem is not None
    pieces: list[str] = []
    v = notas.get("Vista")
    if isinstance(v, str) and v.strip():
        pieces.append(v.strip())
    for key in ("nombre", "Condiciones"):
        if key == "nombre" and skip_nombre_text:
            continue
        val = notas.get(key)
        if isinstance(val, str) and val.strip():
            t = val.strip()
            if t not in pieces:
                pieces.append(t)
    for key in sorted(notas.keys()):
        if key in ("Vista", "nombre", "Condiciones"):
            continue
        val = notas.get(key)
        if isinstance(val, str) and val.strip():
            t = val.strip()
            if t not in pieces:
                pieces.append(t)
    if not pieces:
        return None
    return "\n\n".join(pieces)


def _mx_amount_digits(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s))


def _try_vista_ladder_openbank(notas_text: str) -> list[dict[str, Any]] | None:
    """De $40k … $1M del 7.3% y 7% — same tier shape as data/sample1.yaml OpenBank."""
    m1 = re.search(
        r"(\d+(?:\.\d+)?)%[^\n\$]*topada hasta \$(\d[\d,]*)\s*MXN",
        notas_text,
        re.I,
    )
    m2 = re.search(
        r"a \$1,000,000[^\n%]*del (\d+(?:\.\d+)?)%\s*y\s*(\d+(?:\.\d+)?)%\s*para montos mayores",
        notas_text,
        re.I,
    )
    if not m1 or not m2:
        return None
    r1 = round(float(m1.group(1)) / 100.0, 6)
    cap = _mx_amount_digits(m1.group(2))
    r2 = round(float(m2.group(1)) / 100.0, 6)
    r3 = round(float(m2.group(2)) / 100.0, 6)
    if cap <= 0:
        return None
    return [
        {"limit": cap, "rate": r1},
        {"limit": 1_000_000, "rate": r2},
        {"limit": "inf", "rate": r3},
    ]


def _try_vista_ladder_revolut(notas_text: str, headline_rate: float) -> list[dict[str, Any]] | None:
    """$25k @ headline … $1M @ midpoint of 7–7.5% … tail 5% — same shape as data/sample1.yaml Revolut."""
    m1 = re.search(
        r"(\d+(?:\.\d+)?)%[^\n\$]*topada hasta \$(\d[\d,]*)\s*MXN",
        notas_text,
        re.I,
    )
    m_mid = re.search(
        r"entre el (\d+(?:\.\d+)?)%\s*y\s*(\d+(?:\.\d+)?)%",
        notas_text,
        re.I,
    )
    m_tail = re.search(r"(\d+(?:\.\d+)?)%\s*para montos mayores", notas_text, re.I)
    if not m1 or not m_mid or not m_tail:
        return None
    cap = _mx_amount_digits(m1.group(2))
    lo = float(m_mid.group(1))
    hi = float(m_mid.group(2))
    r_mid = round(((lo + hi) / 2.0) / 100.0, 6)
    r_tail = round(float(m_tail.group(1)) / 100.0, 6)
    if cap <= 0:
        return None
    return [
        {"limit": cap, "rate": headline_rate},
        {"limit": 1_000_000, "rate": r_mid},
        {"limit": "inf", "rate": r_tail},
    ]


def _try_vista_ladder_two_band_topada_mayores(notas_text: str) -> list[dict[str, Any]] | None:
    """NU, Didi, etc.: high rate to $cap, 'Montos mayores ofrecen R%' above (sample1 Nu-shaped two bands)."""
    m1 = re.search(
        r"(\d+(?:\.\d+)?)%[^\n\$]*topada hasta \$(\d[\d,]*)\s*MXN",
        notas_text,
        re.I,
    )
    m2 = re.search(
        r"montos mayores\s+ofrecen\s+(\d+(?:\.\d+)?)%",
        notas_text,
        re.I,
    )
    if not m1 or not m2:
        return None
    r_high = round(float(m1.group(1)) / 100.0, 6)
    cap = _mx_amount_digits(m1.group(2))
    r_low = round(float(m2.group(1)) / 100.0, 6)
    if cap <= 0 or abs(r_high - r_low) < 1e-9:
        return None
    return [
        {"limit": cap, "rate": r_high},
        {"limit": "inf", "rate": r_low},
    ]


def _try_named_vista_balance_ladder(
    record: dict[str, Any],
    headline_rate: float,
    mem: dict[str, Any] | None,
    disclosure_dict: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Openbank / Revolut / two-band notas (NU, Didi, …): multi-tranche Vista from De Cero text."""
    name = (record.get("nombre") or "").strip().casefold()
    text = _disclosure_text_from_notas(record) or ""
    if not text.strip():
        return None
    tiers_template: list[dict[str, Any]] | None = None
    if name == "openbank":
        tiers_template = _try_vista_ladder_openbank(text)
    elif name == "revolut":
        tiers_template = _try_vista_ladder_revolut(text, headline_rate)
    if tiers_template is None:
        tiers_template = _try_vista_ladder_two_band_topada_mayores(text)
    if tiers_template is None:
        return None
    tiers_list = [dict(t) for t in tiers_template]
    if disclosure_dict is not None:
        tiers_list[0].setdefault("constraints", []).append(disclosure_dict)
    if mem is not None:
        tiers_list[0].setdefault("constraints", []).insert(0, mem)
    return tiers_list


def _try_mifel_cuenta_digital_vista_tiers(
    headline_rate: float, record: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Mifel Vista note: min balance + max interest-bearing balance → unlock tranche like data/sample1.yaml."""
    name = (record.get("nombre") or "").casefold()
    if "mifel" not in name or "digital" not in name:
        return None
    merged = _disclosure_text_from_notas(record) or ""
    low = merged.casefold()
    if "500" not in merged or "100" not in merged:
        return None
    if not (
        "monto" in low or "mínimo" in low or "minimo" in low or "máximo" in low or "maximo" in low
    ):
        return None
    return [
        {
            "limit": 100,
            "rate": 0.0,
            "rate_comment": "Required unlock tranche",
        },
        {
            "limit": "500_000",
            "rate": headline_rate,
        },
        {"limit": "inf", "rate": 0.0},
    ]


def _membership_fee_constraint(record: dict[str, Any]) -> dict[str, Any] | None:
    """De Cero sometimes puts the Vista-row fee under notas.nombre (e.g. Plata Plus $99+IVA)."""
    notas = record.get("notas")
    if not isinstance(notas, dict):
        return None
    raw = notas.get("nombre")
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.casefold()
    if "mensualidad" not in s or "iva" not in s:
        return None
    if "99" not in raw:
        return None
    note = raw.strip()
    return {
        "type": "monthly_expense",
        "cost": 114.84,
        "benefit": "membership_plan",
        "active": True,
        "constraint_condition": note,
        "benefit_condition": note,
    }


def load_records(*, url: str | None, input_path: Path | None) -> list[dict[str, Any]]:
    if input_path is not None:
        raw = input_path.read_bytes()
    else:
        if not url:
            raise ValueError("url required when --input is not set")
        req = Request(url, headers={"User-Agent": "rate-allocator-generate-decero-vista/1.0"})
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("expected JSON array at top level")
    return data


def build_institutions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        name = rec.get("nombre")
        if not isinstance(name, str) or not name.strip():
            continue
        pct = _vista_percent(rec)
        if pct is None:
            continue
        rate = round(pct / 100.0, 6)
        mem = _membership_fee_constraint(rec)
        foot = _disclosure_text_from_notas(rec)
        disclosure_dict: dict[str, Any] | None = None
        if foot is not None:
            disclosure_dict = {
                "type": "disclosure",
                "cost": 0,
                "active": False,
                "constraint_condition": foot,
                "benefit_condition": foot,
            }

        mifel_tiers = _try_mifel_cuenta_digital_vista_tiers(rate, rec)
        if mifel_tiers is not None:
            tiers_list = [dict(t) for t in mifel_tiers]
            if disclosure_dict is not None:
                tiers_list[1]["constraints"] = [disclosure_dict]
            if mem is not None:
                tiers_list[0].setdefault("constraints", []).insert(0, mem)
            out.append(
                {
                    "name": name.strip(),
                    "institution_type": _institution_type(rec.get("tipo")),
                    "tiers": tiers_list,
                }
            )
            continue

        ladder_tiers = _try_named_vista_balance_ladder(rec, rate, mem, disclosure_dict)
        if ladder_tiers is not None:
            out.append(
                {
                    "name": name.strip(),
                    "institution_type": _institution_type(rec.get("tipo")),
                    "tiers": ladder_tiers,
                }
            )
            continue

        tier: dict[str, Any] = {
            "limit": "inf",
            "rate": rate,
        }
        constraints: list[dict[str, Any]] = []
        if mem is not None:
            constraints.append(mem)
        if disclosure_dict is not None:
            constraints.append(disclosure_dict)
        if constraints:
            tier["constraints"] = constraints
        out.append(
            {
                "name": name.strip(),
                "institution_type": _institution_type(rec.get("tipo")),
                "tiers": [tier],
            }
        )
    out.sort(key=lambda x: x["name"].casefold())
    return out


def _fmt_rate(rate: float) -> str:
    if rate == 0.0:
        return "0.0"
    s = f"{rate:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_limit_yaml(lim: Any) -> str:
    if lim == "inf":
        return "inf"
    if isinstance(lim, str):
        return lim
    n = int(lim)
    if n >= 1000:
        return f"{n:,}".replace(",", "_")
    return str(n)


def _fmt_cost(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _yaml_scalar_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def emit_institutions_yaml(institutions: list[dict[str, Any]]) -> str:
    lines: list[str] = ["institutions:\n"]
    for inst in institutions:
        lines.append(f"  - name: {_yaml_scalar_str(inst['name'])}\n")
        lines.append(f"    institution_type: {inst['institution_type']}\n")
        lines.append("    tiers:\n")
        for tier in inst["tiers"]:
            lines.append(f"      - limit: {_fmt_limit_yaml(tier['limit'])}\n")
            rate_line = f"        rate: {_fmt_rate(float(tier['rate']))}"
            rc = tier.get("rate_comment")
            if rc:
                rate_line += f"  # {rc}"
            lines.append(rate_line + "\n")
            cons = tier.get("constraints") or []
            if cons:
                lines.append("        constraints:\n")
                for c in cons:
                    ctype = c["type"]
                    if ctype == "disclosure":
                        lines.append("          - type: disclosure\n")
                        lines.append(f"            cost: {int(c['cost'])}\n")
                        lines.append(f"            active: {str(c['active']).lower()}\n")
                        lines.append(
                            f"            constraint_condition: {_yaml_scalar_str(c['constraint_condition'])}\n"
                        )
                        lines.append(
                            f"            benefit_condition: {_yaml_scalar_str(c['benefit_condition'])}\n"
                        )
                    elif ctype == "monthly_expense":
                        lines.append("          - type: monthly_expense\n")
                        cost = float(c["cost"])
                        cost_line = f"            cost: {_fmt_cost(cost)}"
                        if abs(cost - 114.84) < 1e-6:
                            cost_line += "  # 99 + IVA (16%)"
                        lines.append(cost_line + "\n")
                        lines.append(f"            benefit: {c['benefit']}\n")
                        lines.append(f"            active: {str(c['active']).lower()}\n")
                        cc = c.get("constraint_condition")
                        bc = c.get("benefit_condition")
                        if cc is not None:
                            lines.append(
                                f"            constraint_condition: {_yaml_scalar_str(cc)}\n"
                            )
                        if bc is not None:
                            lines.append(
                                f"            benefit_condition: {_yaml_scalar_str(bc)}\n"
                            )
                    else:
                        raise ValueError(f"unknown constraint type in emitter: {ctype!r}")
    return "".join(lines)


def _yaml_header(snapshot_iso: str, source_url: str) -> str:
    return f"""# Vista (overnight) tier rates: annual nominal % from source, stored as decimals for allocate().
# periods_per_year=365 with horizon_years matches daily-style compounding used elsewhere in this repo.
# Canonical path in this repo: data/sample3.yaml (this file; regenerate with scripts/generate_decero_vista_sample.py).
#
# WORK IN PROGRESS — auto-sourced from a third-party JSON feed and heuristically mapped to tiers. Not audited
# for production. Do not treat as a source of truth until you finish review and curation.
# Once you have a finalized institutions file, stop using this snapshot and load your confirmed YAML instead.
#
# Source: {source_url}
# Snapshot (UTC): {snapshot_iso}
#
# Mifel (cuenta digital): min $100 / max $500k for interest → three tiers like data/sample1.yaml Mifel.
# Openbank / Revolut: explicit three-band copy in notas.Vista (rates from De Cero; Revolut middle = avg 7–7.5%).
# Two-band "topada … / Montos mayores ofrecen …" (NU, Didi, …): sample1 Nu–shaped split; rates from the note.
# Other institutions: single headline Vista tier plus disclosures unless you extend parsers.
#
# Footnotes: we merge notas.Vista plus other string notas (nombre, Condiciones, plazo keys like "12 meses")
# into one inactive disclosure — De Cero often puts Vista-only text in notas.Vista but leaves related copy
# in other keys (same gap class as Plata Plus fee living under notas.nombre).
# Exception: notas.nombre matching $99+IVA mensualidad becomes monthly_expense 114.84 (see sample1.yaml);
# that sentence is omitted from the disclosure blob to avoid triplication (it stays on the fee row).
# Headline plazos.Vista still drives the tier rate; footnotes do not add tier splits unless you edit YAML.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="JSON endpoint URL")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help="Output YAML path",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Read JSON from this file instead of HTTP (same schema as --url)",
    )
    args = parser.parse_args()

    if args.input is not None and not args.input.is_file():
        raise SystemExit(f"--input is not a file: {args.input}")

    try:
        records = load_records(
            url=(args.url if args.input is None else None),
            input_path=args.input,
        )
    except (URLError, OSError, TimeoutError, ValueError) as e:
        raise SystemExit(f"failed to fetch or parse JSON: {e}") from e

    institutions = build_institutions(records)
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    body = emit_institutions_yaml(institutions)
    header = _yaml_header(snapshot, args.url)
    args.output.write_text(header + "\n" + body, encoding="utf-8")
    print(f"wrote {len(institutions)} institutions to {args.output}")


if __name__ == "__main__":
    main()
