# MXN Rate Allocator

Optimal capital distribution across Mexican banks and SOFIPOs to maximize real yield — net of taxes and inflation, with guaranteed IPAB/Prosofipo coverage.

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

The UI is in Spanish. Reads rates from SQLite (`data/rates.db`); to regenerate the database after editing the YAML:

```bash
python3 scripts/seed_rates_sqlite.py --yaml data/sample1.yaml --db data/rates.db
```

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

| Path | Purpose |
|------|---------|
| `src/rate_allocator/domain/` | Entities (`Institution`, `Tier`, `Constraint`, `AllocationResult`) |
| `src/rate_allocator/core/optimizer/` | `allocate()` — MILP engine |
| `src/rate_allocator/core/finance/` | Rates, costs, taxes |
| `src/rate_allocator/adapters/` | YAML and regulatory rules loaders |
| `src/rate_allocator/reporting/` | Summaries and charts |
| `src/rate_allocator/workflows/` | `summarize_and_plot`, `build_interactive_report_html` |
| `data/*.yaml` | Sample institutions and MX regulatory rules |
| `streamlit_app.py` | Public demo entrypoint |
