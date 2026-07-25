"""CLI to ingest a YAML file (institutions and/or regulatory rules) into the DB.

Each invocation creates at most one ``change_batches`` row per kind (rates,
rules), tagged with ``source=yaml:<path>`` plus an optional actor and note.
Re-running with no changes is a no-op (no new versions written), which makes
this safe to run from cron or CI.

Usage:
    python scripts/ingest_yaml.py data/sample1.yaml --note "Mar rates"
    python scripts/ingest_yaml.py data/regulatory_rules.mx.yaml --rules
    python scripts/ingest_yaml.py data/sample1.yaml --deactivate-missing
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml
from rate_allocator.persistence import (
    create_db_engine,
    get_database_url,
    init_schema,
    session_scope,
)
from rate_allocator.persistence.ingest import (
    ingest_institutions,
    ingest_regulatory_rules,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest institutions or regulatory rules from a YAML file into "
            "the SCD2 store. Idempotent: identical inputs are no-ops."
        )
    )
    parser.add_argument("path", type=Path, help="Path to a YAML file.")
    parser.add_argument(
        "--rules",
        action="store_true",
        help="Treat the file as a regulatory-rules YAML instead of institutions.",
    )
    parser.add_argument(
        "--actor",
        default=None,
        help="Optional actor label recorded on the change batch.",
    )
    parser.add_argument(
        "--note",
        default=None,
        help="Optional free-text note recorded on the change batch.",
    )
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help=(
            "Close institutions present in the DB but absent from this file. "
            "Off by default so partial uploads don't wipe the catalog."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "Override the DB URL (otherwise read from RATE_ALLOCATOR_DB_URL or "
            "default to a local SQLite file)."
        ),
    )
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help=(
            "Run create_all() before ingesting; convenient for first-run setup. "
            "For tracked deployments, prefer running Alembic migrations."
        ),
    )
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        default=None,
        metavar="DATETIME",
        help=(
            "Override the SCD2 effective timestamp (ISO 8601, e.g. 2026-08-06T00:00:00). "
            "Use for proforma entries: the change is recorded with this future date and "
            "will not appear in the app until that date is reached."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    yaml_path: Path = args.path
    if not yaml_path.exists():
        print(f"error: file not found: {yaml_path}", file=sys.stderr)
        return 2

    db_url = args.db_url or get_database_url()
    engine = create_db_engine(db_url)
    if args.init_schema:
        init_schema(engine)

    source = f"yaml:{yaml_path}"
    with session_scope(engine) as session:
        if args.rules:
            rules = load_regulatory_rules_from_yaml(yaml_path)
            stats = ingest_regulatory_rules(
                session, rules, source=source, actor=args.actor, note=args.note
            )
        else:
            as_of = args.as_of
            if as_of is not None and as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)
            institutions = load_institutions_from_yaml(yaml_path)
            stats = ingest_institutions(
                session,
                institutions,
                source=source,
                actor=args.actor,
                note=args.note,
                deactivate_missing=args.deactivate_missing,
                now=as_of,
            )

    print(f"db_url: {db_url}")
    print(f"source: {source}")
    print(f"changes: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
