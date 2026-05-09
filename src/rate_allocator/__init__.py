"""Rate Allocator - Optimal cash allocation for tiered interest rates."""

from rate_allocator.core.finance import (
    constraint_cost_over_horizon,
    discrete_compounding_accumulation_factor,
    estimated_isr_tax_over_horizon,
    holding_simple_rate_from_annual,
    portfolio_value_path,
    tier_activation_cost,
    tier_constraint_cost_over_horizon,
    withholding_tax_over_horizon,
)
from rate_allocator.core.optimizer.solve import allocate
from rate_allocator.domain.models import (
    AllocationResult,
    Constraint,
    Institution,
    RegulatoryRules,
    Tier,
)
from rate_allocator.reporting.summary import (
    AllocationSummary,
    InstitutionBreakdown,
    TierBreakdown,
    WealthProjection,
    summarize_allocation,
)
from rate_allocator.reporting.visuals import plot_net_interest_by_tranche_stacked
from rate_allocator.workflows.analysis import summarize_and_plot
from rate_allocator.workflows.interactive_report import (
    build_allocation_combo_figure,
    build_interactive_report_html,
    build_portfolio_path_figure,
)

__all__ = [
    "allocate",
    "Institution",
    "Tier",
    "Constraint",
    "AllocationResult",
    "RegulatoryRules",
    "summarize_allocation",
    "AllocationSummary",
    "InstitutionBreakdown",
    "TierBreakdown",
    "WealthProjection",
    "holding_simple_rate_from_annual",
    "discrete_compounding_accumulation_factor",
    "portfolio_value_path",
    "constraint_cost_over_horizon",
    "tier_constraint_cost_over_horizon",
    "estimated_isr_tax_over_horizon",
    "withholding_tax_over_horizon",
    "plot_net_interest_by_tranche_stacked",
    "summarize_and_plot",
    "build_interactive_report_html",
    "build_allocation_combo_figure",
    "build_portfolio_path_figure",
    "tier_activation_cost",
]
