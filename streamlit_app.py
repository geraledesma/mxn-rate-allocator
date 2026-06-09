"""Streamlit app — flujo de 3 pasos minimalista para el usuario promedio."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from rate_allocator import Institution, RegulatoryRules, allocate
from rate_allocator.adapters.noticias_yaml import YamlNoticiaEntry, load_noticias_yaml
from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.yaml_loader import load_institutions_with_overrides

REPO_ROOT = Path(__file__).resolve().parent
DATA_FILE = REPO_ROOT / "data" / "sample1.yaml"
RULES_FILE = REPO_ROOT / "data" / "regulatory_rules.mx.yaml"
DEFAULT_DB_FILE = REPO_ROOT / "data" / "rates.db"
NOTICIAS_YAML_FILE = REPO_ROOT / "data" / "noticias.yaml"
MX_ZONE = ZoneInfo("America/Mexico_City")
DB_URL_ENV = "RATE_ALLOCATOR_DB_URL"
NOTICIAS_LIMIT_ENV = "RATE_ALLOCATOR_NOTICIAS_LIMIT"
NOTICIAS_DEFAULT_LIMIT = 2_000
CACHE_TTL = 120

TOTAL_MIN = 1_000
TOTAL_MAX = 3_000_000
TOTAL_DEFAULT = 100_000
HORIZON_YEARS = 1.0

TIPO_LABEL = {
    "sofipo": "SOFIPO",
    "banco": "Banco",
    "none": "Fintech / Gobierno",
}

_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _resolve_database_url() -> str:
    return os.environ.get(DB_URL_ENV, f"sqlite:///{DEFAULT_DB_FILE}")


def _db_runtime_available() -> bool:
    try:
        import sqlalchemy  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def _try_load_db_snapshot(
    db_url: str,
) -> tuple[list[Institution], RegulatoryRules | None] | None:
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
    except Exception:
        return None
    return institutions, rules


@st.cache_data(ttl=CACHE_TTL, show_spinner="Cargando instituciones…")
def _load_snapshot(_nonce: int) -> tuple[list[Institution], RegulatoryRules, str]:
    db_url = _resolve_database_url()
    snapshot = _try_load_db_snapshot(db_url)
    fallback_rules = load_regulatory_rules_from_yaml(str(RULES_FILE))
    if snapshot:
        insts, rules = snapshot
        if insts:
            return insts, rules or fallback_rules, "db"
    insts = load_institutions_with_overrides(str(DATA_FILE), {})
    return insts, fallback_rules, "yaml"


def _constraint_text(inst: Institution) -> str:
    """Human-readable condition summary for Step 2 institution cards."""
    texts = []
    for tier in inst.tiers:
        for c in tier.constraints:
            if not c.active:
                continue
            if c.benefit == "membership_plan":
                texts.append(f"membresía ${c.cost:,.0f}/mes")
            elif c.benefit == "high_rate_tier" and c.cost <= 10:
                texts.append("requiere 1 compra al mes")
            elif c.benefit == "high_rate_tier" and c.cost > 10:
                texts.append(f"depositar ${c.cost:,.0f}/mes")
    return " · ".join(texts) if texts else "sin condición"


def _tier_summary(inst: Institution) -> str:
    """One-liner tier summary for Step 2: '15% hasta $10k · 7.5% el resto'."""
    parts = []
    for i, tier in enumerate(inst.tiers):
        if tier.limit == float("inf"):
            parts.append(f"{tier.rate:.0%} el resto")
        else:
            parts.append(f"{tier.rate:.0%} hasta ${tier.limit:,.0f}")
    return " · ".join(parts)


def _coverage_text(inst: Institution) -> str:
    tipo = (inst.institution_type or "").lower()
    if tipo == "banco":
        return "Cobertura IPAB"
    if tipo == "sofipo":
        return "Cobertura Prosofipo"
    return ""


def _bar_chart(allocations: dict[str, list[float]]) -> plt.Figure:
    data = {name: sum(amounts) for name, amounts in allocations.items() if sum(amounts) > 1}
    if not data:
        return None
    fig, ax = plt.subplots(figsize=(8, max(2, len(data) * 0.6)), constrained_layout=True)
    names = list(data.keys())
    values = [data[n] for n in names]
    bars = ax.barh(names, values, color="#00c37a", height=0.5)
    ax.bar_label(bars, labels=[f"${v:,.0f}" for v in values], padding=6, fontsize=9)
    ax.set_xlabel("MXN")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.invert_yaxis()
    return fig


def _date_to_calendar_es(d: date) -> str:
    return f"{d.day} de {_MONTHS_ES[d.month - 1]} de {d.year}"


def _vigencia_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        return date(dt.year, dt.month, dt.day)
    return dt.astimezone(timezone.utc).date()


def _noticias_paragraphs(events: list) -> list[str]:
    return [
        (
            f"{e.institution_name} (Tramo {e.tier_index + 1}): "
            f"efectivo el {_date_to_calendar_es(_vigencia_date(e.effective_from))}, "
            f"tasa ajustada del {e.old_rate * 100:.2f}% al {e.new_rate * 100:.2f}%."
        )
        for e in events
    ]


def _yaml_noticias_paragraphs(entries: list[YamlNoticiaEntry]) -> list[str]:
    def sort_key(e: YamlNoticiaEntry) -> tuple:
        ef = e.effective_from.astimezone(timezone.utc) if e.effective_from.tzinfo else e.effective_from.replace(tzinfo=timezone.utc)
        return (-ef.timestamp(),)
    return [
        (
            f"{e.institution} (Tramo {e.tier_display}): "
            f"efectivo el {_date_to_calendar_es(_vigencia_date(e.effective_from))}, "
            f"tasa ajustada del {e.old_rate * 100:.2f}% al {e.new_rate * 100:.2f}%."
        )
        for e in sorted(entries, key=sort_key)
    ]


def _render_noticias() -> None:
    yaml_entries = load_noticias_yaml(NOTICIAS_YAML_FILE)
    paragraphs: list[str] = []

    if _db_runtime_available():
        try:
            from rate_allocator.persistence import create_db_engine, session_scope
            from rate_allocator.persistence.history import load_recent_tier_rate_changes
            engine = create_db_engine(_resolve_database_url())
            with session_scope(engine) as session:
                events = load_recent_tier_rate_changes(session, limit=NOTICIAS_DEFAULT_LIMIT)
            paragraphs = _noticias_paragraphs(events)
        except Exception:
            pass

    if not paragraphs:
        paragraphs = _yaml_noticias_paragraphs(yaml_entries)

    if paragraphs:
        st.markdown("\n\n".join(f"{i}. {p}" for i, p in enumerate(paragraphs, 1)))
    else:
        st.info("Sin cambios de tasa registrados aún.")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Rate Allocator MX",
        page_icon="💰",
        layout="centered",
    )

    # session state
    if "reload_nonce" not in st.session_state:
        st.session_state.reload_nonce = 0
    if "total_mxn" not in st.session_state:
        st.session_state.total_mxn = TOTAL_DEFAULT
    if "calculated" not in st.session_state:
        st.session_state.calculated = False

    institutions, regulatory_rules, source_key = _load_snapshot(
        st.session_state.reload_nonce
    )

    # ── header ───────────────────────────────────────────────────────────────
    st.title("💰 Rate Allocator MX")
    st.markdown(
        "Descubre dónde poner tu dinero para ganar más — "
        "gratis, en segundos, con cobertura institucional garantizada."
    )
    st.divider()

    # ── paso 1 ───────────────────────────────────────────────────────────────
    st.markdown("### Paso 1 — ¿Cuánto dinero quieres invertir?")

    col_slider, col_input = st.columns([3, 1])
    with col_slider:
        slider_val = st.slider(
            "Monto (MXN)",
            min_value=TOTAL_MIN,
            max_value=TOTAL_MAX,
            value=st.session_state.total_mxn,
            step=1_000,
            format="$%d",
            label_visibility="collapsed",
            key="_slider",
        )
    with col_input:
        input_val = st.number_input(
            "Monto exacto",
            min_value=TOTAL_MIN,
            max_value=TOTAL_MAX,
            value=slider_val,
            step=1_000,
            label_visibility="collapsed",
            key="_input",
        )

    total = input_val
    st.session_state.total_mxn = total
    st.caption(f"**${total:,.0f} MXN** seleccionados")

    st.divider()

    # ── paso 2 ───────────────────────────────────────────────────────────────
    st.markdown("### Paso 2 — ¿Dónde lo quieres invertir?")
    st.caption(
        "Todas las instituciones están seleccionadas por default. "
        "Desactiva las que no puedas o no quieras cumplir."
    )

    selected_institutions: list[Institution] = []
    for inst in institutions:
        tipo = TIPO_LABEL.get((inst.institution_type or "").lower(), "")
        condition = _constraint_text(inst)
        tiers_line = _tier_summary(inst)
        coverage = _coverage_text(inst)

        with st.container(border=True):
            col_check, col_info = st.columns([0.06, 0.94])
            with col_check:
                checked = st.checkbox(
                    label=inst.name,
                    value=True,
                    key=f"inst_{inst.name}",
                    label_visibility="collapsed",
                )
            with col_info:
                badge = f"`{tipo}`" if tipo else ""
                st.markdown(f"**{inst.name}** {badge}")
                st.caption(f"{tiers_line}")
                cond_icon = "⚠️" if condition != "sin condición" else "✅"
                st.caption(f"{cond_icon} {condition}" + (f"  ·  {coverage}" if coverage else ""))

        if checked:
            selected_institutions.append(inst)

    st.divider()

    # ── botón calcular ────────────────────────────────────────────────────────
    if not selected_institutions:
        st.warning("Selecciona al menos una institución para continuar.")
        return

    btn_label = "🔄 Recalcular mi plan" if st.session_state.calculated else "✅ Calcular mi plan"
    if st.button(btn_label, type="primary", use_container_width=True):
        st.session_state.calculated = True

    if not st.session_state.calculated:
        return

    # ── paso 3 ───────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### Paso 3 — Tu plan óptimo")

    result = allocate(
        total=total,
        institutions=selected_institutions,
        horizon_years=HORIZON_YEARS,
        periods_per_year=365,
        regulatory_rules=regulatory_rules,
    )

    if result.total_allocated <= 1e-9:
        st.warning("No se pudo generar una asignación con las instituciones seleccionadas.")
        return

    # hero metrics
    col1, col2 = st.columns(2)
    col1.metric(
        label="Rendimiento esperado (1 año)",
        value=f"${result.expected_return:,.0f} MXN",
    )
    col2.metric(
        label="Tasa efectiva",
        value=f"{result.effective_rate:.2%} anual",
    )

    st.divider()

    # institution cards
    st.markdown("#### ¿Cómo distribuirlo?")
    for inst in selected_institutions:
        tier_amounts = result.allocations.get(inst.name, [])
        total_inst = sum(tier_amounts)
        if total_inst < 1:
            continue

        inst_interest = sum(
            amt * tier.rate
            for amt, tier in zip(tier_amounts, inst.tiers)
        )

        with st.container(border=True):
            st.markdown(f"**{inst.name}** — deposita **${total_inst:,.0f} MXN**")
            for i, (amt, tier) in enumerate(zip(tier_amounts, inst.tiers), 1):
                if amt < 1:
                    continue
                limit_label = (
                    f"hasta ${tier.limit:,.0f}"
                    if tier.limit != float("inf")
                    else "el resto"
                )
                st.markdown(
                    f"&nbsp;&nbsp;&nbsp;`Tramo {i}` &nbsp; ${amt:,.0f} ({limit_label}) &nbsp;→&nbsp; **{tier.rate:.2%}**",
                    unsafe_allow_html=True,
                )
            coverage = _coverage_text(inst)
            footer = f"Ganarás aprox. **${inst_interest:,.0f} MXN**"
            if coverage:
                footer += f"  ·  {coverage}"
            st.caption(footer)

    st.divider()

    # bar chart
    st.markdown("#### Distribución del capital")
    fig = _bar_chart(result.allocations)
    if fig:
        st.pyplot(fig, clear_figure=True)

    # ── noticias (al final) ──────────────────────────────────────────────────
    st.divider()
    with st.expander("📰 Noticias — cambios recientes de tasas"):
        st.caption(
            "Historial de cambios de tasa registrados en la base de datos (SCD2). "
            "«Efectivo el…» indica cuándo entró en vigor la nueva tasa."
        )
        _render_noticias()

    # fuente
    fuente = "base de datos" if source_key == "db" else "archivo YAML (demo)"
    st.caption(f"Fuente de tasas: {fuente} · Horizonte: 1 año · Tasas nominales anuales")
    if st.button("🔁 Recargar datos", help="Invalida la caché y vuelve a leer las tasas."):
        st.cache_data.clear()
        st.session_state.reload_nonce += 1
        st.session_state.calculated = False
        st.rerun()


if __name__ == "__main__":
    main()
