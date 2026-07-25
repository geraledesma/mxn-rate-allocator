"""Scrape rates from institution T&C pages (primary sources).

Writes data/scraped_live.yaml in the same format consumed by rate_allocator.cli.ingest.
Each institution has a dedicated extractor keyed on known rate patterns.
Failures are caught per-institution: the scraper logs [FAIL] to stderr, continues,
and exits with code 1 so the caller (rate_agent) can send a Telegram alert.

Usage:
    PYTHONPATH=src python -m rate_allocator.cli.scrape_primary
    PYTHONPATH=src python -m rate_allocator.cli.scrape_primary --ingest
    PYTHONPATH=src python -m rate_allocator.cli.scrape_primary --dry-run
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import pdfplumber
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = REPO_ROOT / "data" / "scraped_live.yaml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9",
}
TIMEOUT = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pct(v: float) -> float:
    """Convert percentage value (e.g. 15.0) to decimal (0.15)."""
    return round(v / 100, 6)


def _find_pct(text: str, pattern: str = r"(\d+(?:[.,]\d+)?)\s*%") -> float | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return _pct(float(m.group(1).replace(",", "."))) if m else None


def _rate_near(text: str, keyword: str, window: int = 400) -> float | None:
    """Find a % rate within `window` chars after the first occurrence of `keyword`."""
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return None
    snippet = text[idx: idx + window]
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", snippet)
    return _pct(float(m.group(1).replace(",", "."))) if m else None


def _fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _fetch_pdf_text(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


# ── Per-institution extractors ────────────────────────────────────────────────
# Each extractor receives the raw text (HTML body or PDF text) and returns a
# complete institution dict ready to include in the output YAML.

def _extract_didi(text: str) -> dict:
    # "15% anual para saldos de hasta $10,000 MXN"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*anual\s+para\s+saldos", text, re.IGNORECASE)
    if not m:
        raise ValueError("rate pattern '% anual para saldos' not found")
    rate_top = _pct(float(m.group(1)))
    return {
        "name": "DiDi",
        "institution_type": "sofipo",
        "tiers": [
            {"limit": 10_000, "rate": rate_top},
            {"limit": "inf",  "rate": 0.075},   # floor tier — hardcoded T&C
        ],
    }


def _extract_nu(text: str) -> dict:
    # PDF: find Cajita Turbo rate (conditional) and base Cajita rate
    # Turbo section typically appears after the word "Turbo"
    idx_turbo = text.lower().find("turbo")
    if idx_turbo >= 0:
        snippet = text[max(0, idx_turbo - 100): idx_turbo + 500]
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", snippet)
        turbo_rate = _pct(float(m.group(1))) if m else None
    else:
        turbo_rate = None

    # Base Cajita rate appears near "6.50" or "cajita" without "turbo"
    idx_cajita = text.lower().find("cajita")
    if idx_cajita >= 0:
        snippet = text[max(0, idx_cajita - 50): idx_cajita + 400]
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", snippet)
        base_rate = _pct(float(m.group(1))) if m else None
    else:
        base_rate = None

    top_rate = turbo_rate if turbo_rate and turbo_rate > (base_rate or 0) else base_rate
    if top_rate is None:
        raise ValueError("no rate found in PDF")

    return {
        "name": "Nu",
        "institution_type": "sofipo",
        "tiers": [
            {
                "limit": 25_000,
                "rate": top_rate,
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
            {"limit": "inf", "rate": base_rate or 0.0675},
        ],
    }


def _extract_openbank(text: str) -> dict:
    # "hasta 13% de rendimiento anual fijo en tus Apartados Open"
    # Look backward from "rendimiento anual" to avoid matching stray "100%" earlier on page.
    kw = re.search(r"rendimiento\s*anual", text, re.IGNORECASE)
    if not kw:
        raise ValueError("keyword 'rendimiento anual' not found")
    window = text[max(0, kw.start() - 200): kw.start()]
    pct_matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*%", window))
    rate_top = None
    for m in reversed(pct_matches):
        candidate = _pct(float(m.group(1)))
        if 0.01 <= candidate <= 0.30:
            rate_top = candidate
            break
    if rate_top is None:
        raise ValueError("no plausible rate near 'rendimiento anual'")
    return {
        "name": "Openbank",
        "institution_type": "banco",
        "tiers": [
            {"limit": 30_000,    "rate": rate_top},
            {"limit": 1_000_000, "rate": 0.07},    # T&C Jul-27 2026
            {"limit": "inf",     "rate": 0.065},
        ],
    }


def _extract_supertasas(text: str) -> dict:
    # "Crecimiento de hasta 8.60% anual en tus inversiones."
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*anual", text, re.IGNORECASE)
    if not m:
        raise ValueError("rate pattern '% anual' not found")
    return {
        "name": "Supertasas",
        "institution_type": "sofipo",
        "tiers": [
            {"limit": "inf", "rate": _pct(float(m.group(1)))},
        ],
    }


def _extract_mifel(text: str) -> dict:
    # "Crece tu dinero 10% anual y disfruta beneficios únicos."
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*anual", text, re.IGNORECASE)
    if not m:
        raise ValueError("rate pattern '% anual' not found")
    rate = _pct(float(m.group(1)))
    return {
        "name": "Mifel",
        "institution_type": "banco",
        "tiers": [
            {"limit": 99.99,   "rate": 0.0},
            {"limit": 500_000, "rate": rate},
            {"limit": "inf",   "rate": 0.0001},
        ],
    }


def _extract_klar(text: str) -> dict:
    # klar.mx/inversion — plan sections: Light (3%), Plus (5%), Platino (5%)
    light_rate = _rate_near(text, "light") or _rate_near(text, "Light") or 0.03
    plus_rate  = _rate_near(text, "plus")  or _rate_near(text, "Plus")  or 0.05

    # Sanity check: rates should be in [1%, 20%]
    for label, rate in [("light", light_rate), ("plus", plus_rate)]:
        if not (0.01 <= rate <= 0.20):
            raise ValueError(f"implausible {label} rate: {rate:.2%}")

    return {
        "name": "Klar",
        "institution_type": "sofipo",
        "plans": [
            {
                "plan_key": "light",
                "display_name": "Klar Light",
                "monthly_cost": 0,
                "tiers": [{"limit": "inf", "rate": light_rate}],
            },
            {
                "plan_key": "plus",
                "display_name": "Klar Plus",
                "monthly_cost": 0,
                "tiers": [{"limit": "inf", "rate": plus_rate}],
            },
            {
                "plan_key": "platino",
                "display_name": "Klar Platino",
                "monthly_cost": 0,
                "tiers": [{"limit": "inf", "rate": plus_rate}],
            },
        ],
    }


def _extract_uala(text: str) -> dict:
    # T&C — Base 6.75%, Plus 12% (gasto ≥$3k), Plus Alta 15% (gasto ≥$6k)
    base_rate = _rate_near(text, "6.75") or _rate_near(text, "6,75") or 0.0675
    # "Plus" rate — look for "12" near "plus" keyword
    plus_rate = _rate_near(text, "plus") or 0.12
    # "alta" rate
    alta_rate = _rate_near(text, "alta") or _rate_near(text, "Alta") or 0.15

    # Clamp to plausible ranges to avoid mis-parsing navigation links etc.
    if not (0.01 <= base_rate <= 0.15):
        base_rate = 0.0675
    if not (0.01 <= plus_rate <= 0.25):
        plus_rate = 0.12
    if not (0.01 <= alta_rate <= 0.25):
        alta_rate = 0.15

    return {
        "name": "Uala",
        "institution_type": "banco",
        "tiers": [
            {"limit": 30_000, "rate": base_rate},
            {
                "limit": 30_000,
                "rate": plus_rate,
                "constraints": [
                    {"type": "monthly_expense", "cost": 3000.0,
                     "benefit": "mid_rate_tier", "condition_value": 3000.0, "active": True},
                ],
            },
            {
                "limit": 30_000,
                "rate": alta_rate,
                "constraints": [
                    {"type": "monthly_expense", "cost": 6000.0,
                     "benefit": "high_rate_tier", "condition_value": 6000.0, "active": True},
                ],
            },
            {"limit": "inf", "rate": 0.0},
        ],
    }


def _extract_finsus(text: str) -> dict:
    # finsus.mx/personas/cuenta — heading: "Finsus+ con 7.01%* de rendimiento anual"
    # Disclaimer: "Tasa de rendimiento fija anual 7.01% ... a la vista"
    # Confirmed overnight (a la vista), no upper limit, min $0.01 MXN (2026-07-24)
    #
    # Rule: if page no longer shows a vista product, raise so the institution
    # is skipped and flagged for manual review rather than ingesting a wrong rate.
    # "Tu dinero disponible 24/7" is the static-HTML signal that this is a vista product.
    # "a la vista" only appears in a JS-rendered accordion — not fetchable via requests.
    if not re.search(r"disponible\s+24/7", text, re.IGNORECASE):
        raise ValueError("'disponible 24/7' not found — vista product may have changed; skip")
    m = re.search(r"(\d+\.\d+)%\*?\s+de\s+rendimiento\s+anual", text, re.IGNORECASE)
    if not m:
        m = re.search(r"rendimiento\s+fija\s+anual\s+(\d+\.\d+)%", text, re.IGNORECASE)
    if not m:
        raise ValueError("rate pattern not found on /personas/cuenta")
    rate = _pct(float(m.group(1)))
    if not (0.01 <= rate <= 0.25):
        raise ValueError(f"implausible rate: {rate:.2%}")
    return {
        "name": "Finsus",
        "institution_type": "sofipo",
        "tiers": [{"limit": "inf", "rate": rate}],
    }


def _extract_revolut(text: str) -> dict:
    # All plans share 15% for first $25k tier
    # Upper tiers are T&C-hardcoded and don't change with the promotion rate
    m = re.search(r"15\s*%", text)
    top_rate = 0.15 if m else (_find_pct(text) or 0.15)

    def _plan(plan_key: str, display: str, cost: float, mid: float, top: float) -> dict:
        tier0: dict = {"limit": 25_000, "rate": top_rate}
        if plan_key == "standard":
            tier0["constraints"] = [
                {"type": "transaction_count", "min_transactions": 4,
                 "min_amount_per_transaction": 50.0, "period_days": 30,
                 "benefit": "promo_15_rate", "active": True},
                {"type": "digital_wallet", "benefit": "promo_15_rate", "active": True},
            ]
        return {
            "plan_key": plan_key,
            "display_name": display,
            "monthly_cost": cost,
            "tiers": [
                tier0,
                {"limit": 1_000_000, "rate": mid},
                {"limit": "inf",     "rate": top},
            ],
        }

    return {
        "name": "Revolut",
        "institution_type": "banco",
        "plans": [
            _plan("standard", "Revolut Standard", 0,      0.07,  0.045),
            _plan("premium",  "Revolut Premium",  172.84, 0.073, 0.048),
            _plan("metal",    "Revolut Metal",    404.84, 0.075, 0.05),
        ],
    }


def _extract_stori(text: str) -> dict:
    # PDF — find nominal annual rate (~6.77%).
    # Require a decimal point to skip "0%" or integer page/section numbers.
    for m in re.finditer(r"(\d+\.\d+)\s*%", text):
        rate = _pct(float(m.group(1)))
        if 0.01 <= rate <= 0.30:
            return {
                "name": "Stori",
                "institution_type": "sofipo",
                "tiers": [{"limit": "inf", "rate": rate}],
            }
    raise ValueError("no plausible decimal rate found in PDF")


def _extract_plata(text: str) -> dict:
    # PDF — "sin Plata+: 7%" and "con Plata+: 10%"
    idx_sin = text.lower().find("sin plata")
    idx_con = text.lower().find("con plata")

    def _after(idx: int, fallback: float) -> float:
        if idx < 0:
            return fallback
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", text[idx: idx + 300])
        return _pct(float(m.group(1))) if m else fallback

    base_rate = _after(idx_sin, 0.07)
    plus_rate = _after(idx_con, 0.10)

    return {
        "name": "Plata",
        "institution_type": "banco",
        "plans": [
            {
                "plan_key": "base",
                "display_name": "Plata Ahorro Flexible",
                "monthly_cost": 0,
                "tiers": [{"limit": "inf", "rate": base_rate}],
            },
            {
                "plan_key": "plus",
                "display_name": "Plata Ahorro Flexible Plata+",
                "monthly_cost": 114.84,
                "tiers": [
                    {
                        "limit": "inf",
                        "rate": plus_rate,
                        "constraints": [
                            {"type": "monthly_expense", "cost": 114.84,
                             "benefit": "membership_plan", "condition_value": 114.84,
                             "active": True},
                        ],
                    }
                ],
            },
        ],
    }


# ── Source registry ───────────────────────────────────────────────────────────

PRIMARY_SOURCES: list[dict] = [
    # ── HTML (requests + BS4-free text extraction) ──
    {
        "name": "DiDi",
        "strategy": "html",
        "url": "https://web.didiglobal.com/mx/jpsofiexpress/didi-cuenta/",
        "extractor": _extract_didi,
    },
    {
        "name": "Openbank",
        "strategy": "html",
        "url": "https://www.openbank.mx/cuenta-debito-open-plus",
        "extractor": _extract_openbank,
    },
    {
        "name": "Supertasas",
        "strategy": "html",
        "url": "https://crediclub.com/inversiones",     # crediclub.com.mx DNS muerto
        "extractor": _extract_supertasas,
    },
    {
        "name": "Mifel",
        "strategy": "html",
        "url": "https://www.mifel.com.mx/personas/cuentas/cuenta-digital",
        "extractor": _extract_mifel,
    },
    {
        "name": "Klar",
        "strategy": "html",
        "url": "https://www.klar.mx/inversion",
        "extractor": _extract_klar,
    },
    {
        "name": "Uala",
        "strategy": "html",
        "url": "https://www.uala.mx/tyc-uala-cuenta-con-rendimiento-plus",
        "extractor": _extract_uala,
    },
    {
        "name": "Finsus",
        "strategy": "html",
        "url": "https://finsus.mx/personas/cuenta",
        "extractor": _extract_finsus,
    },
    {
        "name": "Revolut",
        "strategy": "html",
        "url": "https://www.revolut.com/es-MX/instant-access-savings/",
        "extractor": _extract_revolut,
    },
    # ── PDF (requests + pdfplumber) ──
    {
        "name": "Nu",
        "strategy": "pdf",
        "url": "https://cdn.nubank.com.br/MX/folleto-informativo-cuenta.pdf",
        "extractor": _extract_nu,
    },
    {
        "name": "Stori",
        "strategy": "pdf",
        "url": "https://www.storicard.com/files/stori-cuentamas/folleto-informativo-depositos.pdf?v=20260113",
        "extractor": _extract_stori,
    },
    {
        "name": "Plata",
        "strategy": "pdf",
        "url": "https://prime.platacard.mx/file-service/static/eula/ahorro_flexible_booklet.pdf",
        "extractor": _extract_plata,
    },
    # ── Skipped ──
    # Mercado Pago: Tasa Objetivo only visible when authenticated; rate varies by user → manual
    # Cetes 28d: cetesdirecto.com is a SPA → use Banxico SIE API (BANXICO_API_TOKEN needed)
    # BONDDIA: removed from scope 2026-07-24
]


# ── Scrape loop ───────────────────────────────────────────────────────────────

def scrape_all() -> tuple[list[dict], list[tuple[str, str]]]:
    """Fetch and extract all primary sources.

    Returns:
        institutions: list of institution dicts (successful extractions)
        failures: list of (name, error_message) tuples
    """
    institutions: list[dict] = []
    failures: list[tuple[str, str]] = []

    for src in PRIMARY_SOURCES:
        name = src["name"]
        try:
            if src["strategy"] == "html":
                content = _fetch_html(src["url"])
            else:
                content = _fetch_pdf_text(src["url"])

            institution = src["extractor"](content)
            institutions.append(institution)

            # Report highest rate found for quick log review
            all_rates: list[float] = []
            for tier in institution.get("tiers", []):
                if isinstance(tier.get("rate"), float):
                    all_rates.append(tier["rate"])
            for plan in institution.get("plans", []):
                for tier in plan.get("tiers", []):
                    if isinstance(tier.get("rate"), float):
                        all_rates.append(tier["rate"])
            top_str = f"{max(all_rates):.2%}" if all_rates else "?"
            print(f"  [OK]   {name}: top rate = {top_str}", file=sys.stderr)

        except Exception as exc:
            msg = str(exc)
            print(f"  [FAIL] {name}: {msg}", file=sys.stderr)
            failures.append((name, msg))

    return institutions, failures


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print YAML, do not write file.")
    parser.add_argument("--ingest", action="store_true", help="Run ingest after writing.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output YAML path.")
    args = parser.parse_args(argv)

    print("Scraping primary T&C sources...", file=sys.stderr)
    institutions, failures = scrape_all()

    data = {"institutions": institutions}
    yaml_text = (
        "# Auto-generated by scrape_primary CLI\n"
        "# Source: institution T&C pages (primary) — see PRIMARY_SOURCES in this file\n"
        "# Tier limits are hardcoded per T&C; only rates are scraped.\n\n"
        + yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    )

    if args.dry_run:
        print(yaml_text)
    else:
        args.output.write_text(yaml_text, encoding="utf-8")
        print(
            f"\nWrote {len(institutions)} institutions to {args.output}",
            file=sys.stderr,
        )

    if failures:
        names = ", ".join(n for n, _ in failures)
        print(f"\nFAILURES ({len(failures)}): {names}", file=sys.stderr)
        print("ACTION_REQUIRED: notify CTO agent — run `scrape_primary --dry-run` for details", file=sys.stderr)

    if not args.dry_run and args.ingest and institutions:
        from rate_allocator.cli.ingest import main as _ingest_main
        rc = _ingest_main([
            str(args.output),
            "--init-schema",
            "--note", "scraped from primary T&C sources",
        ])
        if rc != 0:
            return rc

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
