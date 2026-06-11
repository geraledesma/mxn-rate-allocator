"""Allocation summary dataclasses and transformation functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rate_allocator.core.finance.costs import tier_activation_cost
from rate_allocator.core.finance.rates import (
    discrete_compounding_accumulation_factor,
    holding_simple_rate_from_annual,
)
from rate_allocator.core.finance.taxes import (
    estimated_isr_tax_over_horizon,
    withholding_tax_over_horizon,
)
from rate_allocator.domain.models import AllocationResult, Institution, RegulatoryRules

ProjectionMethod = Literal["simple_annual_scaled", "compound_discrete_annual_nominal"]


@dataclass(frozen=True)
class TierBreakdown:
    institution_name: str
    tier_index: int
    amount: float
    weight: float
    rate: float
    gross_interest: float
    constraint_cost_paid: float
    tax_cost_paid: float
    withholding_paid: float

    @property
    def net_contribution(self) -> float:
        return self.gross_interest - self.constraint_cost_paid - self.tax_cost_paid


@dataclass(frozen=True)
class InstitutionBreakdown:
    name: str
    amount: float
    weight: float
    gross_interest: float
    constraint_cost_paid: float
    tax_cost_paid: float
    withholding_paid: float
    tiers: tuple[TierBreakdown, ...]

    @property
    def net_contribution(self) -> float:
        return self.gross_interest - self.constraint_cost_paid - self.tax_cost_paid


@dataclass(frozen=True)
class WealthProjection:
    method: ProjectionMethod
    terminal_wealth: float
    interest_gain: float
    years: float | None
    year_fraction: float | None
    compounding_periods_per_year: int | None


@dataclass(frozen=True)
class AllocationSummary:
    total_allocated: float
    gross_interest: float
    total_constraint_cost: float
    net_dollar_return: float
    institutions: tuple[InstitutionBreakdown, ...]
    tiers: tuple[TierBreakdown, ...]
    matches_expected_return: bool
    projection: WealthProjection | None = None


def summarize_allocation(
    result: AllocationResult,
    institutions: list[Institution],
    *,
    holding_year_fraction: float | None = None,
    compound_years: float | None = None,
    compounding_periods_per_year: int = 12,
    horizon_years: float = 1.0,
    regulatory_rules: RegulatoryRules | None = None,
) -> AllocationSummary:
    """Build a summary view by composing small reporting helpers."""
    _validate_alignment(result, institutions)
    rules = regulatory_rules or RegulatoryRules()
    tier_rows, institution_rows = _build_breakdown_rows(
        result, institutions, horizon_years, rules, compounding_periods_per_year
    )
    gross_total = sum(row.gross_interest for row in tier_rows)
    cost_total = sum(row.constraint_cost_paid + row.tax_cost_paid for row in tier_rows)
    net_total = gross_total - cost_total
    projection = _build_projection(
        tier_rows,
        result.total_allocated,
        holding_year_fraction,
        compound_years,
        compounding_periods_per_year,
    )
    return AllocationSummary(
        total_allocated=result.total_allocated,
        gross_interest=gross_total,
        total_constraint_cost=cost_total,
        net_dollar_return=net_total,
        institutions=tuple(institution_rows),
        tiers=tuple(tier_rows),
        matches_expected_return=_matches_expected_return(
            net_total, result.expected_return
        ),
        projection=projection,
    )


def _build_breakdown_rows(
    result: AllocationResult,
    institutions: list[Institution],
    horizon_years: float,
    regulatory_rules: RegulatoryRules,
    periods_per_year: int,
) -> tuple[list[TierBreakdown], list[InstitutionBreakdown]]:
    tier_rows: list[TierBreakdown] = []
    institution_rows: list[InstitutionBreakdown] = []
    total_allocated = result.total_allocated
    for inst in institutions:
        amounts = result.allocations[inst.name]
        institution_tiers: list[TierBreakdown] = []
        for tier_index, (amount, tier) in enumerate(
            zip(amounts, inst.tiers, strict=True)
        ):
            institution_total = sum(amounts)
            institution_gross_return = sum(
                amount * (
                    discrete_compounding_accumulation_factor(rate, horizon_years, periods_per_year) - 1.0
                )
                for amount, rate in zip(
                    amounts, [tier.rate for tier in inst.tiers], strict=True
                )
            )
            institution_tax_total = estimated_isr_tax_over_horizon(
                inst,
                institution_total,
                institution_gross_return,
                horizon_years,
                regulatory_rules,
            )
            institution_withholding_total = withholding_tax_over_horizon(
                inst, institution_total, horizon_years, regulatory_rules
            )
            tax_share = (
                institution_tax_total * (amount / institution_total)
                if institution_total > 0
                else 0.0
            )
            withholding_share = (
                institution_withholding_total * (amount / institution_total)
                if institution_total > 0
                else 0.0
            )
            row = _tier_breakdown_row(
                inst.name,
                tier_index,
                amount,
                tier.rate,
                total_allocated,
                tier,
                horizon_years,
                tax_share,
                withholding_share,
            )
            institution_tiers.append(row)
            tier_rows.append(row)
        institution_rows.append(
            _institution_breakdown_row(inst.name, institution_tiers, total_allocated)
        )
    return tier_rows, institution_rows


def _tier_breakdown_row(
    institution_name: str,
    tier_index: int,
    amount: float,
    rate: float,
    total_allocated: float,
    tier,
    horizon_years: float,
    tax_cost_paid: float,
    withholding_paid: float,
) -> TierBreakdown:
    weight = (amount / total_allocated) if total_allocated > 0 else 0.0
    gross_interest = amount * rate
    cost_paid = tier_activation_cost(tier, amount, horizon_years)
    return TierBreakdown(
        institution_name=institution_name,
        tier_index=tier_index,
        amount=amount,
        weight=weight,
        rate=rate,
        gross_interest=gross_interest,
        constraint_cost_paid=cost_paid,
        tax_cost_paid=tax_cost_paid,
        withholding_paid=withholding_paid,
    )


def _institution_breakdown_row(
    name: str,
    tier_rows: list[TierBreakdown],
    total_allocated: float,
) -> InstitutionBreakdown:
    amount = sum(row.amount for row in tier_rows)
    weight = (amount / total_allocated) if total_allocated > 0 else 0.0
    return InstitutionBreakdown(
        name=name,
        amount=amount,
        weight=weight,
        gross_interest=sum(row.gross_interest for row in tier_rows),
        constraint_cost_paid=sum(row.constraint_cost_paid for row in tier_rows),
        tax_cost_paid=sum(row.tax_cost_paid for row in tier_rows),
        withholding_paid=sum(row.withholding_paid for row in tier_rows),
        tiers=tuple(tier_rows),
    )


def _build_projection(
    tier_rows: list[TierBreakdown],
    total_allocated: float,
    holding_year_fraction: float | None,
    compound_years: float | None,
    compounding_periods_per_year: int,
) -> WealthProjection | None:
    if compound_years is not None:
        return _compound_projection(
            tier_rows, total_allocated, compound_years, compounding_periods_per_year
        )
    if holding_year_fraction is not None:
        return _simple_projection(tier_rows, total_allocated, holding_year_fraction)
    return None


def _compound_projection(
    tier_rows: list[TierBreakdown],
    total_allocated: float,
    compound_years: float,
    compounding_periods_per_year: int,
) -> WealthProjection:
    if compound_years < 0:
        raise ValueError("compound_years must be non-negative")
    terminal_wealth = sum(
        row.amount
        * discrete_compounding_accumulation_factor(
            row.rate, compound_years, compounding_periods_per_year
        )
        for row in tier_rows
    )
    return WealthProjection(
        method="compound_discrete_annual_nominal",
        terminal_wealth=terminal_wealth,
        interest_gain=terminal_wealth - total_allocated,
        years=compound_years,
        year_fraction=None,
        compounding_periods_per_year=compounding_periods_per_year,
    )


def _simple_projection(
    tier_rows: list[TierBreakdown],
    total_allocated: float,
    holding_year_fraction: float,
) -> WealthProjection:
    if holding_year_fraction < 0:
        raise ValueError("holding_year_fraction must be non-negative")
    terminal_wealth = sum(
        row.amount
        * (1.0 + holding_simple_rate_from_annual(row.rate, holding_year_fraction))
        for row in tier_rows
    )
    return WealthProjection(
        method="simple_annual_scaled",
        terminal_wealth=terminal_wealth,
        interest_gain=terminal_wealth - total_allocated,
        years=None,
        year_fraction=holding_year_fraction,
        compounding_periods_per_year=None,
    )


def _matches_expected_return(net_total: float, expected_return: float) -> bool:
    tolerance = max(1e-9, 1e-9 * abs(expected_return))
    return abs(net_total - expected_return) <= tolerance


def _validate_alignment(
    result: AllocationResult, institutions: list[Institution]
) -> None:
    if {i.name for i in institutions} != set(result.allocations.keys()):
        raise ValueError(
            "institutions and result.allocations must have the same institution names"
        )
    by_name = {i.name: i for i in institutions}
    for name, amounts in result.allocations.items():
        n_tiers = len(by_name[name].tiers)
        if len(amounts) != n_tiers:
            raise ValueError(
                f"Institution {name!r}: {len(amounts)} allocation tiers but "
                f"{n_tiers} tier definitions"
            )
