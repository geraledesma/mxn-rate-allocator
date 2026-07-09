"""Core domain models for the allocator."""

from dataclasses import dataclass, field
from typing import Literal

InstitutionType = Literal["banco", "sofipo", "none"]


@dataclass(frozen=True)
class RegulatoryRules:
    """Policy inputs that can be updated without changing code."""

    country: str = "MX"
    effective_from: str = "2026-01-01"
    bank_insurance_limit_mxn: float = 3_300_000.0
    sofipo_insurance_limit_mxn: float = 208_000.0
    bank_isr_withholding_rate_annual: float = 0.009
    real_interest_isr_rate_annual: float = 0.009
    inflation_proxy_annual: float = 0.0421
    sofipo_exempt_balance_limit_mxn: float = 213_973.0
    sofipo_excess_isr_rate_annual: float = 0.009

    def __post_init__(self):
        if self.bank_insurance_limit_mxn < 0:
            raise ValueError("bank_insurance_limit_mxn must be non-negative")
        if self.sofipo_insurance_limit_mxn < 0:
            raise ValueError("sofipo_insurance_limit_mxn must be non-negative")
        if not (0 <= self.bank_isr_withholding_rate_annual <= 1):
            raise ValueError("bank_isr_withholding_rate_annual must be between 0 and 1")
        if not (0 <= self.real_interest_isr_rate_annual <= 1):
            raise ValueError("real_interest_isr_rate_annual must be between 0 and 1")
        if self.inflation_proxy_annual < 0:
            raise ValueError("inflation_proxy_annual must be non-negative")
        if self.sofipo_exempt_balance_limit_mxn < 0:
            raise ValueError("sofipo_exempt_balance_limit_mxn must be non-negative")
        if not (0 <= self.sofipo_excess_isr_rate_annual <= 1):
            raise ValueError("sofipo_excess_isr_rate_annual must be between 0 and 1")


@dataclass(frozen=True)
class Constraint:
    """An optional condition attached to a tier."""

    type: str
    cost: float = 0.0
    benefit: str | None = None
    condition_value: float | None = None
    active: bool = True
    constraint_condition: str | None = None
    benefit_condition: str | None = None

    def __post_init__(self):
        if not self.type:
            raise ValueError("Constraint type must be a non-empty string")
        if self.cost < 0:
            raise ValueError("Constraint cost must be non-negative")


@dataclass(frozen=True)
class Tier:
    """A rate tier with cumulative limit and interest rate."""

    limit: float
    rate: float
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.limit <= 0 and self.limit != float("inf"):
            raise ValueError("Tier limit must be positive or inf")
        if not (0 <= self.rate <= 1):
            raise ValueError("Rate must be between 0 and 1")
        if not isinstance(self.constraints, tuple):
            raise ValueError("Tier constraints must be a tuple")


@dataclass(frozen=True)
class Plan:
    """A subscription plan within an institution (e.g. Klar Light, Klar Plus).

    Single-plan institutions use plan_key='base' and display_name=institution name.
    """

    plan_key: str
    display_name: str
    monthly_cost: float
    tiers: tuple[Tier, ...]

    def __post_init__(self):
        if not self.plan_key:
            raise ValueError("plan_key must be a non-empty string")
        if not self.display_name:
            raise ValueError("display_name must be a non-empty string")
        if self.monthly_cost < 0:
            raise ValueError("monthly_cost must be non-negative")
        if not self.tiers:
            raise ValueError("Plan must have at least one tier")
        limits = [t.limit for t in self.tiers]
        if limits != sorted(limits):
            raise ValueError("Tier limits must be in ascending order")


@dataclass
class AllocationResult:
    """Result of optimal allocation."""

    weights: dict[str, list[float]]
    allocations: dict[str, list[float]]
    total_allocated: float
    expected_return: float
    effective_rate: float
    total_expenses_paid: float = 0.0
    total_taxes_paid: float = 0.0
    total_withholding_paid: float = 0.0
    constraint_info: dict[str, list[dict]] = field(default_factory=dict)


@dataclass(frozen=True)
class Institution:
    """A financial institution with one or more subscription plans."""

    name: str
    plans: tuple[Plan, ...]
    institution_type: InstitutionType = "none"
    protection_limit: float | None = None

    def __post_init__(self):
        if not self.plans:
            raise ValueError("Institution must have at least one plan")

    def protection_limit_for(self, rules: "RegulatoryRules") -> float | None:
        """Resolve effective protection cap using configurable policy rules."""
        if self.protection_limit is not None:
            return self.protection_limit
        if self.institution_type == "banco":
            return rules.bank_insurance_limit_mxn
        if self.institution_type == "sofipo":
            return rules.sofipo_insurance_limit_mxn
        return None

    @property
    def tiers(self) -> tuple[Tier, ...]:
        """Tiers of the base plan — for optimizer and v1 API compatibility."""
        for p in self.plans:
            if p.plan_key == "base":
                return p.tiers
        return self.plans[0].tiers

    @property
    def effective_protection_limit(self) -> float | None:
        """Alias for protection_limit_for(RegulatoryRules()) — backward compat."""
        return self.protection_limit_for(RegulatoryRules())

    def flatten(self) -> list["Institution"]:
        """One Institution per Plan — used by v1 API and the optimizer.

        Each returned Institution has a single 'base' plan whose tiers are the
        plan's tiers and whose name is the plan's display_name.
        """
        if len(self.plans) == 1 and self.plans[0].plan_key == "base":
            return [self]
        result = []
        for plan in self.plans:
            base_plan = Plan(
                plan_key="base",
                display_name=plan.display_name,
                monthly_cost=plan.monthly_cost,
                tiers=plan.tiers,
            )
            result.append(
                Institution(
                    name=plan.display_name,
                    plans=(base_plan,),
                    institution_type=self.institution_type,
                    protection_limit=self.protection_limit,
                )
            )
        return result
