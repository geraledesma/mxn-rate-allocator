"""YAML parser adapter for institution configuration."""

from pathlib import Path

import yaml

from rate_allocator.domain.models import Constraint, Institution, Plan, Tier


def load_institutions_from_yaml(path: str | Path) -> list[Institution]:
    """Load institutions from YAML file."""
    return load_institutions_with_overrides(path, {})


def load_institutions_with_overrides(
    path: str | Path, active_overrides: dict[str, list[str]] | None = None
) -> list[Institution]:
    """Load institutions and optionally override active constraint types."""
    active_overrides = active_overrides or {}
    data = _read_yaml(path)
    return [
        _parse_institution(inst_data, active_overrides.get(inst_data["name"]))
        for inst_data in data.get("institutions", [])
    ]


def _read_yaml(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _parse_institution(
    institution_data: dict,
    institution_active_overrides: list[str] | None,
) -> Institution:
    name = institution_data["name"]

    if "plans" in institution_data:
        plans = tuple(
            _parse_plan(plan_data, name, institution_active_overrides)
            for plan_data in institution_data["plans"]
        )
    else:
        # Shorthand: tiers at institution level → single base plan
        plans = (
            Plan(
                plan_key="base",
                display_name=name,
                monthly_cost=float(institution_data.get("monthly_cost", 0.0)),
                tiers=tuple(
                    _parse_tier(t, institution_active_overrides)
                    for t in institution_data["tiers"]
                ),
            ),
        )

    return Institution(
        name=name,
        plans=plans,
        institution_type=institution_data.get("institution_type", "none"),
        protection_limit=institution_data.get("protection_limit"),
    )


def _parse_plan(
    plan_data: dict,
    institution_name: str,
    institution_active_overrides: list[str] | None,
) -> Plan:
    return Plan(
        plan_key=plan_data["plan_key"],
        display_name=plan_data.get("display_name", institution_name),
        monthly_cost=float(plan_data.get("monthly_cost", 0.0)),
        tiers=tuple(
            _parse_tier(t, institution_active_overrides)
            for t in plan_data["tiers"]
        ),
    )


def _parse_tier(
    tier_data: dict,
    institution_active_overrides: list[str] | None,
) -> Tier:
    return Tier(
        limit=_parse_tier_limit(tier_data["limit"]),
        rate=tier_data["rate"],
        constraints=tuple(
            _parse_constraint(constraint_data, institution_active_overrides)
            for constraint_data in tier_data.get("constraints", [])
        ),
    )


def _parse_tier_limit(raw_limit: float | str) -> float:
    if raw_limit == "inf":
        return float("inf")
    return float(raw_limit)


def _parse_constraint(
    constraint_data: dict,
    institution_active_overrides: list[str] | None,
) -> Constraint:
    constraint_type = constraint_data["type"]
    return Constraint(
        type=constraint_type,
        cost=constraint_data.get("cost", 0.0),
        benefit=constraint_data.get("benefit"),
        condition_value=constraint_data.get("condition_value"),
        active=_resolve_constraint_active(
            constraint_data.get("active", True),
            constraint_type,
            institution_active_overrides,
        ),
        constraint_condition=constraint_data.get("constraint_condition"),
        benefit_condition=constraint_data.get("benefit_condition"),
    )


def _resolve_constraint_active(
    yaml_active: bool,
    constraint_type: str,
    institution_overrides: list[str] | None,
) -> bool:
    if institution_overrides is not None:
        return constraint_type in institution_overrides
    return yaml_active
