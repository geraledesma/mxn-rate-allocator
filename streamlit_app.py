"""Streamlit demo: mirrors notebooks/demo_ipywidgets_es.ipynb (allocate → HTML report, UI in Spanish)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import streamlit as st

from rate_allocator import Institution, RegulatoryRules, allocate
from rate_allocator.adapters.noticias_yaml import YamlNoticiaEntry, load_noticias_yaml
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
DEFAULT_DB_FILE = REPO_ROOT / "data" / "rates.db"
NOTICIAS_YAML_FILE = REPO_ROOT / "data" / "noticias.yaml"
MX_ZONE = ZoneInfo("America/Mexico_City")
DB_URL_ENV = "RATE_ALLOCATOR_DB_URL"


def _resolve_database_url() -> str:
    """Same resolution as ``rate_allocator.persistence.get_database_url`` without importing SQLAlchemy."""
    return os.environ.get(DB_URL_ENV, f"sqlite:///{DEFAULT_DB_FILE}")

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
        f"configuraste `{DB_URL_ENV}` o existe `data/rates.db` por defecto. Ejecuta `scripts/ingest_yaml.py` "
        "y usa **Recargar datos**. "
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
    "noticias_help": (
        "Cambios recientes en tasas nominales por tramo (histórico SCD2). "
        "La columna «Vigente desde» es la fecha de vigencia del nuevo tramo; "
        "«Fecha aplicada» es cuándo se registró el lote en el sistema."
    ),
    "noticias_empty": "No hay cambios de tasa registrados en la BD aún (o la BD está vacía).",
    "noticias_db_unavailable": (
        "No se pudo leer la base de datos (archivo ausente, esquema sin migrar o error de conexión). "
        "Configura `RATE_ALLOCATOR_DB_URL` o crea `data/rates.db` con `scripts/ingest_yaml.py`."
    ),
    "noticias_no_deps": (
        "No hay motor SQL (p. ej. SQLAlchemy) en este despliegue y `data/noticias.yaml` "
        "no tiene entradas o no existe. Añada dependencias o el archivo YAML de noticias."
    ),
    "noticias_yaml_banner": (
        "Origen: `data/noticias.yaml` (demostración). Para historial real de tasas, "
        "configure la BD, ejecute la ingestión y use `RATE_ALLOCATOR_DB_URL` si aplica."
    ),
    "noticias_yaml_after_db_error": (
        "No se pudo leer la base de datos. Se muestran las entradas de `data/noticias.yaml`."
    ),
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


def _dt_mx_label(dt: datetime) -> str:
    """Format a DB timestamp for display in America/Mexico_City."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MX_ZONE).strftime("%Y-%m-%d %H:%M %Z")


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
    """Return DB snapshot or None when DB modules are unavailable or the DB is unreadable."""
    try:
        from rate_allocator.adapters.db_loader import (
            load_institutions_from_db,
            load_regulatory_rules_from_db,
        )
        from rate_allocator.persistence import create_db_engine, session_scope
        from sqlalchemy.exc import SQLAlchemyError
    except ModuleNotFoundError:
        return None

    try:
        engine = create_db_engine(db_url)
        with session_scope(engine) as session:
            institutions = load_institutions_from_db(session)
            rules = load_regulatory_rules_from_db(session, country="MX")
    except SQLAlchemyError:
        return None
    return institutions, rules


def _db_runtime_available() -> bool:
    """True when SQLAlchemy is importable (required for SCD2 noticias from the DB)."""
    try:
        import sqlalchemy  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _noticias_rows_from_db_events(events) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for e in events:
        note = (e.note or "").strip()
        rows.append(
            {
                "Vigente desde": _dt_mx_label(e.effective_from),
                "Fecha aplicada": _dt_mx_label(e.applied_at),
                "Institución": e.institution_name,
                "Tramo": str(e.tier_index + 1),
                "Cambio de tasa": f"{e.old_rate:.2%} → {e.new_rate:.2%}",
                "Origen": e.source or "—",
                "Nota": note or "—",
            }
        )
    return rows


def _noticias_rows_from_yaml(entries: list[YamlNoticiaEntry]) -> list[dict[str, str]]:
    return [
        {
            "Vigente desde": _dt_mx_label(e.effective_from),
            "Fecha aplicada": _dt_mx_label(e.applied_at),
            "Institución": e.institution,
            "Tramo": e.tier_display,
            "Cambio de tasa": f"{e.old_rate:.2%} → {e.new_rate:.2%}",
            "Origen": e.source or "—",
            "Nota": e.note or "—",
        }
        for e in entries
    ]


@st.cache_data(ttl=CACHE_LOAD_TTL_SECONDS, show_spinner="Cargando instituciones y reglas...")
def _load_snapshot(
    _reload_nonce: int,
) -> tuple[list[Institution], RegulatoryRules, str, bool]:
    """Return (institutions, rules, source_key, explicit_db_url_in_env).

    Uses ``RATE_ALLOCATOR_DB_URL`` when set; otherwise ``data/rates.db`` under
    the app root. Does not import ``rate_allocator.persistence`` here so a
    missing SQLAlchemy install still falls back to YAML via ``_try_load_db_snapshot``.
    """
    explicit_db_url_in_env = os.environ.get(DB_URL_ENV) is not None
    db_url = _resolve_database_url()
    db_snapshot = _try_load_db_snapshot(db_url)
    if db_snapshot is None:
        institutions = load_institutions_with_overrides(str(DATA_FILE), {})
        rules = _fallback_rules()
        return institutions, rules, "yaml", explicit_db_url_in_env

    institutions, rules = db_snapshot
    if institutions:
        resolved_rules = rules if rules is not None else _fallback_rules()
        return institutions, resolved_rules, "db", explicit_db_url_in_env
    inst_yaml = load_institutions_with_overrides(str(DATA_FILE), {})
    resolved_rules = rules if rules is not None else _fallback_rules()
    return inst_yaml, resolved_rules, "yaml", explicit_db_url_in_env


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


def _institution_allocation_figure(df: pd.DataFrame, title: str, x_title: str):
    import matplotlib.pyplot as plt

    df_sorted = df.sort_values("monto_q", ascending=True).reset_index(drop=True)
    fig_h = max(3.0, min(7.5, 0.45 * len(df_sorted)))
    fig, ax = plt.subplots(figsize=(10, fig_h), constrained_layout=True)
    ax.barh(df_sorted["institucion"], df_sorted["monto_q"], color="#2563eb")
    ax.set_title(title)
    ax.set_xlabel(x_title)
    ax.grid(axis="x", alpha=0.2)
    for idx, value in enumerate(df_sorted["monto_q"]):
        ax.text(value, idx, f"  {value:,.0f}", va="center", fontsize=10)
    return fig


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

    with st.expander(t["noticias"], expanded=False):
        st.caption(t["noticias_help"])
        yaml_entries = load_noticias_yaml(NOTICIAS_YAML_FILE)
        yaml_rows = _noticias_rows_from_yaml(yaml_entries)
        db_rows: list[dict[str, str]] = []
        db_read_failed = False
        if _db_runtime_available():
            from rate_allocator.persistence import create_db_engine, session_scope
            from rate_allocator.persistence.history import load_recent_tier_rate_changes
            from sqlalchemy.exc import SQLAlchemyError

            try:
                engine = create_db_engine(_resolve_database_url())
                with session_scope(engine) as session:
                    events = load_recent_tier_rate_changes(session, limit=50)
                db_rows = _noticias_rows_from_db_events(events)
            except SQLAlchemyError:
                db_read_failed = True

        if db_rows:
            st.table(pd.DataFrame(db_rows))
        elif db_read_failed and yaml_rows:
            st.info(t["noticias_yaml_after_db_error"])
            st.table(pd.DataFrame(yaml_rows))
        elif db_read_failed:
            st.info(t["noticias_db_unavailable"])
        elif yaml_rows:
            st.info(t["noticias_yaml_banner"])
            st.table(pd.DataFrame(yaml_rows))
        elif _db_runtime_available() and not db_read_failed:
            st.info(t["noticias_empty"])
        else:
            st.info(t["noticias_no_deps"])

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
            "Conexión: `RATE_ALLOCATOR_DB_URL` configurada ✓"
            if hint_db
            else f"Conexión: BD por defecto (`{_resolve_database_url()}`) o YAML si no hay datos"
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
        fig_alloc = _institution_allocation_figure(
            df_chart,
            title=t["chart_alloc_title"],
            x_title=t["chart_tooltip_monto"],
        )
        st.pyplot(fig_alloc, clear_figure=True)

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
        tbl_fmt = pd.DataFrame(
            {
                "Institución": tbl["Institución"],
                "Monto (MXN)": tbl["Monto (MXN)"].map(lambda v: f"${v:,.0f}"),
                "Participación (%)": tbl["Participación (%)"].map(lambda v: f"{v:.1f} %"),
                "Interés bruto (horizon.)": tbl["Interés bruto (horizon.)"].map(
                    lambda v: f"${v:,.2f}"
                ),
                "Comisiones": tbl["Comisiones"].map(lambda v: f"${v:,.2f}"),
                "ISR (estim.)": tbl["ISR (estim.)"].map(lambda v: f"${v:,.2f}"),
                "Retención (estim.)": tbl["Retención (estim.)"].map(lambda v: f"${v:,.2f}"),
                "Contribución neta": tbl["Contribución neta"].map(lambda v: f"${v:,.2f}"),
            }
        )
        st.table(tbl_fmt)

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
