# Rate Allocator — start here

Modular Python package for tiered cash allocation (LP via SciPy).

## Clone and enter the repo

```bash
git clone <your-repo-url> rate-allocator
cd rate-allocator
```

## Quick start

### Option A — Streamlit demo (browser)

```bash
pip install -e ".[streamlit]"
streamlit run streamlit_app.py
```

With **`RATE_ALLOCATOR_DB_URL`** set, the UI reads institutions and MX regulatory rules from the database (YAML fallback applies if DB institutions are missing or rules absent). Hit **Recargar datos** in the sidebar after re-ingesting. Example:

```bash
export RATE_ALLOCATOR_DB_URL="sqlite:///$(pwd)/data/rates.db"
python scripts/ingest_yaml.py data/sample1.yaml
python scripts/backfill_history_2026_05_08.py
streamlit run streamlit_app.py
```

On **Streamlit Community Cloud**, store the database URL plus this project’s Postgres/SQLite as `RATE_ALLOCATOR_DB_URL` in app secrets—without it the allocator falls back to checked-in YAML and **Noticias** only mirrors SCD2 from the BD you expose there.

The demo YAML includes example rates such as **PlataAhorroPlus**; change them and run ingest again when you refresh published yields.

### Option B — Jupyter notebook

```bash
pip install -e ".[notebook]"
jupyter notebook notebooks/demo.ipynb
```

Interactive widgets demos: `notebooks/demo_ipywidgets_en.ipynb` and `notebooks/demo_ipywidgets_es.ipynb` (restart kernel and run all). The hosted Streamlit app mirrors the Spanish notebook: **Spanish** UI and report (`demo_ipywidgets_es.ipynb`).

### Option C — Python REPL

```bash
pip install -e .
python3 << 'PYTHON'
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
]

result = allocate(total=100_000, institutions=institutions)
print(f"Effective rate: {result.effective_rate:.2%}")
print(f"Return: ${result.expected_return:,.2f}")
PYTHON
```

### Option D — Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Project layout

| Path | Purpose |
|------|---------|
| `src/rate_allocator/domain/` | Entities (`Institution`, `Tier`, `Constraint`, `AllocationResult`) |
| `src/rate_allocator/adapters/` | YAML loaders |
| `src/rate_allocator/core/finance/` | Rates, costs, taxes |
| `src/rate_allocator/core/optimizer/` | `allocate()` |
| `src/rate_allocator/reporting/` | Summaries and plots |
| `src/rate_allocator/workflows/` | `summarize_and_plot`, `build_interactive_report_html` |
| `data/*.yaml` | Example institutions and regulatory defaults |
| `streamlit_app.py` | Public demo entrypoint |

## Recommended reading order

1. `src/rate_allocator/domain/models.py`
2. `src/rate_allocator/core/finance/rates.py`
3. `src/rate_allocator/core/finance/costs.py`
4. `src/rate_allocator/core/optimizer/solve.py`
5. `src/rate_allocator/reporting/summary.py`
6. `src/rate_allocator/workflows/analysis.py`

## Notes

- Legacy modules (`rate_allocator.io`, `rate_allocator.summary`, `rate_allocator.models`, `rate_allocator.allocator`) are compatibility shims.
- Prefer the paths above for ongoing development.
