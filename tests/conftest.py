"""Shared test helpers and fixtures."""
from rate_allocator.domain.models import Institution, InstitutionType, Plan, Tier


def mk_inst(
    name: str,
    tiers: tuple[Tier, ...],
    institution_type: InstitutionType = "none",
    protection_limit: float | None = None,
) -> Institution:
    """Build a single-plan Institution — shorthand for tests."""
    plan = Plan(plan_key="base", display_name=name, monthly_cost=0.0, tiers=tiers)
    return Institution(
        name=name,
        plans=(plan,),
        institution_type=institution_type,
        protection_limit=protection_limit,
    )
