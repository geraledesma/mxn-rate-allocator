"""Backward-compatible exports for YAML loader adapters."""

from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.sqlite_loader import (
    load_institutions_from_sqlite,
    seed_rates_database,
)
from rate_allocator.adapters.yaml_loader import (
    load_institutions_from_yaml,
    load_institutions_with_overrides,
)

__all__ = [
    "load_institutions_from_sqlite",
    "load_institutions_from_yaml",
    "load_institutions_with_overrides",
    "load_regulatory_rules_from_yaml",
    "seed_rates_database",
]
