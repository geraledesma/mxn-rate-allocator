#!/usr/bin/env python3
"""Populate SQLite rate database from YAML (canonical snapshot for demos)."""

from __future__ import annotations

import argparse
from pathlib import Path

from rate_allocator.adapters.sqlite_loader import seed_rates_database

REPO = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create or overwrite SQLite rates DB from YAML institutions.",
    )
    ap.add_argument(
        "--yaml",
        type=Path,
        default=REPO / "data" / "sample1.yaml",
        help="YAML file with institutions: list (default: data/sample1.yaml)",
    )
    ap.add_argument(
        "--db",
        type=Path,
        default=REPO / "data" / "rates.db",
        help="Output SQLite path (default: data/rates.db)",
    )
    args = ap.parse_args()
    seed_rates_database(args.yaml, args.db)
    print(f"Wrote {args.db} ({args.db.stat().st_size} bytes) from {args.yaml}")


if __name__ == "__main__":
    main()
