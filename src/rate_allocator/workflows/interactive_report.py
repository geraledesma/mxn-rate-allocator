"""Reusable interactive report helpers for notebook and future HTTP views."""

from __future__ import annotations

import base64
import html as html_mod
import io
from typing import Literal

from rate_allocator.core.finance.costs import tier_activation_cost
from rate_allocator.core.finance.rates import (
    discrete_compounding_accumulation_factor,
    portfolio_value_path,
)
from rate_allocator.core.finance.taxes import estimated_isr_tax_over_horizon
from rate_allocator.domain.models import AllocationResult, Institution, RegulatoryRules
from rate_allocator.reporting.visuals import plot_net_interest_by_tranche_stacked

ReportLocale = Literal["en", "es"]


def _report_strings(locale: ReportLocale) -> dict[str, str]:
    if locale == "es":
        return {
            "summary": (
                "{total:,.0f} MXN a asignar  ·  "
                "rendimiento efectivo al horizonte {eff_pct}  ·  "
                "rendimiento esperado al horizonte ${exp_ret:,.2f}"
            ),
            "col_institution": "Institución",
            "col_tier": "Tramo",
            "col_principal": "Principal",
            "col_nominal_rate": "Tasa nominal",
            "col_gross_compound": "Rendimiento bruto (compuesto)",
            "col_fees_horizon": "Comisiones (restricciones + impuesto, horizonte)",
            "col_net_nominal": "Rendimiento neto nominal",
            "col_net_real": "Rendimiento neto real",
            "h4_tranche": "Por tramo (rendimiento al horizonte, MXN salvo tasa)",
            "h4_fee_notes": "Notas de comisiones ([n] en columna de comisiones)",
            "fee_note_monthly": (
                "  [{idx}] {inst} gasto mensual ${cost:,.2f}/mes "
                "(imputado al total de horizonte en rendimiento neto)"
            ),
            "fee_note_onetime": "  [{idx}] {inst} {ctype} ${cost:,.2f} (pago único al fondear)",
            "fee_notes_empty": "  — Sin filas de comisiones; el neto equivale al bruto por tramo.",
            "fee_notes_footer": (
                "  Las comisiones incluyen ISR estimado anual sobre interés real; "
                "la retención se informa aparte."
            ),
            "h4_charts": "Gráficos",
            "pie_title": "Principal por institución",
            "tranche_chart_title": "Interés neto por tramo (MXN/año)",
            "tranche_chart_ylabel": "MXN/año",
            "tranche_gross_label": "Interés bruto (anual simple)",
            "tranche_fees_label": "Comisiones + impuestos (anualizado)",
            "tranche_empty_text": "Sin tramos financiados",
            "path_legend_compound": "Capitalización diaria discreta (m=365)",
            "path_legend_simple": "Lineal simple (tasa × día/365)",
            "path_xlabel": "Día calendario",
            "path_ylabel": "Valor del portafolio (MXN)",
            "path_title": "Asignación final: compuesto vs simple en 1 año",
            "pandas_required": "<p>Se requiere pandas para la tabla del informe.</p>",
            "matplotlib_required": "<p>Se requiere matplotlib para los gráficos.</p>",
            "img_alt_combo": "principal-interes-neto",
            "img_alt_path": "trayectoria-valor",
        }
    return {
        "summary": (
            "{total:,.0f} MXN to allocate  ·  "
            "effective horizon yield {eff_pct}  ·  "
            "expected return over horizon ${exp_ret:,.2f}"
        ),
        "col_institution": "Institution",
        "col_tier": "Tier",
        "col_principal": "Principal",
        "col_nominal_rate": "Nominal rate",
        "col_gross_compound": "Gross return (compound)",
        "col_fees_horizon": "Fees (constraints + tax, horizon)",
        "col_net_nominal": "Net return nominal",
        "col_net_real": "Net return real",
        "h4_tranche": "By tranche (horizon return, MXN except rate)",
        "h4_fee_notes": "Fee notes ([n] in Fees column)",
        "fee_note_monthly": (
            "  [{idx}] {inst} monthly_expense ${cost:,.2f}/month "
            "(charged as horizon total in net return)"
        ),
        "fee_note_onetime": "  [{idx}] {inst} {ctype} ${cost:,.2f} (one-time when funded)",
        "fee_notes_empty": "  — No fee rows; net equals gross for each tranche.",
        "fee_notes_footer": (
            "  Taxes in Fees are estimated annual ISR over real interest; "
            "withholding is reported separately."
        ),
        "h4_charts": "Charts",
        "pie_title": "Principal by institution",
        "tranche_chart_title": "Net interest by tranche (MXN/yr)",
        "tranche_chart_ylabel": "MXN/yr",
        "tranche_gross_label": "Gross interest (simple annual)",
        "tranche_fees_label": "Fees + taxes (annualized)",
        "tranche_empty_text": "No funded tranches",
        "path_legend_compound": "Discrete daily compounding (m=365)",
        "path_legend_simple": "Simple linear (rate × day/365)",
        "path_xlabel": "Calendar day",
        "path_ylabel": "Portfolio value (MXN)",
        "path_title": "Final allocation: compounding vs simple over 1 year",
        "pandas_required": "<p>Pandas is required to render the tabular report output.</p>",
        "matplotlib_required": "<p>Matplotlib is required to render charts.</p>",
        "img_alt_combo": "principal-net",
        "img_alt_path": "path",
    }


def build_interactive_report_html(
    result: AllocationResult,
    institutions: list[Institution],
    *,
    total: float,
    horizon_years: float = 1.0,
    periods_per_year: int = 365,
    regulatory_rules: RegulatoryRules | None = None,
    locale: ReportLocale = "en",
    embed_charts: bool = True,
) -> str:
    """Build the HTML fragment displayed by the interactive notebook."""
    rules = regulatory_rules or RegulatoryRules()
    msgs = _report_strings(locale)
    raw_rows, footnote_lines, institution_totals = _build_report_rows(
        result, institutions, horizon_years, periods_per_year, rules
    )
    parts: list[str] = ['<div style="max-width:960px">']

    summary = msgs["summary"].format(
        total=total,
        eff_pct=f"{result.effective_rate:.2%}",
        exp_ret=result.expected_return,
    )
    parts.append(f"<pre>{html_mod.escape(summary)}</pre>")

    if raw_rows:
        parts.extend(_rows_table_and_footnotes(raw_rows, footnote_lines, msgs))
        if embed_charts:
            parts.extend(
                _charts_html(
                    result,
                    institutions,
                    institution_totals,
                    horizon_years,
                    rules,
                    msgs,
                    locale=locale,
                    periods_per_year=periods_per_year,
                )
            )

    parts.append("</div>")
    return "\n".join(parts)


def build_allocation_combo_figure(
    result: AllocationResult,
    institutions: list[Institution],
    institution_totals: list[tuple[str, float]],
    *,
    horizon_years: float = 1.0,
    periods_per_year: int = 365,
    regulatory_rules: RegulatoryRules | None = None,
    locale: ReportLocale = "en",
):
    """Matplotlib Figure: principal pie + net interest/tranche bars (1×2 subplot)."""
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "matplotlib is required for build_allocation_combo_figure"
        ) from e

    rules = regulatory_rules or RegulatoryRules()
    msgs = _report_strings(locale)
    names = [name for name, _amount in institution_totals]
    values = [float(amount) for _name, amount in institution_totals]

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(10, 4),
        gridspec_kw={"width_ratios": [1, 1], "wspace": 0.25},
        constrained_layout=True,
    )
    axes[0].set_title(msgs["pie_title"])
    if sum(values) <= 0:
        axes[0].text(
            0.5,
            0.5,
            "—",
            ha="center",
            va="center",
            transform=axes[0].transAxes,
        )
    else:
        axes[0].pie(values, labels=names, autopct="%1.1f%%", startangle=90)
    plot_net_interest_by_tranche_stacked(
        axes[1],
        result,
        institutions,
        horizon_years=horizon_years,
        regulatory_rules=rules,
        title=msgs["tranche_chart_title"],
        ylabel=msgs["tranche_chart_ylabel"],
        gross_bar_label=msgs["tranche_gross_label"],
        fees_bar_label=msgs["tranche_fees_label"],
        empty_text=msgs["tranche_empty_text"],
    )
    return fig


def build_portfolio_path_figure(
    result: AllocationResult,
    institutions: list[Institution],
    *,
    max_days: int = 365,
    periods_per_year: int = 365,
    locale: ReportLocale = "en",
):
    """Matplotlib Figure: portfolio value compound vs simple path."""
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "matplotlib is required for build_portfolio_path_figure"
        ) from e

    msgs = _report_strings(locale)
    days, compound_vals, simple_vals = portfolio_value_path(
        result, institutions, max_days=max_days, periods_per_year=periods_per_year
    )
    fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    ax.plot(days, compound_vals, label=msgs["path_legend_compound"])
    ax.plot(days, simple_vals, label=msgs["path_legend_simple"])
    ax.set_xlabel(msgs["path_xlabel"])
    ax.set_ylabel(msgs["path_ylabel"])
    ax.set_title(msgs["path_title"])
    ax.legend()
    ax.grid(alpha=0.3)
    return fig


def _build_report_rows(
    result: AllocationResult,
    institutions: list[Institution],
    horizon_years: float,
    periods_per_year: int,
    regulatory_rules: RegulatoryRules,
) -> tuple[list[dict], list[tuple[str, str, float]], list[tuple[str, float]]]:
    footnote_map: dict[tuple[str, str, float], int] = {}
    footnote_lines: list[tuple[str, str, float]] = []
    raw_rows: list[dict] = []
    institution_totals: list[tuple[str, float]] = []

    for inst_name, amounts in result.allocations.items():
        inst = next(i for i in institutions if i.name == inst_name)
        inst_total = sum(amounts)
        if inst_total <= 0:
            continue

        institution_totals.append((inst_name, inst_total))
        gross_interest_total = sum(
            amount
            * (
                discrete_compounding_accumulation_factor(
                    tier.rate, horizon_years, periods_per_year
                )
                - 1.0
            )
            for amount, tier in zip(amounts, inst.tiers, strict=True)
        )
        institution_tax_total = estimated_isr_tax_over_horizon(
            inst, inst_total, gross_interest_total, horizon_years, regulatory_rules
        )
        for tier_idx, amount in enumerate(amounts):
            if amount <= 0:
                continue
            tier = inst.tiers[tier_idx]
            gross_interest = amount * (
                discrete_compounding_accumulation_factor(
                    tier.rate, horizon_years, periods_per_year
                )
                - 1.0
            )
            active_costs = [
                info
                for info in result.constraint_info.get(inst_name, [])
                if info.get("tier_idx") == tier_idx and info.get("activated")
            ]
            fee_total = tier_activation_cost(tier, amount, horizon_years)
            tax_share = (
                institution_tax_total * (amount / inst_total) if inst_total > 0 else 0.0
            )
            cost_total = fee_total + tax_share
            net_return_nominal = gross_interest - cost_total
            inflation_drag = (
                amount * regulatory_rules.inflation_proxy_annual * horizon_years
            )
            net_return_real = net_return_nominal - inflation_drag
            tags = _assign_footnotes(
                active_costs, inst_name, footnote_map, footnote_lines
            )
            base_cost_cell = (
                " + ".join(
                    (f"[{tag}] ${_constraint_horizon_total(info, horizon_years):,.2f}")
                    for tag, info in zip(tags, active_costs)
                )
                if active_costs
                else "—"
            )
            tax_cell = f"ISR ${tax_share:,.2f}" if tax_share > 0 else None
            cost_cell = (
                f"{base_cost_cell} + {tax_cell}"
                if tax_cell and base_cost_cell != "—"
                else tax_cell or base_cost_cell
            )
            raw_rows.append(
                {
                    "inst": inst_name,
                    "tier": tier_idx + 1,
                    "principal": amount,
                    "nominal_annual_rate": tier.rate,
                    "gross_horizon_return": gross_interest,
                    "fixed_costs": cost_cell,
                    "tax_horizon_total": tax_share,
                    "fees_horizon_total": cost_total,
                    "net_horizon_return_nominal": net_return_nominal,
                    "net_horizon_return_real": net_return_real,
                }
            )
    return raw_rows, footnote_lines, institution_totals


def _assign_footnotes(
    active_costs: list[dict],
    inst_name: str,
    footnote_map: dict[tuple[str, str, float], int],
    footnote_lines: list[tuple[str, str, float]],
) -> list[int]:
    tags: list[int] = []
    for info in active_costs:
        key = (inst_name, info["type"], float(info["cost"]))
        if key not in footnote_map:
            footnote_map[key] = len(footnote_lines) + 1
            footnote_lines.append(key)
        tags.append(footnote_map[key])
    return tags


def _rows_table_and_footnotes(
    raw_rows: list[dict],
    footnote_lines: list[tuple[str, str, float]],
    msgs: dict[str, str],
) -> list[str]:
    try:
        import pandas as pd
    except ModuleNotFoundError:
        return [msgs["pandas_required"]]

    df = pd.DataFrame(
        {
            msgs["col_institution"]: [r["inst"] for r in raw_rows],
            msgs["col_tier"]: [r["tier"] for r in raw_rows],
            msgs["col_principal"]: [f"${r['principal']:,.0f}" for r in raw_rows],
            msgs["col_nominal_rate"]: [f"{r['nominal_annual_rate']:.2%}" for r in raw_rows],
            msgs["col_gross_compound"]: [
                f"${r['gross_horizon_return']:,.2f}" for r in raw_rows
            ],
            msgs["col_fees_horizon"]: [r["fixed_costs"] for r in raw_rows],
            msgs["col_net_nominal"]: [
                f"${r['net_horizon_return_nominal']:,.2f}" for r in raw_rows
            ],
            msgs["col_net_real"]: [
                f"${r['net_horizon_return_real']:,.2f}" for r in raw_rows
            ],
        }
    )

    parts = [
        f"<h4>{html_mod.escape(msgs['h4_tranche'])}</h4>",
        df.to_html(index=False, escape=True),
    ]
    parts.append(f"<h4>{html_mod.escape(msgs['h4_fee_notes'])}</h4><pre>")
    if footnote_lines:
        for idx, key in enumerate(footnote_lines, start=1):
            inst_name, ctype, cost = key
            if ctype == "monthly_expense":
                line = msgs["fee_note_monthly"].format(
                    idx=idx, inst=inst_name, cost=cost
                )
            else:
                line = msgs["fee_note_onetime"].format(
                    idx=idx, inst=inst_name, ctype=ctype, cost=cost
                )
            parts.append(html_mod.escape(line))
    else:
        parts.append(html_mod.escape(msgs["fee_notes_empty"]))
    parts.append(html_mod.escape(msgs["fee_notes_footer"]))
    parts.append("</pre>")
    return parts


def _charts_html(
    result: AllocationResult,
    institutions: list[Institution],
    institution_totals: list[tuple[str, float]],
    horizon_years: float,
    regulatory_rules: RegulatoryRules,
    msgs: dict[str, str],
    *,
    locale: ReportLocale,
    periods_per_year: int,
) -> list[str]:
    try:
        fig_combo = build_allocation_combo_figure(
            result,
            institutions,
            institution_totals,
            horizon_years=horizon_years,
            periods_per_year=periods_per_year,
            regulatory_rules=regulatory_rules,
            locale=locale,
        )
        fig_path = build_portfolio_path_figure(
            result,
            institutions,
            max_days=365,
            periods_per_year=periods_per_year,
            locale=locale,
        )
    except ModuleNotFoundError:
        return [msgs["matplotlib_required"]]

    b64a = _figure_to_png_b64(fig_combo)
    b64b = _figure_to_png_b64(fig_path)
    return [
        f'<h4>{html_mod.escape(msgs["h4_charts"])}</h4>'
        f'<p><img src="data:image/png;base64,{b64a}" alt="{html_mod.escape(msgs["img_alt_combo"])}"/></p>',
        f'<p><img src="data:image/png;base64,{b64b}" alt="{html_mod.escape(msgs["img_alt_path"])}"/></p>',
    ]


def _constraint_horizon_total(info: dict, horizon_years: float) -> float:
    if info.get("type") == "monthly_expense":
        return float(info["cost"]) * 12.0 * horizon_years
    return float(info["cost"])


def _figure_to_png_b64(fig, dpi: int = 110) -> str:
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
