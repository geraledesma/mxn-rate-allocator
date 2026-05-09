"""Streamlit demo: mirrors notebooks/demo_ipywidgets_es.ipynb (allocate → HTML report, UI in Spanish)."""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from rate_allocator import (
    allocate,
    build_interactive_report_html,
    summarize_allocation,
)
from rate_allocator.adapters.sqlite_loader import load_institutions_from_sqlite

REPO_ROOT = Path(__file__).resolve().parent

TOTAL_MIN = 0
TOTAL_MAX = 1_200_000
TOTAL_DEFAULT = 100_000

STRINGS = {
    "page_title": "Rate Allocator",
    "title": "Rate Allocator: demo interactivo",
    "caption": (
        "Elige instituciones y el total en MXN (deslizador o campo numérico, pasos de 100). "
        "Las tasas y comisiones se cargan desde la base SQLite incluida en el proyecto "
        "(por defecto `data/rates.db`, no YAML). Actualiza esa BD con el script "
        "`scripts/seed_rates_sqlite.py` o cambia la ruta con la variable "
        "`RATE_ALLOCATOR_SQLITE` / secret homónimo. "
        "El horizonte en años ajusta el compuesto al plazo y el modelado de comisiones en el informe."
    ),
    "institutions": "Instituciones a incluir",
    "total_slider": "Total (MXN):",
    "total_number": "Mismo total (escribe o ±100):",
    "horizon": "Horizonte (años)",
    "empty": "Selecciona al menos una institución.",
    "no_fees": "sin comisiones modeladas",
    "viz_section": "Panorama visual",
    "viz_caption": (
        "Métricas y gráficos interactivos a partir del mismo resultado de la optimización. "
        "Abajo tienes el informe detallado con tabla por tramo y gráficos (matplotlib)."
    ),
    "summary_box": "Métricas clave",
    "metric_requested": "Monto solicitado",
    "metric_allocated": "Monto asignado",
    "metric_eff_rate": "Tasa efectiva (horizonte)",
    "metric_exp_return": "Rendimiento neto esperado",
    "chart_alloc_title": "Asignación de capital por institución",
    "chart_tooltip_monto": "Monto (MXN)",
    "table_inst_title": "Desglose por institución",
    "detail_section": "Informe detallado (tabla y gráficos)",
    "detail_caption": "El mismo formato que usa el notebook: tramos, comisiones, torta de principal e intereses por tramo.",
    "no_allocation": "Con estos parámetros no hay capital asignado; sube el monto o revisa instituciones.",
    "db_missing": "No se encontró la base SQLite de tasas en `{path}`.",
    "db_seed_hint": (
        "Genera **data/rates.db** con:\n```\npython3 scripts/seed_rates_sqlite.py\n```"
        "\nOpcionalmente apunta otro archivo con env `RATE_ALLOCATOR_SQLITE` o el secret Streamlit igual."
    ),
}


def resolve_streamlit_sqlite_path() -> Path:
    """Prefer env, then Streamlit secret, then bundled ``data/rates.db``."""

    raw = os.environ.get("RATE_ALLOCATOR_SQLITE")
    if raw:
        return Path(raw).expanduser().resolve()
    try:
        sec = getattr(st, "secrets", None)
        if sec is not None:
            val = sec.get("RATE_ALLOCATOR_SQLITE") if hasattr(sec, "get") else None
            if val:
                return Path(str(val)).expanduser().resolve()
    except Exception:
        pass
    return (REPO_ROOT / "data" / "rates.db").resolve()


def _brief_constraints_label(inst) -> str:
    parts = []
    for tier in inst.tiers:
        for c in tier.constraints:
            parts.append(f"{c.type} ${c.cost:.2f}")
    return ", ".join(parts) if parts else STRINGS["no_fees"]


@st.cache_data
def _load_base_institutions(db_path_str: str):
    """Institutions keyed by SQLite path string so caches invalidate per DB file."""

    return load_institutions_from_sqlite(Path(db_path_str).expanduser().resolve())


def _sync_total_from_slider() -> None:
    st.session_state.total_mxn = int(st.session_state._total_slider)


def _sync_total_from_number() -> None:
    st.session_state.total_mxn = int(st.session_state._total_num)


def _institution_allocation_chart(df: pd.DataFrame, title: str, x_title: str) -> alt.Chart:
    bar = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4, color="#2563eb")
        .encode(
            x=alt.X("monto_q:Q", title=x_title).axis(format=",.0f"),
            y=alt.Y("institucion:N", title="", sort="-x"),
            tooltip=[
                alt.Tooltip("institucion:N", title="Institución"),
                alt.Tooltip("monto_q:Q", title="Monto (MXN)", format=",.2f"),
            ],
        )
    )
    text = (
        alt.Chart(df)
        .mark_text(align="left", baseline="middle", dx=6, fontSize=11)
        .encode(
            x=alt.X("monto_q:Q"),
            y=alt.Y("institucion:N", sort="-x"),
            text=alt.Text("etiqueta:N"),
        )
    )
    h = len(df)
    chart = (
        (bar + text)
        .properties(height=max(220, min(540, h * 36)), padding=12, title=title)
        .configure_axis(labelFontSize=12, titleFontSize=13)
        .configure_title(fontSize=15, anchor="start")
        .interactive()
    )
    return chart


def main() -> None:
    st.set_page_config(page_title=STRINGS["page_title"], layout="wide")

    if "total_mxn" not in st.session_state:
        st.session_state.total_mxn = TOTAL_DEFAULT

    t = STRINGS

    sqlite_path = resolve_streamlit_sqlite_path()
    if not sqlite_path.is_file():
        st.error(t["db_missing"].format(path=sqlite_path))
        st.markdown(t["db_seed_hint"])
        st.stop()

    st.title(t["title"])
    st.caption(t["caption"])

    base_institutions = _load_base_institutions(str(sqlite_path))
    all_names = [inst.name for inst in base_institutions]
    hints = {inst.name: _brief_constraints_label(inst) for inst in base_institutions}

    total_value = max(TOTAL_MIN, min(TOTAL_MAX, int(st.session_state.total_mxn)))

    with st.sidebar:
        st.caption(f"BD SQLite: `{sqlite_path.name}`")

        def _institution_option_label(n: str) -> str:
            hint = hints[n]
            return n if hint == t["no_fees"] else f"{n} ({hint})"

        selected = st.multiselect(
            t["institutions"],
            options=all_names,
            default=all_names,
            format_func=_institution_option_label,
        )
        st.slider(
            t["total_slider"],
            min_value=TOTAL_MIN,
            max_value=TOTAL_MAX,
            value=total_value,
            step=100,
            key="_total_slider",
            on_change=_sync_total_from_slider,
        )
        st.number_input(
            t["total_number"],
            min_value=TOTAL_MIN,
            max_value=TOTAL_MAX,
            value=total_value,
            step=100,
            key="_total_num",
            on_change=_sync_total_from_number,
        )
        horizon_years = st.slider(
            t["horizon"],
            min_value=0.25,
            max_value=5.0,
            value=1.0,
            step=0.25,
        )

    total = max(TOTAL_MIN, min(TOTAL_MAX, int(st.session_state.total_mxn)))

    if not selected:
        st.info(t["empty"])
        return

    institutions = [inst for inst in base_institutions if inst.name in selected]

    result = allocate(
        total=total,
        institutions=institutions,
        horizon_years=horizon_years,
        periods_per_year=365,
    )

    if result.total_allocated <= 1e-9:
        st.warning(t["no_allocation"])
        return

    summary = summarize_allocation(
        result,
        institutions,
        horizon_years=horizon_years,
        compound_years=horizon_years,
        compounding_periods_per_year=365,
    )

    st.subheader(t["viz_section"])
    st.caption(t["viz_caption"])

    with st.container():
        st.markdown(f"##### {t['summary_box']}")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric(
                label=t["metric_requested"],
                value=f"{total:,.0f} MXN",
            )
        with m2:
            st.metric(
                label=t["metric_allocated"],
                value=f"{result.total_allocated:,.0f} MXN",
                delta=(
                    f"{total - result.total_allocated:,.0f} MXN sin asignar"
                    if abs(total - result.total_allocated) > 0.5
                    else None
                ),
            )
        with m3:
            st.metric(label=t["metric_eff_rate"], value=f"{result.effective_rate:.2%}")
        with m4:
            st.metric(
                label=t["metric_exp_return"],
                value=f"${result.expected_return:,.0f}",
            )

    chart_rows = [
        {"institucion": r.name, "monto_q": r.amount}
        for r in summary.institutions
        if r.amount > 0
    ]
    df_chart = pd.DataFrame(chart_rows)
    if df_chart.empty:
        st.warning(t["no_allocation"])
        return

    df_chart["etiqueta"] = df_chart["monto_q"].apply(
        lambda v: _format_mx_compact(float(v)),
    )

    st.markdown(f"##### {t['chart_alloc_title']}")
    chart = _institution_allocation_chart(
        df_chart.sort_values("monto_q", ascending=True),
        title="",
        x_title=t["chart_tooltip_monto"],
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown(f"##### {t['table_inst_title']}")
    tbl = pd.DataFrame(
        [
            {
                "Institución": r.name,
                "Monto (MXN)": r.amount,
                "Participación (%)": r.weight * 100,
                "Interés bruto (horizon.)": r.gross_interest,
                "Comisiones": r.constraint_cost_paid,
                "ISR (estim.)": r.tax_cost_paid,
                "Retención (estim.)": r.withholding_paid,
                "Contribución neta": r.net_contribution,
            }
            for r in summary.institutions
            if r.amount > 0
        ]
    )
    tbl = tbl.sort_values("Monto (MXN)", ascending=False).reset_index(drop=True)
    st.dataframe(
        tbl,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Monto (MXN)": st.column_config.NumberColumn(format="$%.0f"),
            "Participación (%)": st.column_config.NumberColumn(format="%.1f %%"),
            "Interés bruto (horizon.)": st.column_config.NumberColumn(format="$%.2f"),
            "Comisiones": st.column_config.NumberColumn(format="$%.2f"),
            "ISR (estim.)": st.column_config.NumberColumn(format="$%.2f"),
            "Retención (estim.)": st.column_config.NumberColumn(format="$%.2f"),
            "Contribución neta": st.column_config.NumberColumn(format="$%.2f"),
        },
    )

    st.divider()
    st.subheader(t["detail_section"])
    st.caption(t["detail_caption"])

    html_fragment = build_interactive_report_html(
        result,
        institutions,
        total=total,
        horizon_years=horizon_years,
        periods_per_year=365,
        locale="es",
    )
    st.markdown(html_fragment, unsafe_allow_html=True)


def _format_mx_compact(value: float) -> str:
    if value >= 1_000_000:
        return f"$ {value/1e6:.2f} M"
    if value >= 1_000:
        return f"$ {value/1e3:,.1f} k"
    return f"$ {value:,.0f}"


if __name__ == "__main__":
    main()
