"""LP-based allocation orchestration built from small helper functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from rate_allocator.core.finance.costs import (
    tier_activation_cost,
    tier_constraint_cost_over_horizon,
)
from rate_allocator.core.finance.rates import (
    discrete_compounding_accumulation_factor,
    holding_simple_rate_from_annual,
)
from rate_allocator.core.finance.taxes import (
    estimated_isr_tax_over_horizon,
    withholding_tax_over_horizon,
)
from rate_allocator.domain.models import (
    AllocationResult,
    Institution,
    RegulatoryRules,
    Tier,
)

CompoundingMode = Literal["simple", "compound"]


def allocate(
    total: float,
    institutions: list[Institution],
    *,
    horizon_years: float = 1.0,
    periods_per_year: int = 365,
    regulatory_rules: RegulatoryRules | None = None,
    compounding: CompoundingMode = "compound",
) -> AllocationResult:
    """Find optimal allocation maximizing net horizon return."""
    _validate_allocate_inputs(total, institutions, horizon_years, periods_per_year, compounding)
    if total == 0:
        return _empty_result(institutions)
    rules = regulatory_rules or RegulatoryRules()

    var_map = _build_var_map(institutions)
    objective = _build_objective(
        institutions,
        total,
        var_map,
        horizon_years,
        periods_per_year,
        rules,
        compounding,
    )
    solution = _solve_milp(institutions, total, var_map, objective, rules)
    return _extract_result(
        solution,
        institutions,
        var_map,
        horizon_years,
        periods_per_year,
        rules,
        compounding,
    )


class ObjectiveParts:
    """Objective coefficients and bounds container."""

    def __init__(self, c: np.ndarray, bounds: list[tuple[float, float]]) -> None:
        self.c = c
        self.bounds = bounds


@dataclass(frozen=True)
class _MilpCore:
    """Phase-1 MILP: minimize c @ x over tier cumulatives and tier-unlock binaries."""

    n_x: int
    n_vars: int
    y_map: dict[tuple[str, int], int]
    c: np.ndarray
    lb: np.ndarray
    ub: np.ndarray
    integrality: np.ndarray
    A: np.ndarray
    constraint_lower: np.ndarray
    constraint_upper: np.ndarray


def _validate_allocate_inputs(
    total: float,
    institutions: list[Institution],
    horizon_years: float,
    periods_per_year: int,
    compounding: CompoundingMode,
) -> None:
    if total < 0:
        raise ValueError("Total must be non-negative")
    if not institutions:
        raise ValueError("Must provide at least one institution")
    names = [inst.name for inst in institutions]
    if len(names) != len(set(names)):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"Duplicate institution names: {duplicates}")
    if horizon_years < 0:
        raise ValueError("horizon_years must be non-negative")
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be at least 1")
    if compounding not in ("simple", "compound"):
        raise ValueError(f"compounding must be 'simple' or 'compound', got {compounding!r}")


def _build_var_map(institutions: list[Institution]) -> dict[tuple[str, int], int]:
    var_map: dict[tuple[str, int], int] = {}
    idx = 0
    for inst in institutions:
        for tier_index in range(len(inst.tiers)):
            var_map[(inst.name, tier_index)] = idx
            idx += 1
    return var_map


def _build_objective(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    horizon_years: float,
    periods_per_year: int,
    regulatory_rules: RegulatoryRules,
    compounding: CompoundingMode,
) -> ObjectiveParts:
    n_vars = len(var_map)
    c = np.zeros(n_vars)
    bounds: list[tuple[float, float]] = []
    epsilon = 1e-9
    max_capacity = _max_capacity(institutions, total)

    for inst in institutions:
        for tier_index, tier in enumerate(inst.tiers):
            var_idx = var_map[(inst.name, tier_index)]
            tier_capacity = _tier_capacity(tier, total)
            current_rate = _objective_rate(
                inst,
                tier,
                tier_capacity,
                horizon_years,
                periods_per_year,
                regulatory_rules,
                compounding,
            )
            next_rate = _next_tier_rate(
                inst,
                tier_index,
                total,
                horizon_years,
                periods_per_year,
                regulatory_rules,
                compounding,
            )
            capacity_priority = tier_capacity / max_capacity if max_capacity else 0.0
            c[var_idx] = -(current_rate - next_rate) - epsilon * capacity_priority
            bounds.append((0.0, _tier_upper_bound(tier, total)))

    return ObjectiveParts(c=c, bounds=bounds)


def _max_capacity(institutions: list[Institution], total: float) -> float:
    return max(
        (_tier_capacity(tier, total) for inst in institutions for tier in inst.tiers),
        default=1.0,
    )


def _tier_capacity(tier: Tier, total: float) -> float:
    return total if tier.limit == float("inf") else min(tier.limit, total)


def _tier_upper_bound(tier: Tier, total: float) -> float:
    return total if tier.limit == float("inf") else min(tier.limit, total)


def _next_tier_rate(
    institution: Institution,
    tier_index: int,
    total: float,
    horizon_years: float,
    periods_per_year: int,
    regulatory_rules: RegulatoryRules,
    compounding: CompoundingMode,
) -> float:
    if tier_index + 1 >= len(institution.tiers):
        return 0.0
    next_tier = institution.tiers[tier_index + 1]
    return _objective_rate(
        institution,
        next_tier,
        _tier_capacity(next_tier, total),
        horizon_years,
        periods_per_year,
        regulatory_rules,
        compounding,
    )


def _objective_rate(
    institution: Institution,
    tier: Tier,
    allocation_hint: float,
    horizon_years: float,
    periods_per_year: int,
    regulatory_rules: RegulatoryRules,
    compounding: CompoundingMode,
) -> float:
    gross = _marginal_return_per_unit(tier, horizon_years, periods_per_year, compounding)
    if allocation_hint <= 0:
        return gross
    nominal_gain_hint = allocation_hint * gross
    fee_per_unit = (
        tier_constraint_cost_over_horizon(tier, horizon_years) / allocation_hint
    )
    tax_per_unit = (
        estimated_isr_tax_over_horizon(
            institution,
            allocation_hint,
            nominal_gain_hint,
            horizon_years,
            regulatory_rules,
        )
        / allocation_hint
    )
    return gross - fee_per_unit - tax_per_unit


def _marginal_return_per_unit(
    tier: Tier, horizon_years: float, periods_per_year: int, compounding: CompoundingMode
) -> float:
    if compounding == "simple":
        return holding_simple_rate_from_annual(tier.rate, horizon_years)
    return discrete_compounding_accumulation_factor(tier.rate, horizon_years, periods_per_year) - 1.0


def _build_budget_constraint(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
) -> tuple[np.ndarray, np.ndarray]:
    n_vars = len(var_map)
    A_eq = np.zeros((1, n_vars))
    for inst in institutions:
        A_eq[0, var_map[(inst.name, len(inst.tiers) - 1)]] = 1.0
    return A_eq, np.array([total])


def _build_inequality_constraints(
    institutions: list[Institution],
    var_map: dict[tuple[str, int], int],
    regulatory_rules: RegulatoryRules,
) -> tuple[np.ndarray, np.ndarray]:
    n_vars = len(var_map)
    constraints: list[np.ndarray] = []
    rhs: list[float] = []
    _append_monotonicity_constraints(institutions, var_map, n_vars, constraints, rhs)
    _append_protection_cap_constraints(
        institutions, var_map, n_vars, constraints, rhs, regulatory_rules
    )
    if not constraints:
        return np.zeros((0, n_vars)), np.array([])
    return np.vstack(constraints), np.array(rhs)


def _append_monotonicity_constraints(
    institutions: list[Institution],
    var_map: dict[tuple[str, int], int],
    n_vars: int,
    constraints: list[np.ndarray],
    rhs: list[float],
) -> None:
    for inst in institutions:
        for t in range(1, len(inst.tiers)):
            row = np.zeros(n_vars)
            row[var_map[(inst.name, t - 1)]] = 1.0
            row[var_map[(inst.name, t)]] = -1.0
            constraints.append(row)
            rhs.append(0.0)


def _append_protection_cap_constraints(
    institutions: list[Institution],
    var_map: dict[tuple[str, int], int],
    n_vars: int,
    constraints: list[np.ndarray],
    rhs: list[float],
    regulatory_rules: RegulatoryRules,
) -> None:
    for inst in institutions:
        cap = inst.protection_limit_for(regulatory_rules)
        if cap is None:
            continue
        row = np.zeros(n_vars)
        row[var_map[(inst.name, len(inst.tiers) - 1)]] = 1.0
        constraints.append(row)
        rhs.append(cap)


def _build_milp_core(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    objective: ObjectiveParts,
    regulatory_rules: RegulatoryRules,
) -> _MilpCore:
    n_x = len(objective.c)
    y_map = _build_tier_unlock_var_map(institutions, n_x)
    n_vars = n_x + len(y_map)

    c = np.zeros(n_vars)
    c[:n_x] = objective.c

    lb = np.zeros(n_vars)
    ub = np.ones(n_vars)
    for idx, (x_lb, x_ub) in enumerate(objective.bounds):
        lb[idx] = x_lb
        ub[idx] = x_ub

    A_eq_x, b_eq = _build_budget_constraint(institutions, total, var_map)
    A_ub_x, b_ub = _build_inequality_constraints(
        institutions, var_map, regulatory_rules
    )
    A_eq = np.hstack([A_eq_x, np.zeros((A_eq_x.shape[0], len(y_map)))])
    A_ub = np.hstack([A_ub_x, np.zeros((A_ub_x.shape[0], len(y_map)))])

    unlock_rows, unlock_rhs = _build_tier_unlock_constraints(
        institutions, total, var_map, y_map, n_vars, regulatory_rules
    )
    if unlock_rows.size:
        A_ub = np.vstack([A_ub, unlock_rows])
        b_ub = np.concatenate([b_ub, unlock_rhs])

    matrices: list[np.ndarray] = []
    lowers: list[float] = []
    uppers: list[float] = []

    if A_eq.size:
        matrices.append(A_eq)
        lowers.extend(b_eq.tolist())
        uppers.extend(b_eq.tolist())
    if A_ub.size:
        matrices.append(A_ub)
        lowers.extend([-np.inf] * A_ub.shape[0])
        uppers.extend(b_ub.tolist())

    A = np.vstack(matrices) if matrices else np.zeros((0, n_vars))
    integrality = np.zeros(n_vars, dtype=int)
    for y_idx in y_map.values():
        integrality[y_idx] = 1

    return _MilpCore(
        n_x=n_x,
        n_vars=n_vars,
        y_map=y_map,
        c=c,
        lb=lb,
        ub=ub,
        integrality=integrality,
        A=A,
        constraint_lower=np.array(lowers, dtype=float),
        constraint_upper=np.array(uppers, dtype=float),
    )


def _run_milp_dense(
    c: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
    integrality: np.ndarray,
    A: np.ndarray,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
) -> np.ndarray:
    result = milp(
        c=c,
        integrality=integrality,
        bounds=Bounds(lb, ub),
        constraints=LinearConstraint(A, constraint_lower, constraint_upper),
    )
    if not result.success or result.x is None:
        raise ValueError(f"Optimization failed (MILP): {result.message}")
    return np.array(result.x, dtype=float)


def _primary_objective_value(c_primary: np.ndarray, sol: np.ndarray) -> float:
    return float(np.dot(c_primary, sol[: c_primary.shape[0]]))


def _institution_indicator_penalty(c_primary: np.ndarray, n_institutions: int) -> float:
    """Tiny weight on sum(z) so marginal-return objective dominates; breaks ties toward fewer accounts."""
    nz = np.abs(c_primary[np.abs(c_primary) > 1e-18])
    floor = float(np.min(nz)) if nz.size else 1e-9
    cap = floor / max(500.0, 50.0 * float(n_institutions))
    return min(cap, 1e-11)


def _institution_open_rows(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    n_core_vars: int,
    n_inst: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_expanded = n_core_vars + n_inst
    rows: list[np.ndarray] = []
    z_col = n_core_vars
    for inst in institutions:
        row = np.zeros(n_expanded)
        row[var_map[(inst.name, len(inst.tiers) - 1)]] = 1.0
        row[z_col] = -float(total)
        rows.append(row)
        z_col += 1
    if not rows:
        return np.zeros((0, n_expanded)), np.array([]), np.array([])
    mat = np.vstack(rows)
    lower = np.full(len(rows), -np.inf)
    upper = np.zeros(len(rows))
    return mat, lower, upper


def _stack_extended_constraints(
    core: _MilpCore,
    extra_A: np.ndarray,
    extra_lower: np.ndarray,
    extra_upper: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_inst_cols = extra_A.shape[1] - core.A.shape[1]
    base_wide = np.hstack([core.A, np.zeros((core.A.shape[0], n_inst_cols))])
    if extra_A.size == 0:
        return base_wide, core.constraint_lower, core.constraint_upper
    A_full = np.vstack([base_wide, extra_A])
    lower = np.concatenate([core.constraint_lower, extra_lower])
    upper = np.concatenate([core.constraint_upper, extra_upper])
    return A_full, lower, upper


def _solve_milp_single_penalty(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    objective: ObjectiveParts,
    regulatory_rules: RegulatoryRules,
    *,
    institution_penalty: float,
) -> np.ndarray:
    """Single MILP: minimize c @ x + penalty * sum(z) where z indicates an open institution."""
    core = _build_milp_core(
        institutions, total, var_map, objective, regulatory_rules
    )
    n_inst = len(institutions)
    open_rows, open_lo, open_hi = _institution_open_rows(
        institutions, total, var_map, core.n_vars, n_inst
    )
    A2, lo2, hi2 = _stack_extended_constraints(core, open_rows, open_lo, open_hi)
    n2 = core.n_vars + n_inst
    c2 = np.zeros(n2)
    c2[: core.n_vars] = core.c
    c2[core.n_vars :] = float(institution_penalty)
    lb2 = np.concatenate([core.lb, np.zeros(n_inst)])
    ub2 = np.concatenate([core.ub, np.ones(n_inst)])
    int2 = np.concatenate([core.integrality, np.ones(n_inst, dtype=int)])
    sol = _run_milp_dense(c2, lb2, ub2, int2, A2, lo2, hi2)
    return sol[: core.n_x]


def _solve_milp(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    objective: ObjectiveParts,
    regulatory_rules: RegulatoryRules,
) -> np.ndarray:
    delta = _institution_indicator_penalty(objective.c, len(institutions))
    return _solve_milp_single_penalty(
        institutions,
        total,
        var_map,
        objective,
        regulatory_rules,
        institution_penalty=delta,
    )


def _build_tier_unlock_var_map(
    institutions: list[Institution], offset: int
) -> dict[tuple[str, int], int]:
    y_map: dict[tuple[str, int], int] = {}
    idx = offset
    for inst in institutions:
        for tier_index in range(1, len(inst.tiers)):
            y_map[(inst.name, tier_index)] = idx
            idx += 1
    return y_map


def _build_tier_unlock_constraints(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    y_map: dict[tuple[str, int], int],
    n_vars: int,
    regulatory_rules: RegulatoryRules,
) -> tuple[np.ndarray, np.ndarray]:
    rows: list[np.ndarray] = []
    rhs: list[float] = []
    for inst in institutions:
        limit = inst.protection_limit_for(regulatory_rules)
        inst_cap = min(total, limit if limit is not None else total)
        for tier_index in range(1, len(inst.tiers)):
            y_idx = y_map[(inst.name, tier_index)]

            # Delta funding in tier t requires y_t = 1.
            row_activation = np.zeros(n_vars)
            row_activation[var_map[(inst.name, tier_index)]] = 1.0
            row_activation[var_map[(inst.name, tier_index - 1)]] = -1.0
            row_activation[y_idx] = -inst_cap
            rows.append(row_activation)
            rhs.append(0.0)

            # Activating tier t requires previous tier fully filled.
            prev_limit = inst.tiers[tier_index - 1].limit
            prev_cap = (
                inst_cap if prev_limit == float("inf") else min(prev_limit, inst_cap)
            )
            row_prev_full = np.zeros(n_vars)
            row_prev_full[var_map[(inst.name, tier_index - 1)]] = -1.0
            row_prev_full[y_idx] = prev_cap
            rows.append(row_prev_full)
            rhs.append(0.0)

    if not rows:
        return np.zeros((0, n_vars)), np.array([])
    return np.vstack(rows), np.array(rhs)


def _extract_result(
    x: np.ndarray,
    institutions: list[Institution],
    var_map: dict[tuple[str, int], int],
    horizon_years: float,
    periods_per_year: int,
    regulatory_rules: RegulatoryRules,
    compounding: CompoundingMode,
) -> AllocationResult:
    allocations: dict[str, list[float]] = {}
    constraint_info: dict[str, list[dict]] = {}
    total_allocated = 0.0
    total_return = 0.0
    total_expenses_paid = 0.0
    total_taxes_paid = 0.0
    total_withholding_paid = 0.0

    for inst in institutions:
        tier_amounts = _tier_amounts_from_solution(x, inst, var_map)
        allocations[inst.name] = tier_amounts
        constraint_info[inst.name] = _build_constraint_info(inst, tier_amounts)
        total_allocated += sum(tier_amounts)

        inst_return, inst_cost, inst_tax, inst_withholding = (
            _institution_return_and_cost(
                inst,
                tier_amounts,
                horizon_years,
                periods_per_year,
                regulatory_rules,
                compounding,
            )
        )
        total_return += inst_return
        total_expenses_paid += inst_cost
        total_taxes_paid += inst_tax
        total_withholding_paid += inst_withholding

    total_return = _apply_post_return_adjustments(total_return)
    weights = _weights_from_allocations(allocations, total_allocated)
    effective_rate = total_return / total_allocated if total_allocated > 0 else 0.0
    return AllocationResult(
        weights=weights,
        allocations=allocations,
        total_allocated=total_allocated,
        expected_return=total_return,
        effective_rate=effective_rate,
        total_expenses_paid=total_expenses_paid,
        total_taxes_paid=total_taxes_paid,
        total_withholding_paid=total_withholding_paid,
        constraint_info=constraint_info,
    )


def _tier_amounts_from_solution(
    x: np.ndarray,
    institution: Institution,
    var_map: dict[tuple[str, int], int],
) -> list[float]:
    amounts: list[float] = []
    prev = 0.0
    for tier_index in range(len(institution.tiers)):
        cumulative = x[var_map[(institution.name, tier_index)]]
        tier_amount = max(0.0, cumulative - prev)
        amounts.append(tier_amount)
        prev = cumulative
    return amounts


def _build_constraint_info(
    institution: Institution, tier_amounts: list[float]
) -> list[dict]:
    info: list[dict] = []
    for tier_index, (tier, amount) in enumerate(
        zip(institution.tiers, tier_amounts, strict=True)
    ):
        for constraint in tier.constraints:
            if not constraint.active and constraint.type != "disclosure":
                continue
            row: dict = {
                "tier_idx": tier_index,
                "type": constraint.type,
                "cost": constraint.cost,
                "benefit": constraint.benefit,
                "activated": amount > 0,
            }
            if constraint.constraint_condition is not None:
                row["constraint_condition"] = constraint.constraint_condition
            if constraint.benefit_condition is not None:
                row["benefit_condition"] = constraint.benefit_condition
            info.append(row)
    return info


def _institution_return_and_cost(
    institution: Institution,
    tier_amounts: list[float],
    horizon_years: float,
    periods_per_year: int,
    regulatory_rules: RegulatoryRules,
    compounding: CompoundingMode,
) -> tuple[float, float, float, float]:
    gross_return = 0.0
    expenses = 0.0
    principal_amount = 0.0
    for tier, amount in zip(institution.tiers, tier_amounts, strict=True):
        principal_amount += amount
        gross_return += amount * _marginal_return_per_unit(
            tier, horizon_years, periods_per_year, compounding
        )
        expenses += tier_activation_cost(tier, amount, horizon_years)
    taxes = estimated_isr_tax_over_horizon(
        institution, principal_amount, gross_return, horizon_years, regulatory_rules
    )
    withholding_paid = withholding_tax_over_horizon(
        institution, principal_amount, horizon_years, regulatory_rules
    )
    return gross_return - expenses - taxes, expenses, taxes, withholding_paid


def _weights_from_allocations(
    allocations: dict[str, list[float]],
    total_allocated: float,
) -> dict[str, list[float]]:
    if total_allocated <= 0:
        return {name: [0.0 for _ in amounts] for name, amounts in allocations.items()}
    return {
        name: [(amount / total_allocated) * 100.0 for amount in amounts]
        for name, amounts in allocations.items()
    }


def _empty_result(institutions: list[Institution]) -> AllocationResult:
    allocations = {inst.name: [0.0] * len(inst.tiers) for inst in institutions}
    weights = {inst.name: [0.0] * len(inst.tiers) for inst in institutions}
    constraint_info = {
        inst.name: _build_constraint_info(inst, [0.0] * len(inst.tiers))
        for inst in institutions
    }
    return AllocationResult(
        weights=weights,
        allocations=allocations,
        total_allocated=0.0,
        expected_return=0.0,
        effective_rate=0.0,
        total_expenses_paid=0.0,
        total_taxes_paid=0.0,
        total_withholding_paid=0.0,
        constraint_info=constraint_info,
    )


def _apply_post_return_adjustments(pre_tax_return: float) -> float:
    return pre_tax_return
