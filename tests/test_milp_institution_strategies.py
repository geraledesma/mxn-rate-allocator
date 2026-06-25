"""Regression tests for single-MILP institution indicator penalty (tie-break)."""

from __future__ import annotations

import numpy as np

from rate_allocator import Institution, Tier
from rate_allocator.domain.models import RegulatoryRules
from rate_allocator.core.optimizer.solve import (
    _build_milp_core,
    _build_objective,
    _build_var_map,
    _institution_indicator_penalty,
    _primary_objective_value,
    _run_milp_dense,
    _solve_milp_single_penalty,
)


def _count_institutions_used(
    x: np.ndarray,
    institutions: list[Institution],
    var_map: dict[tuple[str, int], int],
    *,
    tol: float = 1e-9,
) -> int:
    n = 0
    for inst in institutions:
        last = x[var_map[(inst.name, len(inst.tiers) - 1)]]
        if last > tol:
            n += 1
    return n


def _solve_core_only(
    institutions: list[Institution],
    total: float,
    var_map: dict[tuple[str, int], int],
    objective,
    rules: RegulatoryRules,
) -> np.ndarray:
    core = _build_milp_core(institutions, total, var_map, objective, rules)
    return _run_milp_dense(
        core.c,
        core.lb,
        core.ub,
        core.integrality,
        core.A,
        core.constraint_lower,
        core.constraint_upper,
    )


def test_indicator_penalty_tiny_relative_to_primary_coefficients():
    c = np.array([-1e-06, -0.05, 0.0])
    p = _institution_indicator_penalty(c, n_institutions=5)
    assert p < float(np.min(np.abs(c[np.abs(c) > 1e-18]))) / 100.0


def test_symmetric_institutions_minimize_open_count():
    institutions = [
        Institution(
            name=f"B{i}",
            tiers=(Tier(limit=float("inf"), rate=0.11),),
        )
        for i in range(4)
    ]
    total = 75_000.0
    rules = RegulatoryRules()
    var_map = _build_var_map(institutions)
    objective = _build_objective(
        institutions, total, var_map, 1.0, 365, rules, "compound"
    )
    delta = _institution_indicator_penalty(objective.c, len(institutions))
    x = _solve_milp_single_penalty(
        institutions,
        total,
        var_map,
        objective,
        rules,
        institution_penalty=delta,
    )
    assert _count_institutions_used(x, institutions, var_map) == 1


def test_penalty_matches_phase1_primary_on_representative_cases():
    """Derived δ must not move the marginal objective measurably vs the original MILP."""
    scenarios = [
        (
            "identical_three",
            [
                Institution(
                    name=f"B{i}",
                    tiers=(Tier(limit=float("inf"), rate=0.11),),
                )
                for i in range(3)
            ],
            50_000.0,
        ),
        (
            "asymmetric_sample",
            [
                Institution(
                    name="Nu",
                    tiers=(
                        Tier(limit=25_000, rate=0.15),
                        Tier(limit=250_000, rate=0.12),
                        Tier(limit=float("inf"), rate=0.10),
                    ),
                ),
                Institution(
                    name="Mercado Pago",
                    tiers=(
                        Tier(limit=23_000, rate=0.14),
                        Tier(limit=float("inf"), rate=0.10),
                    ),
                ),
            ],
            100_000.0,
        ),
        (
            "near_tie_rates",
            [
                Institution(
                    name="A",
                    tiers=(Tier(limit=float("inf"), rate=0.1000001),),
                ),
                Institution(
                    name="B",
                    tiers=(Tier(limit=float("inf"), rate=0.1000000),),
                ),
            ],
            10_000.0,
        ),
    ]
    rules = RegulatoryRules()
    for _name, institutions, total in scenarios:
        var_map = _build_var_map(institutions)
        objective = _build_objective(
            institutions, total, var_map, 1.0, 365, rules, "compound"
        )
        x0 = _solve_core_only(institutions, total, var_map, objective, rules)
        o0 = _primary_objective_value(objective.c, x0)
        delta = _institution_indicator_penalty(objective.c, len(institutions))
        x1 = _solve_milp_single_penalty(
            institutions,
            total,
            var_map,
            objective,
            rules,
            institution_penalty=delta,
        )
        o1 = _primary_objective_value(objective.c, x1)
        assert o1 <= o0 + max(1e-7 * max(1.0, abs(o0)), 1e-12)
        assert _count_institutions_used(x1, institutions, var_map) <= _count_institutions_used(
            x0, institutions, var_map
        )


def test_large_penalty_can_sacrifice_primary():
    """If δ is too large, the solver may trade return for fewer accounts (documented pitfall)."""
    institutions = [
        Institution(
            name="High",
            tiers=(
                Tier(limit=5_000, rate=0.20),
                Tier(limit=float("inf"), rate=0.05),
            ),
        ),
        Institution(
            name="Flat",
            tiers=(Tier(limit=float("inf"), rate=0.12),),
        ),
    ]
    total = 8_000.0
    rules = RegulatoryRules()
    var_map = _build_var_map(institutions)
    objective = _build_objective(
        institutions, total, var_map, 1.0, 365, rules, "compound"
    )
    x_lexish = _solve_core_only(institutions, total, var_map, objective, rules)
    o0 = _primary_objective_value(objective.c, x_lexish)
    # δ must exceed the marginal-return gap between the true optimum (two SOFIs) and a
    # one-institution feasible point; ~230 here for this coefficient scale.
    x_pen = _solve_milp_single_penalty(
        institutions,
        total,
        var_map,
        objective,
        rules,
        institution_penalty=300.0,
    )
    o_pen = _primary_objective_value(objective.c, x_pen)
    n0 = _count_institutions_used(x_lexish, institutions, var_map)
    n1 = _count_institutions_used(x_pen, institutions, var_map)
    assert o_pen > o0 + 1e-6
    assert n1 < n0
