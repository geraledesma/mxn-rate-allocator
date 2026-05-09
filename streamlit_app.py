"""Streamlit demo: mirrors notebooks/demo_ipywidgets_es.ipynb (allocate → HTML report, UI in Spanish)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import matplotlib

matplotlib.use("Agg")

import pandas as pd
import streamlit as st

from rate_allocator import Institution, RegulatoryRules, allocate
from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.yaml_loader import load_institutions_with_overrides
from rate_allocator.reporting.summary import summarize_allocation
from rate_allocator.workflows.interactive_report import (
    build_allocation_combo_figure,
    build_interactive_report_html,
    build_portfolio_path_figure,
)

REPO_ROOT = Path(__file__).resolve().parent
DATA_FILE = REPO_ROOT / "data" / "sample1.yaml"
RULES_FILE = REPO_ROOT / "data" / "regulatory_rules.mx.yaml"
MX_ZONE = ZoneInfo("America/Mexico_City")
DB_URL_ENV = "RATE_ALLOCATOR_DB_URL"

TOTAL_MIN = 1
TOTAL_MAX = 1_200_000
TOTAL_DEFAULT = 100_000
CACHE_LOAD_TTL_SECONDS = 120

STRINGS = {
    "page_title": "Rate Allocator",
    "title": "Rate Allocator: demo interactivo",
    "caption": (
        "Elige instituciones y el total en MXN (deslizador o campo numérico, pasos de 100). "
        "Las tasas y comisiones salen del archivo YAML de ejemplo o de la base de datos si "
        f"configuraste `{DB_URL_ENV}`. Ejecuta `scripts/ingest_yaml.py` y usa **Recargar datos**. "
        "El horizonte en años ajusta el compuesto al plazo y el modelado de comisiones en el informe."
    ),
    "institutions": "Instituciones a incluir",
    "total_slider": "Total (MXN):",
    "total_number": "Mismo total (escribe o ±100):",
    "horizon": "Horizonte (años)",
    "empty": "Selecciona al menos una institución.",
    "no_fees": "sin comisiones modeladas",
    "date_mx": "**Hoy** ({weekday}, {iso} — America/Mexico_City)",
    "source_db": "Fuente de tasas y reglas: **base de datos**",
    "source_yaml": "Fuente de tasas y reglas: **archivo YAML (demo)**",
    "db_fallback_missing_deps": (
        "Se configuró `RATE_ALLOCATOR_DB_URL`, pero faltan dependencias de BD "
        "(por ejemplo `sqlalchemy`). Se usa fallback a YAML para evitar que la app falle."
    ),
    "reload": "Recargar datos",
    "noticias": "Noticias",
    "noticias_help": "Cambios recientes en tasas nominales por tramo (histórico SCD2 en la BD).",
    "noticias_empty": "No hay cambios de tasa registrados en la BD aún.",
    "noticias_no_db": "Las noticias de tasas requieren una base de datos ingestada.",
    "chart_section": "Asignación de capital por institución",
    "path_section": "Trayectoria del portafolio",
    "pie_warn_empty": "No hay principal asignado para el gráfico circular.",
    "viz_section": "Panorama visual",
    "viz_caption": (
        "Métricas y gráfico interactivo a partir del resultado de la optimización. "
        "Abajo, el informe detallado con tabla por tramo y gráficos matplotlib."
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
    "detail_caption": "Tramos, comisiones, torta de principal e intereses por tramo.",
    "no_allocation": "Con estos parámetros no hay capital asignado; sube el monto o revisa instituciones.",
}


def _today_mx_label() -> str:
    d = datetime.now(MX_ZONE).date()
    weekdays = (
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
    )
    weekday = weekdays[d.weekday()]
    return STRINGS["date_mx"].format(weekday=weekday, iso=d.isoformat())


def _fallback_rules() -> RegulatoryRules:
    return load_regulatory_rules_from_yaml(str(RULES_FILE))


def _try_load_db_snapshot(
    db_url: str,
) -> tuple[list[Institution], RegulatoryRules | None] | None:
    """Return DB snapshot or None when DB modules are unavailable."""
    try:
        from rate_allocator.adapters.db_loader import (
            load_institutions_from_db,
            load_regulatory_rules_from_db,
        )
        from rate_allocator.persistence import create_db_engine, session_scope
    except ModuleNotFoundError:
        return None

    engine = create_db_engine(db_url)
    with session_scope(engine) as session:
        institutions = load_institutions_from_db(session)
        rules = load_regulatory_rules_from_db(session, country="MX")
    return institutions, rules


def _db_runtime_available() -> bool:
    try:
        import sqlalchemy  # noqa: F401
        from rate_allocator.adapters import db_loader  # noqa: F401
        from rate_allocator.persistence import history  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


@st.cache_data(ttl=CACHE_LOAD_TTL_SECONDS, show_spinner="Cargando instituciones y reglas...")
def _load_snapshot(
    _reload_nonce: int,
) -> tuple[list[Institution], RegulatoryRules, str, bool]:
    """Return (institutions, rules, source_key_db_or_yaml, db_url_was_set)."""
    db_url = os.environ.get(DB_URL_ENV)
    if not db_url:
        institutions = load_institutions_with_overrides(str(DATA_FILE), {})
        rules = _fallback_rules()
        return institutions, rules, "yaml", False

    db_snapshot = _try_load_db_snapshot(db_url)
    if db_snapshot is None:
        institutions = load_institutions_with_overrides(str(DATA_FILE), {})
        rules = _fallback_rules()
        return institutions, rules, "yaml", True

    institutions, rules = db_snapshot
    if institutions:
        resolved_rules = rules if rules is not None else _fallback_rules()
        return institutions, resolved_rules, "db", True
    inst_yaml = load_institutions_with_overrides(str(DATA_FILE), {})
    resolved_rules = rules if rules is not None else _fallback_rules()
    return inst_yaml, resolved_rules, "yaml", True


def _brief_constraints_label(inst) -> str:
    parts = []
    for tier in inst.tiers:
        for c in tier.constraints:
            parts.append(f"{c.type} ${c.cost:.2f}")
    return ", ".join(parts) if parts else STRINGS["no_fees"]


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


def _format_mx_compact(value: float) -> str:
    if value >= 1_000_000:
        return f"$ {value/1e6:.2f} M"
    if value >= 1_000:
        return f"$ {value/1e3:,.1f} k"
    return f"$ {value:,.0f}"


def main() -> None:
    st.set_page_config(page_title=STRINGS["page_title"], layout="wide")

    if "total_mxn" not in st.session_state:
        st.session_state.total_mxn = TOTAL_DEFAULT
    if "reload_nonce" not in st.session_state:
        st.session_state.reload_nonce = 0

    t = STRINGS

    st.markdown(_today_mx_label())
    base_institutions, regulatory_rules, source_key, db_configured = _load_snapshot(
        st.session_state.reload_nonce
    )
    if source_key == "db":
        st.caption(t["source_db"])
    else:
        st.caption(t["source_yaml"])
    if db_configured and source_key != "db" and not _db_runtime_available():
        st.warning(t["db_fallback_missing_deps"])

    if db_configured:
        with st.expander(t["noticias"], expanded=False):
            st.caption(t["noticias_help"])
            db_url = os.environ.get(DB_URL_ENV)
            if not db_url:
                st.info(t["noticias_no_db"])
            else:
                try:
                    from rate_allocator.persistence import create_db_engine, session_scope
                    from rate_allocator.persistence.history import (
                        load_recent_tier_rate_changes,
                    )
                except ModuleNotFoundError:
                    st.info(t["noticias_no_db"])
                    events = []
                else:
                    engine = create_db_engine(db_url)
                    with session_scope(engine) as session:
                        events = load_recent_tier_rate_changes(session, limit=50)
                if not events:
                    st.info(t["noticias_empty"])
                else:
                    rows = [
                        {
                            "Fecha (aplicada)": e.applied_at.astimezone(MX_ZONE).strftime(
                                "%Y-%m-%d %H:%M %Z"
                            ),
                            "Institución": e.institution_name,
                            "Tramo": e.tier_index + 1,
                            "Tasa anterior": f"{e.old_rate:.2%}",
                            "Tasa nueva": f"{e.new_rate:.2%}",
                            "Origen": e.source or "—",
                        }
                        for e in events
                    ]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.title(t["title"])
    st.caption(t["caption"])

    all_names = [inst.name for inst in base_institutions]
    hints = {inst.name: _brief_constraints_label(inst) for inst in base_institutions}

    total_value = max(TOTAL_MIN, min(TOTAL_MAX, int(st.session_state.total_mxn)))

    with st.sidebar:
        if st.button(t["reload"], help="Invalida la caché de Streamlit y vuelve a leer YAML o la BD."):
            st.cache_data.clear()
            st.session_state.reload_nonce = int(st.session_state.reload_nonce) + 1
            st.rerun()
        hint_db = os.environ.get(DB_URL_ENV, "")
        st.caption(
            (
                "Conexión: variable de entorno configurada ✓"
                if hint_db
                else "Conexión: solo YAML demo (sin `RATE_ALLOCATOR_DB_URL`)"
            )
        )

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
        regulatory_rules=regulatory_rules,
    )

    if result.total_allocated <= 1e-9:
        st.warning(t["no_allocation"])
        return

    institution_totals = [
        (name, sum(amounts))
        for name, amounts in result.allocations.items()
        if sum(amounts) > 0
    ]

    summary = summarize_allocation(
        result,
        institutions,
        horizon_years=horizon_years,
        compound_years=horizon_years,
        compounding_periods_per_year=365,
        regulatory_rules=regulatory_rules,
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
    if not df_chart.empty:
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
        regulatory_rules=regulatory_rules,
        locale="es",
        embed_charts=False,
    )
    st.markdown(html_fragment, unsafe_allow_html=True)

    st.markdown(f"### {t['chart_section']}")
    combo_vals = [float(v) for _n, v in institution_totals]
    if sum(combo_vals) <= 0:
        st.warning(t["pie_warn_empty"])
    else:
        fig_combo = build_allocation_combo_figure(
            result,
            institutions,
            institution_totals,
            horizon_years=horizon_years,
            periods_per_year=365,
            regulatory_rules=regulatory_rules,
            locale="es",
        )
        st.pyplot(fig_combo, clear_figure=True)

    st.markdown(f"### {t['path_section']}")
    fig_path = build_portfolio_path_figure(
        result,
        institutions,
        max_days=365,
        periods_per_year=365,
        locale="es",
    )
    st.pyplot(fig_path, clear_figure=True)


if __name__ == "__main__":
    main()
