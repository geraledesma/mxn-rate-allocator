# MXN Rate Allocator

> Part of the [Merqurio](https://merqurio.com.mx) suite — accessible financial tools for Mexico and LatAm.

Optimal capital distribution across Mexican banks and SOFIPOs to maximize real yield — net of taxes and inflation, with guaranteed IPAB/Prosofipo coverage.

> Source available under [BUSL-1.1](LICENSE). Free for personal, non-commercial use.

## Why this project exists

Financial inclusion is one of Mexico's most serious problems. It doesn't just affect the personal finances of individual citizens — it has a direct multiplier effect on quality of life, access to credit, small business growth, and ultimately job creation and economic development across the country.

At the root of that problem is financial education: it's very poor, and that has concrete consequences. Most Mexican savers leave their money in accounts paying 2–4% when regulated, safe options exist paying 10–15% — not out of lack of interest, but because comparing the available options is genuinely difficult.

This project exists to close that gap. The tool is free, built in Spanish, and designed so that anyone — without prior financial knowledge — can make an informed and safe savings decision.

## What it does

Given an amount to invest, the algorithm distributes capital across available institutions to:

- Maximize effective yield net of taxes and fees
- Respect IPAB coverage limits (3.3 M MXN/bank) and Prosofipo limits (208 k MXN/SOFIPO)
- Minimize the number of accounts needed when yield is equivalent
- Account for institution-specific conditions (memberships, minimum deposits, etc.)

## Quick Start

```python
from rate_allocator import allocate, Institution, Tier

institutions = [
    Institution(
        name="Nu",
        tiers=(
            Tier(limit=25_000, rate=0.15),
            Tier(limit=250_000, rate=0.12),
            Tier(limit=float("inf"), rate=0.10),
        ),
    ),
    Institution(
        name="Mercado Pago",
        tiers=(
            Tier(limit=23_000, rate=0.14),
            Tier(limit=float("inf"), rate=0.10),
        ),
    ),
]

result = allocate(total=100_000, institutions=institutions)
print(f"Expected return: {result.expected_return:,.2f}")
print(f"Effective rate: {result.effective_rate:.2%}")
```

## Installation

```bash
pip install -e .
```

## Interactive demo (Streamlit)

**Live demo:** [https://rate-allocator-4mhzzryvjevndl5wnh9dqx.streamlit.app/](https://rate-allocator-4mhzzryvjevndl5wnh9dqx.streamlit.app/)

```bash
pip install -e ".[streamlit]"
streamlit run streamlit_app.py
```

The UI is in Spanish. Reads rates from SQLite (`data/rates.db`); to seed the database:

```bash
pip install -e ".[streamlit]"
rate-seed --yaml data/sample1.yaml --db data/rates.db
RATE_ALLOCATOR_DB_URL="sqlite:///$(pwd)/data/rates.db" streamlit run streamlit_app.py
```

## CLI Commands

After `pip install -e .`, three commands are available:

| Command | Purpose |
|---------|---------|
| `rate-scrape` | Scrape current rates from tasas.mx → `data/scraped_live.yaml` |
| `rate-ingest <file.yaml>` | Ingest institutions or regulatory rules into the SCD2 database |
| `rate-seed --yaml <file> --db <db>` | Seed a fresh SQLite database from a YAML snapshot |

```bash
# Full update cycle
rate-scrape --output data/scraped_live.yaml
RATE_ALLOCATOR_DB_URL="sqlite:///$(pwd)/data/rates.db" rate-ingest data/scraped_live.yaml
RATE_ALLOCATOR_DB_URL="sqlite:///$(pwd)/data/rates.db" rate-ingest data/manual_additions.yaml
```

See `scripts/commands/update-rates.md` for the full update workflow.

## Running Tests

```bash
pytest tests/
```

## How It Works

The optimizer uses Mixed Integer Linear Programming (MILP) via SciPy:

- **Variables:** cumulative amount per tier per institution
- **Objective:** maximize total interest earned
- **Constraints:** total budget, per-tier limits, sequential tier filling, institutional coverage

See `docs/assumptions.md` for full model specifications.

## Project Layout

```
src/rate_allocator/
├── cli/            rate-scrape, rate-ingest, rate-seed entry points
├── domain/         Institution, Tier, Constraint, AllocationResult, RegulatoryRules
├── core/
│   ├── optimizer/  allocate() — MILP engine (SciPy)
│   └── finance/    rates, costs, taxes, ISR
├── adapters/       YAML, DB, and regulatory rules loaders
├── persistence/    SQLAlchemy ORM, SCD2 ingest, migration (Alembic)
├── reporting/      summaries, charts
└── workflows/      summarize_and_plot, build_interactive_report_html

data/
├── sample1.yaml              primary sample (app + tests)
├── sample_comprehensive.yaml 20-institution dataset (extended tests)
├── manual_additions.yaml     institutions not on tasas.mx (PlataCard, Mifel)
├── noticias.yaml             curated rate-change history
└── regulatory_rules.mx.yaml  IPAB / Prosofipo coverage limits

scripts/commands/update-rates.md   /update-rates skill for Claude Code CLI
notebooks/demo_ipywidgets_es.ipynb interactive Spanish demo
streamlit_app.py                   public Streamlit demo entrypoint
```
