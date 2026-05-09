"""Streamlit demo: mirrors notebooks/demo_ipywidgets_es.ipynb (allocate → HTML report, UI in Spanish)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from rate_allocator import Institution, RegulatoryRules, allocate
from rate_allocator.adapters.db_loader import load_institutions_from_db, load_regulatory_rules_from_db
from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.yaml_loader import load_institutions_with_overrides
from rate_allocator.persistence import DB_URL_ENV, create_db_engine, session_scope
from rate_allocator.persistence.history import load_recent_tier_rate_changes
from rate_allocator.workflows.interactive_report import (
    build_allocation_combo_figure,
    build_interactive_report_html,
    build_portfolio_path_figure,
)

REPO_ROOT = Path(__file__).resolve().parent
DATA_FILE = REPO_ROOT / "data" / "sample1.yaml"
RULES_FILE = REPO_ROOT / "data" / "regulatory_rules.mx.yaml"
MX_ZONE = ZoneInfo("America/Mexico_City")

TOTAL_MIN = 1
TOTAL_MAX = 1_200_000
TOTAL_DEFAULT = 100_000
CACHE_LOAD_TTL_SECONDS = 120

STRINGS = {
    "page_title": "Rate Allocator",
    "title": "Rate Allocator: demo interactivo",
    "caption": (
        "Elige instituciones y el total en MXN (deslizador o campo numérico, pasos de 100). "
        "Las tasas y comisiones salen del archivo YAML de ejemplo o de la base de datos si configuraste una. "
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
    "reload": "Recargar datos",
    "noticias": "Noticias",
    "noticias_help": "Cambios recientes en tasas nominales por tramo (histórico SCD2 en la BD).",
    "noticias_empty": "No hay cambios de tasa registrados en la BD aún.",
    "noticias_no_db": "Las noticias de tasas requieren una base de datos ingestada.",
    "chart_section": "Asignación de capital por institución",
    "path_section": "Trayectoria del portafolio",
    "pie_warn_empty": "No hay principal asignado para el gráfico circular.",
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


@st.cache_data(ttl=CACHE_LOAD_TTL_SECONDS, show_spinner="Cargando instituciones y reglas...")
def _load_snapshot(
    _reload_nonce: int,
) -> tuple[list[Institution], RegulatoryRules, str, bool]:
    """Return (institutions, rules, source_key_db_or_yaml, db_url_was_set).

    _reload_nonce bumps when the user clears cache so reload takes effect immediately.
    """
    db_url = os.environ.get(DB_URL_ENV)
    if not db_url:
        institutions = load_institutions_with_overrides(str(DATA_FILE), {})
        rules = _fallback_rules()
        return institutions, rules, "yaml", False

    engine = create_db_engine(db_url)
    with session_scope(engine) as session:
        institutions = load_institutions_from_db(session)
        rules = load_regulatory_rules_from_db(session, country="MX")
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

    if db_configured:
        with st.expander(t["noticias"], expanded=False):
            st.caption(t["noticias_help"])
            db_url = os.environ.get(DB_URL_ENV)
            if not db_url:
                st.info(t["noticias_no_db"])
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
        # Noticias: only when DATABASE_URL configured (tier history lives in DB)
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
    institution_totals = [
        (name, sum(amounts))
        for name, amounts in result.allocations.items()
        if sum(amounts) > 0
    ]

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
