"""Scrape current rates from tasas.mx and generate a YAML for ingest.

Fetches the main comparison table from tasas.mx (static HTML, no browser needed).
Merges scraped rates with known tier structures and writes data/scraped_live.yaml.

Usage:
    python scripts/scrape_tasas_mx.py               # writes data/scraped_live.yaml
    python scripts/scrape_tasas_mx.py --ingest       # also runs ingest_yaml
    python scripts/scrape_tasas_mx.py --dry-run      # print YAML, no file written
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = REPO_ROOT / "data" / "scraped_live.yaml"
TASAS_MX_URL = "https://www.tasas.mx/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; rate-allocator-scraper/1.0)"}

# Known tier structures per institution.
# rates are placeholders — they get replaced by scraped values.
# limits are in MXN. "inf" means no cap.
# Sourced from institution pages + pitch deck research (June 2026).
TIER_STRUCTURES: dict[str, dict] = {
    # source: https://web.didiglobal.com/mx/jpsofiexpress/didi-cuenta/
    # T&C contract: https://web.didiglobal.com/mx/didi-cuenta/contrato.pdf
    # Product: DiDi Cuenta — a la vista, daily returns. $10k limit confirmed Jan 2026.
    "DiDi": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": 10_000, "rate_key": "vista"},
            {"limit": "inf",  "rate": 0.075},
        ],
    },
    # source: https://www.revolut.com/es-MX/instant-access-savings/
    # Product: Rendimientos Diarios — a la vista, 24/7, no lock-up.
    # Rates: first $25k at vista rate; $25k-$1M and $1M+ are hardcoded from T&C Apr 2026.
    "Revolut": {
        "institution_type": "banco",
        "tiers": [
            {"limit": 25_000,    "rate_key": "vista"},
            {"limit": 1_000_000, "rate": 0.075},
            {"limit": "inf",     "rate": 0.05},
        ],
    },
    # source: https://cdn.nubank.com.br/MX/folleto-informativo-cuenta.pdf
    # Product: Cajita Turbo (a la vista) — requires ≥1 purchase per 30 days on Nu card.
    # Over $25k: 24/7 Cajita at ~6.75%, no conditions.
    "Nu": {
        "institution_type": "sofipo",
        "tiers": [
            {
                "limit": 25_000,
                "rate_key": "vista",
                "constraints": [
                    {
                        "type": "monthly_expense",
                        "cost": 1.0,
                        "benefit": "high_rate_tier",
                        "condition_value": 1.0,
                        "active": True,
                    }
                ],
            },
            {"limit": "inf", "rate": 0.0675},
        ],
    },
    # source: https://www.mercadopago.com.mx/ayuda/terminos-condiciones-beneficio_32110
    # Product: Dinero en Cuenta — a la vista, daily returns. Rate conditional on monthly spend.
    # First $25k: vista rate (requires ≥$3,000 monthly spend). Over $25k: ~6% no condition.
    "Mercado Pago": {
        "institution_type": "none",
        "tiers": [
            {
                "limit": 25_000,
                "rate_key": "vista",
                "constraints": [
                    {
                        "type": "monthly_expense",
                        "cost": 3_000.0,
                        "benefit": "high_rate_tier",
                        "condition_value": 3_000.0,
                        "active": True,
                    }
                ],
            },
            {"limit": "inf", "rate": 0.06},
        ],
    },
    # source: https://www.openbank.mx/cuenta-debito-open-plus
    # Product: Cuenta Débito Open+ — a la vista, Santander/IPAB. Rates from T&C Mar 2026.
    # First $40k: vista rate from tasas.mx. $40k-$1M and $1M+ hardcoded from T&C.
    "Openbank": {
        "institution_type": "banco",
        "tiers": [
            {"limit": 40_000,    "rate_key": "vista"},
            {"limit": 1_000_000, "rate": 0.073},
            {"limit": "inf",     "rate": 0.07},
        ],
    },
    # source: https://www.klar.mx/inversion (Fondo de Rendimiento Klar, flexible)
    # Product: Flexible investment (on-demand, no lock-up, no early-withdrawal penalty).
    # NOTE: 8.5% is for Klar Plus/Platino tier. Light tier earns less (~3-6%).
    # tasas.mx shows "vista" = 8.5% which corresponds to the flexible/on-demand tier.
    "Klar": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate_key": "vista"},
        ],
    },
    # source: https://crediclub.com.mx (supertasas.com redirects here)
    # Product: Cuenta de Ahorro a la Vista — Crediclub SFP. Only "vista" rate is in scope.
    # NOTA: Crediclub también ofrece plazos (7-364 días) con tasas más altas — EXCLUIDOS.
    "Supertasas": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate_key": "vista"},
        ],
    },
    # source: https://www.bmv.com.mx/es/fondos/BONDDIA-7407
    # Product: Fondo GBM de Instrumentos Gubernamentales — daily liquidity, a la vista.
    # Invests in short-term government securities. Returns calculated and paid daily.
    "BONDDIA": {
        "institution_type": "none",
        "tiers": [
            {"limit": "inf", "rate_key": "vista"},
        ],
    },
    # source: https://www.cetesdirecto.com / banxico.org.mx
    # Product: CETES 28 días — 28-day maturity ≤ 1 mes, qualifies per methodology.
    # tasas.mx shows CETES under "1mes" column (CETES 28 días ≈ 1 mes).
    "Cetes": {
        "institution_type": "none",
        "tiers": [
            {"limit": "inf", "rate_key": "1mes"},
        ],
    },
    # Finsus and Stori REMOVED from auto-scrape — their tasas.mx rates are ALL fixed-term
    # (no "vista" column). Their a la vista products are manually curated in
    # data/manual_additions.yaml with official T&C rates.
}

COLUMN_KEYS = ["vista", "7dias", "1mes", "3meses", "6meses", "1año"]


def fetch_rates() -> dict[str, dict[str, float | None]]:
    """Return {institution_name: {tenor: rate_float}} from tasas.mx table."""
    resp = requests.get(TASAS_MX_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("No table found on tasas.mx — page structure may have changed.")

    rates: dict[str, dict[str, float | None]] = {}
    for row in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8:
            continue
        name = cells[0]
        row_rates: dict[str, float | None] = {}
        for key, raw in zip(COLUMN_KEYS, cells[2:8]):
            row_rates[key] = _parse_rate(raw)
        rates[name] = row_rates

    return rates


def _parse_rate(raw: str) -> float | None:
    raw = raw.strip().replace("%", "")
    if raw == "-" or not raw:
        return None
    try:
        return round(float(raw) / 100, 6)
    except ValueError:
        return None


def build_yaml(scraped: dict[str, dict[str, float | None]]) -> dict:
    institutions = []

    for name, structure in TIER_STRUCTURES.items():
        inst_rates = scraped.get(name)
        if not inst_rates:
            print(f"  [SKIP] {name} not found in tasas.mx data", file=sys.stderr)
            continue

        tiers_out = []
        skipped = False
        for tier in structure["tiers"]:
            rate_key = tier.get("rate_key")
            if rate_key:
                rate = inst_rates.get(rate_key)
                if rate is None:
                    print(
                        f"  [WARN] {name}: rate_key '{rate_key}' is '-' on tasas.mx — skipping institution",
                        file=sys.stderr,
                    )
                    skipped = True
                    break
            else:
                rate = tier["rate"]

            tier_out: dict = {
                "limit": tier["limit"],
                "rate": rate,
            }
            if "constraints" in tier:
                tier_out["constraints"] = tier["constraints"]
            tiers_out.append(tier_out)

        if skipped or not tiers_out:
            continue

        institutions.append(
            {
                "name": name,
                "institution_type": structure["institution_type"],
                "tiers": tiers_out,
            }
        )
        print(f"  [OK]   {name}: top rate = {tiers_out[0]['rate']:.2%}", file=sys.stderr)

    return {"institutions": institutions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print YAML, do not write file.")
    parser.add_argument("--ingest", action="store_true", help="Run ingest_yaml after writing.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output YAML path.")
    args = parser.parse_args(argv)

    print("Fetching tasas.mx...", file=sys.stderr)
    scraped = fetch_rates()
    print(f"Found {len(scraped)} institutions.", file=sys.stderr)

    data = build_yaml(scraped)
    yaml_text = (
        "# Auto-generated by rate-scrape CLI\n"
        "# Source: https://www.tasas.mx/\n"
        "# Tier limits are manually curated; rates are scraped.\n\n"
        + yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    )

    if args.dry_run:
        print(yaml_text)
        return 0

    args.output.write_text(yaml_text, encoding="utf-8")
    print(f"\nWrote {len(data['institutions'])} institutions to {args.output}", file=sys.stderr)

    if args.ingest:
        from rate_allocator.cli.ingest import main as _ingest_main
        return _ingest_main([str(args.output), "--init-schema", "--note", "scraped from tasas.mx"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
