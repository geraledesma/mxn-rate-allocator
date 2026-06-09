# MXN Rate Allocator

Distribución óptima de capital entre bancos y SOFIPOs mexicanos para maximizar el rendimiento real — neto de ISR e inflación, con cobertura IPAB/Prosofipo garantizada.

## Por qué existe este proyecto

La inclusión financiera es uno de los problemas más serios de México. No solo afecta las finanzas personales de los ciudadanos — tiene un efecto multiplicador directo sobre la calidad de vida, el acceso al crédito, el crecimiento de negocios pequeños y, en consecuencia, la generación de empleo y el desarrollo económico del país.

En el centro de ese problema está la educación financiera: es muy pobre, y eso tiene consecuencias concretas. La mayoría de los ahorradores mexicanos deja su dinero en cuentas que pagan 2–4% cuando existen opciones reguladas y seguras que pagan 10–15% — no por falta de interés, sino porque comparar las opciones es genuinamente difícil.

Este proyecto existe para reducir esa brecha. La herramienta es gratuita, está en español, y está diseñada para que cualquier persona — sin conocimientos financieros previos — pueda tomar una decisión de ahorro informada y segura.

## Qué hace

Dado un monto a invertir, el algoritmo distribuye el capital entre las instituciones disponibles para:

- Maximizar el rendimiento efectivo neto de impuestos y comisiones
- Respetar los límites de cobertura IPAB (3.3 M MXN/banco) y Prosofipo (208 k MXN/SOFIPO)
- Minimizar el número de cuentas necesarias cuando el rendimiento es equivalente
- Considerar condiciones específicas por institución (membresías, depósitos mínimos, etc.)

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

## Demo interactivo (Streamlit)

**Live demo:** [https://rate-allocator-4mhzzryvjevndl5wnh9dqx.streamlit.app/](https://rate-allocator-4mhzzryvjevndl5wnh9dqx.streamlit.app/)

```bash
pip install -e ".[streamlit]"
streamlit run streamlit_app.py
```

La UI está en español. Lee tasas desde SQLite (`data/rates.db`); para regenerar la base después de editar el YAML:

```bash
python3 scripts/seed_rates_sqlite.py --yaml data/sample1.yaml --db data/rates.db
```

## Running Tests

```bash
pytest tests/
```

## How It Works

El optimizador usa programación lineal entera mixta (MILP) con SciPy:

- **Variables:** monto acumulado por tramo por institución
- **Objetivo:** maximizar el interés total generado
- **Restricciones:** presupuesto total, límites por tramo, llenado secuencial de tramos, cobertura institucional

Ver `docs/assumptions.md` para las especificaciones completas del modelo.

## Project Layout

| Path | Purpose |
|------|---------|
| `src/rate_allocator/domain/` | Entidades (`Institution`, `Tier`, `Constraint`, `AllocationResult`) |
| `src/rate_allocator/core/optimizer/` | `allocate()` — motor MILP |
| `src/rate_allocator/core/finance/` | Tasas, costos, ISR |
| `src/rate_allocator/adapters/` | Carga de YAML y reglas regulatorias |
| `src/rate_allocator/reporting/` | Resúmenes y gráficas |
| `src/rate_allocator/workflows/` | `summarize_and_plot`, `build_interactive_report_html` |
| `data/*.yaml` | Instituciones de ejemplo y reglas regulatorias MX |
| `streamlit_app.py` | Demo público |
