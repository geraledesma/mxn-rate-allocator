"""Streamlit app — split-screen wizard: left = inputs, right = live results."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
DB_URL_ENV = "RATE_ALLOCATOR_DB_URL"
NOTICIAS_DEFAULT_LIMIT = 2_000
CACHE_TTL = 120

TOTAL_MIN = 1_000
TOTAL_MAX = 3_000_000
TOTAL_DEFAULT = 100_000
HORIZON_YEARS = 1.0

TIPO_LABEL = {
    "sofipo": "SOFIPO",
    "banco": "Banco",
    "none": "Fintech / Gob.",
}

_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# Table column proportions for Paso 2: [checkbox, name, tipo/coverage, tiers, condition]
_COL_W = [0.05, 0.20, 0.18, 0.32, 0.25]


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


def _best_rate(inst: Institution) -> float:
    return max(t.rate for t in inst.tiers)


def _constraint_lines(inst: Institution) -> list[str]:
    texts = []
    for tier in inst.tiers:
        for c in tier.constraints:
            if not c.active:
                continue
            if c.benefit == "membership_plan":
                texts.append(f"Membresía ${c.cost:,.0f}/mes")
            elif c.benefit == "high_rate_tier" and c.cost <= 10:
                texts.append("1 compra al mes")
            elif c.benefit == "high_rate_tier" and c.cost > 10:
                texts.append(f"Gastar ${c.cost:,.0f}/mes")
    return texts if texts else ["Sin condición"]


def _tier_lines(inst: Institution) -> list[str]:
    lines = []
    for tier in inst.tiers:
        if tier.limit == float("inf"):
            lines.append(f"{tier.rate:.0%} — sin límite")
        else:
            lines.append(f"{tier.rate:.0%} hasta ${tier.limit:,.0f}")
    return lines


def _coverage_text(inst: Institution) -> str:
    tipo = (inst.institution_type or "").lower()
    if tipo == "banco":
        return "IPAB"
    if tipo == "sofipo":
        return "Prosofipo"
    return "—"


def _bar_chart(allocations: dict[str, list[float]]) -> plt.Figure | None:
    data = {name: sum(amounts) for name, amounts in allocations.items() if sum(amounts) > 1}
    if not data:
        return None
    # Sort bars largest to smallest (top = largest)
    sorted_items = sorted(data.items(), key=lambda x: x[1])
    names = [i[0] for i in sorted_items]
    values = [i[1] for i in sorted_items]
    fig, ax = plt.subplots(figsize=(6, max(2, len(data) * 0.55)), constrained_layout=True)
    bars = ax.barh(names, values, color="#00c37a", height=0.5)
    ax.bar_label(bars, labels=[f"${v:,.0f}" for v in values], padding=6, fontsize=9)
    ax.set_xlabel("MXN")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
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
    paragraphs: list[tuple[float, str]] = []  # (timestamp, text)

    # DB events
    if _db_runtime_available():
        try:
            from rate_allocator.persistence import create_db_engine, session_scope
            from rate_allocator.persistence.history import load_recent_tier_rate_changes
            engine = create_db_engine(_resolve_database_url())
            with session_scope(engine) as session:
                events = load_recent_tier_rate_changes(session, limit=NOTICIAS_DEFAULT_LIMIT)
            for e in events:
                ef = e.effective_from
                ts = ef.timestamp() if ef.tzinfo else ef.replace(tzinfo=timezone.utc).timestamp()
                text = (
                    f"{e.institution_name} (Tramo {e.tier_index + 1}): "
                    f"efectivo el {_date_to_calendar_es(_vigencia_date(ef))}, "
                    f"tasa ajustada del {e.old_rate * 100:.2f}% al {e.new_rate * 100:.2f}%."
                )
                paragraphs.append((ts, text))
        except Exception:
            pass

    # YAML entries — always merged (supplement DB with manually curated history)
    yaml_entries = load_noticias_yaml(NOTICIAS_YAML_FILE)
    db_keys = {p[1][:40] for p in paragraphs}  # rough dedup by text prefix
    for e in yaml_entries:
        ef = e.effective_from
        ts = ef.astimezone(timezone.utc).timestamp() if ef.tzinfo else ef.replace(tzinfo=timezone.utc).timestamp()
        text = (
            f"{e.institution} (Tramo {e.tier_display}): "
            f"efectivo el {_date_to_calendar_es(_vigencia_date(ef))}, "
            f"tasa ajustada del {e.old_rate * 100:.2f}% al {e.new_rate * 100:.2f}%."
        )
        if text[:40] not in db_keys:
            paragraphs.append((ts, text))

    if not paragraphs:
        st.info("Sin cambios de tasa registrados aún.")
        return

    paragraphs.sort(key=lambda x: x[0], reverse=True)
    st.markdown("\n\n".join(f"{i}. {p}" for i, (_, p) in enumerate(paragraphs, 1)))


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Rate Allocator MX",
        page_icon="💰",
        layout="wide",
    )

    if "reload_nonce" not in st.session_state:
        st.session_state.reload_nonce = 0
    if "total_mxn" not in st.session_state:
        st.session_state.total_mxn = TOTAL_DEFAULT

    institutions, regulatory_rules, source_key = _load_snapshot(
        st.session_state.reload_nonce
    )
    institutions_sorted = sorted(institutions, key=_best_rate, reverse=True)

    # ── header ───────────────────────────────────────────────────────────────
    st.title("💰 Rate Allocator MX")
    st.markdown(
        "**Maximiza el rendimiento de tus ahorros** distribuyéndolos de forma inteligente "
        "entre bancos, SOFIPOs e instrumentos de gobierno — en segundos, sin costo y con "
        "cobertura institucional garantizada (IPAB / Prosofipo)."
    )
    st.markdown(
        "En México, la mayoría de las personas deja su dinero en cuentas que pagan 2–4% "
        "cuando existen opciones reguladas y seguras que pagan 10–15%. Esta herramienta "
        "existe para cerrar esa brecha: es completamente gratuita para cualquier monto, "
        "porque la inclusión financiera no debería depender de cuánto tienes."
    )
    st.divider()

    # ── split layout ─────────────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 1], gap="large")

    # ════════════════════════════════════════════════════════════════════════
    # LEFT — Paso 1 + Paso 2
    # ════════════════════════════════════════════════════════════════════════
    with col_left:
        # ── paso 1 ───────────────────────────────────────────────────────────
        st.markdown("#### Paso 1 — ¿Cuánto quieres invertir?")
        st.caption("Indica el monto total que deseas distribuir. Puedes ajustarlo en cualquier momento.")

        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            st.slider(
                "Monto",
                min_value=TOTAL_MIN,
                max_value=TOTAL_MAX,
                step=1_000,
                format="$%d",
                label_visibility="collapsed",
                key="total_mxn",
            )
        with col_input:
            typed = st.number_input(
                "Monto exacto",
                min_value=TOTAL_MIN,
                max_value=TOTAL_MAX,
                value=st.session_state.total_mxn,
                step=1_000,
                label_visibility="collapsed",
            )
            if typed != st.session_state.total_mxn:
                st.session_state.total_mxn = typed
                st.rerun()

        total = st.session_state.total_mxn
        st.caption(f"**${total:,.0f} MXN** seleccionados")

        st.divider()

        # ── paso 2 ───────────────────────────────────────────────────────────
        st.markdown("#### Paso 2 — ¿Dónde invertirlo?")
        st.caption("Selecciona las instituciones en las que estás dispuesto a abrir cuenta. Desactiva las que tengan condiciones que no puedas o no quieras cumplir.")

        # Toggle button — label flips based on current state
        all_checked = all(
            st.session_state.get(f"inst_{inst.name}", True)
            for inst in institutions_sorted
        )
        col_caption, col_toggle = st.columns([0.65, 0.35])
        with col_caption:
            st.caption("Ordenadas de mayor a menor tasa.")
        with col_toggle:
            toggle_label = "☐ Deseleccionar todo" if all_checked else "☑ Seleccionar todo"
            if st.button(toggle_label, use_container_width=True):
                new_val = not all_checked
                for inst in institutions_sorted:
                    st.session_state[f"inst_{inst.name}"] = new_val
                st.rerun()

        # Table header
        h_ck, h_name, h_tipo, h_tiers, h_cond = st.columns(_COL_W)
        h_name.markdown("<small><b>Institución</b></small>", unsafe_allow_html=True)
        h_tipo.markdown("<small><b>Tipo / Cobertura</b></small>", unsafe_allow_html=True)
        h_tiers.markdown("<small><b>Tasa por tramos</b></small>", unsafe_allow_html=True)
        h_cond.markdown("<small><b>Condición</b></small>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0 6px'>", unsafe_allow_html=True)

        selected_institutions: list[Institution] = []

        for inst in institutions_sorted:
            tipo_label = TIPO_LABEL.get((inst.institution_type or "").lower(), "—")
            coverage = _coverage_text(inst)
            tier_lines = _tier_lines(inst)
            cond_lines = _constraint_lines(inst)

            col_ck, col_name, col_tipo, col_tiers, col_cond = st.columns(_COL_W)

            with col_ck:
                if f"inst_{inst.name}" not in st.session_state:
                    st.session_state[f"inst_{inst.name}"] = True
                checked = st.checkbox(
                    label=inst.name,
                    key=f"inst_{inst.name}",
                    label_visibility="collapsed",
                )
            with col_name:
                st.markdown(f"**{inst.name}**")
            with col_tipo:
                st.html(f"<small>{tipo_label}<br><span style='color:#888'>{coverage}</span></small>")
            with col_tiers:
                st.html(f"<small style='line-height:1.8'>{'<br>'.join(tier_lines)}</small>")
            with col_cond:
                icon = "⚠️" if cond_lines != ["Sin condición"] else "✅"
                lines_with_icon = [f"{icon} {cond_lines[0]}"] + cond_lines[1:]
                st.html(f"<small style='line-height:1.8'>{'<br>'.join(lines_with_icon)}</small>")

            if checked:
                selected_institutions.append(inst)

            st.markdown("<hr style='margin:2px 0'>", unsafe_allow_html=True)

        st.divider()
        fuente = "base de datos" if source_key == "db" else "archivo YAML (demo)"
        st.caption(f"Fuente: {fuente} · Horizonte: 1 año · Tasas nominales anuales")
        if st.button("🔁 Recargar datos", help="Invalida la caché y vuelve a leer las tasas."):
            st.cache_data.clear()
            st.session_state.reload_nonce += 1
            st.rerun()

    # ════════════════════════════════════════════════════════════════════════
    # RIGHT — Paso 3 (live, auto-updates)
    # ════════════════════════════════════════════════════════════════════════
    with col_right:
        st.markdown("#### Tu plan óptimo")

        if not selected_institutions:
            st.info("Selecciona al menos una institución para ver tu plan.")
        else:
            result = allocate(
                total=total,
                institutions=selected_institutions,
                horizon_years=HORIZON_YEARS,
                periods_per_year=365,
                regulatory_rules=regulatory_rules,
            )

            if result.total_allocated <= 1e-9:
                st.warning("No se pudo generar una asignación con las instituciones seleccionadas.")
            else:
                # hero metrics
                mc1, mc2 = st.columns(2)
                mc1.metric(
                    label="Rendimiento esperado (1 año)",
                    value=f"${result.expected_return:,.0f} MXN",
                )
                mc2.metric(
                    label="Tasa efectiva",
                    value=f"{result.effective_rate:.2%} anual",
                )

                # bar chart
                fig = _bar_chart(result.allocations)
                if fig:
                    st.pyplot(fig, clear_figure=True)

                st.divider()

                # Build result rows sorted by amount deposited descending
                inst_results = []
                for inst in selected_institutions:
                    tier_amounts = result.allocations.get(inst.name, [])
                    total_inst = sum(tier_amounts)
                    if total_inst < 1:
                        continue
                    inst_interest = sum(
                        amt * tier.rate
                        for amt, tier in zip(tier_amounts, inst.tiers)
                    )
                    inst_results.append((inst, tier_amounts, total_inst, inst_interest))

                inst_results.sort(key=lambda x: x[2], reverse=True)

                st.markdown("#### Paso 3 — ¿Cómo distribuirlo?")
                st.caption("Distribución óptima para maximizar tu rendimiento respetando los límites de cobertura institucional.")
                for inst, tier_amounts, total_inst, inst_interest in inst_results:
                    with st.container(border=True):
                        st.markdown(f"**{inst.name}** — deposita **${total_inst:,.0f} MXN**")
                        for i, (amt, tier) in enumerate(zip(tier_amounts, inst.tiers), 1):
                            if amt < 1:
                                continue
                            limit_label = (
                                f"hasta ${tier.limit:,.0f}"
                                if tier.limit != float("inf")
                                else "sin límite"
                            )
                            st.html(
                                f"<div style='margin:2px 0 2px 12px;font-size:0.9em'>"
                                f"<code>Tramo {i}</code>&nbsp; "
                                f"${amt:,.0f} ({limit_label}) &rarr; <b>{tier.rate:.2%}</b>"
                                f"</div>"
                            )
                        cond_lines = _constraint_lines(inst)
                        coverage_full = _coverage_text(inst)
                        footer_parts = [f"Ganarás aprox. **${inst_interest:,.0f} MXN**"]
                        if coverage_full and coverage_full != "—":
                            footer_parts.append(f"Cobertura {coverage_full}")
                        if cond_lines != ["Sin condición"]:
                            footer_parts.append("⚠️ " + " · ".join(cond_lines))
                        st.caption("  ·  ".join(footer_parts))

    # ════════════════════════════════════════════════════════════════════════
    # FULL-WIDTH FOOTER — Noticias
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("### 📰 Noticias — cambios recientes de tasas")
    st.caption("«Efectivo el…» indica cuándo entró en vigor la nueva tasa.")
    _render_noticias()


if __name__ == "__main__":
    main()
