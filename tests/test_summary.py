"""Tests for summary helpers (constraint costs, plots data prep)."""

import pytest

from rate_allocator.core.finance.costs import (
    constraint_cost_over_horizon,
    tier_activation_cost,
    tier_constraint_cost_over_horizon,
)
from rate_allocator.domain.models import (
    AllocationResult,
    Constraint,
    Institution,
    Tier,
)
from rate_allocator.workflows.interactive_report import build_interactive_report_html
from tests.conftest import mk_inst


def test_constraint_cost_monthly_scales_with_horizon():
    c = Constraint(type="monthly_expense", cost=100.0)
    assert constraint_cost_over_horizon(c, 1.0) == pytest.approx(1_200.0)
    assert constraint_cost_over_horizon(c, 2.0) == pytest.approx(2_400.0)
    assert constraint_cost_over_horizon(c, None) == pytest.approx(1_200.0)


def test_constraint_cost_one_time():
    c = Constraint(type="fee", cost=50.0)
    assert constraint_cost_over_horizon(c, 1.0) == pytest.approx(50.0)
    assert constraint_cost_over_horizon(c, None) == pytest.approx(50.0)


def test_tier_activation_cost_zero_when_unfunded():
    tier = Tier(
        limit=float("inf"),
        rate=0.1,
        constraints=(Constraint(type="fee", cost=99.0),),
    )
    assert tier_activation_cost(tier, 0.0, 1.0) == 0.0


def test_tier_constraint_cost_matches_monthly_formula():
    tier = Tier(
        limit=float("inf"),
        rate=0.0,
        constraints=(Constraint(type="monthly_expense", cost=114.84, benefit="plan"),),
    )
    assert tier_constraint_cost_over_horizon(tier, 1.0) == pytest.approx(114.84 * 12.0)
    assert tier_activation_cost(tier, 1.0, 1.0) == pytest.approx(114.84 * 12.0)


def test_tier_constraint_cost_sums_active_constraints():
    tier = Tier(
        limit=float("inf"),
        rate=0.0,
        constraints=(
            Constraint(type="fee", cost=10.0),
            Constraint(type="fee", cost=5.0, active=False),
        ),
    )
    assert tier_constraint_cost_over_horizon(tier, 1.0) == pytest.approx(10.0)


def test_interactive_report_uses_horizon_semantics_labels():
    pytest.importorskip("pandas")
    institutions = [
        mk_inst("BankA", (Tier(limit=float("inf"), rate=0.10),)),
    ]
    result = AllocationResult(
        weights={"BankA": [100.0]},
        allocations={"BankA": [10_000.0]},
        total_allocated=10_000.0,
        expected_return=1_000.0,
        effective_rate=0.10,
        total_expenses_paid=0.0,
        total_withholding_paid=0.0,
        constraint_info={"BankA": []},
    )
    html = build_interactive_report_html(
        result,
        institutions,
        total=10_000.0,
        horizon_years=1.0,
        periods_per_year=365,
    )
    assert "Gross return (compound)" in html
    assert "Fees (constraints + tax, horizon)" in html
    assert "Net return nominal" in html
    assert "Net return real" in html
    assert "deployed" not in html.lower()


def test_interactive_report_spanish_locale():
    pytest.importorskip("pandas")
    pytest.importorskip("matplotlib")
    institutions = [
        mk_inst("BankA", (Tier(limit=float("inf"), rate=0.10),)),
    ]
    result = AllocationResult(
        weights={"BankA": [100.0]},
        allocations={"BankA": [10_000.0]},
        total_allocated=10_000.0,
        expected_return=1_000.0,
        effective_rate=0.10,
        total_expenses_paid=0.0,
        total_withholding_paid=0.0,
        constraint_info={"BankA": []},
    )
    html = build_interactive_report_html(
        result,
        institutions,
        total=10_000.0,
        horizon_years=1.0,
        periods_per_year=365,
        locale="es",
    )
    assert "Institución" in html
    assert "Rendimiento bruto (compuesto)" in html
    assert "Comisiones (restricciones + impuesto, horizonte)" in html
    assert "Rendimiento neto nominal" in html
    assert "Rendimiento neto real" in html
    assert "Gráficos" in html
