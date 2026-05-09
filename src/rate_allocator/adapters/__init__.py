"""Input/output adapters."""

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
    "seed_rates_database",
]
