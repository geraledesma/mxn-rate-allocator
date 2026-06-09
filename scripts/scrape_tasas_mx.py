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

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "data" / "scraped_live.yaml"
TASAS_MX_URL = "https://www.tasas.mx/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; rate-allocator-scraper/1.0)"}

# Known tier structures per institution.
# rates are placeholders — they get replaced by scraped values.
# limits are in MXN. "inf" means no cap.
# Sourced from institution pages + pitch deck research (June 2026).
TIER_STRUCTURES: dict[str, dict] = {
    "DiDi": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": 10_000, "rate_key": "vista"},
            {"limit": "inf",  "rate": 0.075},
        ],
    },
    "Revolut": {
        "institution_type": "banco",
        "tiers": [
            {"limit": 25_000,    "rate_key": "vista"},
            {"limit": 1_000_000, "rate": 0.075},
            {"limit": "inf",     "rate": 0.05},
        ],
    },
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
    "Mercado Pago": {
        "institution_type": "none",
        "tiers": [
            {
                "limit": 25_000,  # 13% applies to first $25k — source: app UI (June 2026, T&C not confirmed)
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
            {"limit": "inf", "rate": 0.06},  # ~6% rest — source: app UI (June 2026, T&C not confirmed)
        ],
    },
    "Openbank": {
        "institution_type": "banco",
        "tiers": [
            {"limit": 40_000,    "rate_key": "vista"},
            {"limit": 1_000_000, "rate": 0.073},
            {"limit": "inf",     "rate": 0.07},
        ],
    },
    "Klar": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate_key": "vista"},
        ],
    },
    "Supertasas": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate_key": "vista"},
        ],
    },
    "BONDDIA": {
        "institution_type": "none",
        "tiers": [
            {"limit": "inf", "rate_key": "vista"},
        ],
    },
    "Cetes": {
        "institution_type": "none",
        "tiers": [
            {"limit": "inf", "rate_key": "1mes"},
        ],
    },
    "Finsus": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate_key": "1mes"},
        ],
    },
    "Stori": {
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate_key": "1mes"},
        ],
    },
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
        "# Auto-generated by scripts/scrape_tasas_mx.py\n"
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
        import subprocess
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "ingest_yaml.py"), str(args.output),
             "--init-schema", "--note", "scraped from tasas.mx"],
            cwd=REPO_ROOT,
        )
        return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
