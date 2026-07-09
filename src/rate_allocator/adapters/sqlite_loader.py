"""Load institutions from a normalized SQLite DB (alternative to YAML)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from rate_allocator.domain.models import Constraint, Institution, Plan, Tier


def ensure_rates_schema(conn: sqlite3.Connection) -> None:
    """Create institution / tier / constraint tables when missing."""
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS institution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            institution_type TEXT NOT NULL DEFAULT 'none',
            protection_limit REAL,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tier (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_id INTEGER NOT NULL REFERENCES institution (id)
                ON DELETE CASCADE,
            tier_order INTEGER NOT NULL,
            rate REAL NOT NULL,
            limit_value REAL NOT NULL DEFAULT 0,
            limit_is_inf INTEGER NOT NULL DEFAULT 0,
            UNIQUE (institution_id, tier_order),
            CHECK (limit_is_inf IN (0, 1))
        );

        CREATE TABLE IF NOT EXISTS tier_constraint (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tier_id INTEGER NOT NULL REFERENCES tier (id) ON DELETE CASCADE,
            constraint_order INTEGER NOT NULL,
            type TEXT NOT NULL,
            cost REAL NOT NULL DEFAULT 0,
            benefit TEXT,
            condition_value REAL,
            active INTEGER NOT NULL DEFAULT 1,
            constraint_condition TEXT,
            benefit_condition TEXT,
            UNIQUE (tier_id, constraint_order)
        );

        CREATE INDEX IF NOT EXISTS idx_tier_inst ON tier (institution_id);

        CREATE INDEX IF NOT EXISTS idx_constraint_tier ON tier_constraint (tier_id);
        """
    )


def clear_rates_rows(conn: sqlite3.Connection) -> None:
    """Remove all institutional data (preserves schema)."""
    conn.execute("DELETE FROM tier_constraint")
    conn.execute("DELETE FROM tier")
    conn.execute("DELETE FROM institution")


def _tier_limit_parts_from_yaml(raw_limit) -> tuple[float, int]:
    if raw_limit == "inf":
        return 0.0, 1
    if isinstance(raw_limit, float) and raw_limit == float("inf"):
        return 0.0, 1
    return float(raw_limit), 0


def _resolve_constraint_active(
    yaml_active: bool,
    constraint_type: str,
    institution_overrides: list[str] | None,
) -> bool:
    if institution_overrides is not None:
        return constraint_type in institution_overrides
    return yaml_active


def populate_rates_sqlite_from_yaml_file(
    conn: sqlite3.Connection, yaml_path: str | Path
) -> None:
    """Rebuild rate rows from YAML (same shape as ``data/sample*.yaml`` institutions list)."""
    path = Path(yaml_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    institutions = data.get("institutions", [])
    clear_rates_rows(conn)
    conn.execute("PRAGMA foreign_keys = ON")

    for sort_ix, inst in enumerate(institutions):
        name = inst["name"]
        itype = str(inst.get("institution_type", "none"))
        prot = inst.get("protection_limit")
        prot_sql = float(prot) if prot is not None else None
        cur = conn.execute(
            """
            INSERT INTO institution (name, institution_type, protection_limit, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (name, itype, prot_sql, sort_ix),
        )
        inst_id = int(cur.lastrowid)

        tiers_list = inst["tiers"]
        for tier_order, tier_data in enumerate(tiers_list):
            lim_raw = tier_data["limit"]
            limit_value, limit_is_inf = _tier_limit_parts_from_yaml(lim_raw)
            rate = float(tier_data["rate"])

            tier_cur = conn.execute(
                """
                INSERT INTO tier (
                    institution_id, tier_order, rate, limit_value, limit_is_inf
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    inst_id,
                    tier_order,
                    rate,
                    limit_value,
                    limit_is_inf,
                ),
            )
            tier_id = int(tier_cur.lastrowid)

            constraint_list = tier_data.get("constraints") or []
            for cc_order, c in enumerate(constraint_list):
                ctype = str(c["type"])
                yaml_active_flag = bool(c.get("active", True))
                cond_val = c.get("condition_value")
                conn.execute(
                    """
                    INSERT INTO tier_constraint (
                        tier_id, constraint_order, type, cost, benefit,
                        condition_value, active, constraint_condition,
                        benefit_condition
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tier_id,
                        cc_order,
                        ctype,
                        float(c.get("cost", 0.0)),
                        c.get("benefit"),
                        float(cond_val) if cond_val is not None else None,
                        1 if yaml_active_flag else 0,
                        c.get("constraint_condition"),
                        c.get("benefit_condition"),
                    ),
                )


def seed_rates_database(yaml_source: str | Path, db_destination: str | Path) -> None:
    """Create/update schema and populate ``db_destination`` from ``yaml_source``."""
    dest = Path(db_destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(dest))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_rates_schema(conn)
        populate_rates_sqlite_from_yaml_file(conn, yaml_source)
        conn.commit()
    finally:
        conn.close()


def load_institutions_from_sqlite(
    db_path: str | Path,
    active_overrides: dict[str, list[str]] | None = None,
) -> list[Institution]:
    """Load institution models from SQLite (tier order preserved)."""

    active_overrides = active_overrides or {}
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(
            "SQLite DB not found "
            f"({path}); run scripts/seed_rates_sqlite.py to create data/rates.db."
        )

    conn = sqlite3.connect(str(path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        institutions: list[Institution] = []
        inst_rows = conn.execute(
            """
            SELECT id, name, institution_type, protection_limit
            FROM institution
            ORDER BY sort_order, id
            """
        ).fetchall()

        for row in inst_rows:
            inst_id = int(row["id"])
            name = str(row["name"])
            overrides = active_overrides.get(name)

            tier_rows = conn.execute(
                """
                SELECT id, rate, limit_value, limit_is_inf
                FROM tier
                WHERE institution_id = ?
                ORDER BY tier_order, id
                """,
                (inst_id,),
            ).fetchall()

            tiers: list[Tier] = []
            for t_row in tier_rows:
                tier_id = int(t_row["id"])
                limit_is_inf = int(t_row["limit_is_inf"])
                limit_val = (
                    float("inf")
                    if limit_is_inf
                    else float(t_row["limit_value"])
                )
                rate = float(t_row["rate"])

                c_rows = conn.execute(
                    """
                    SELECT type, cost, benefit, condition_value,
                           active, constraint_condition, benefit_condition
                    FROM tier_constraint
                    WHERE tier_id = ?
                    ORDER BY constraint_order, id
                    """,
                    (tier_id,),
                ).fetchall()

                constraints: tuple[Constraint, ...] = tuple(
                    Constraint(
                        type=str(c_row["type"]),
                        cost=float(c_row["cost"] or 0.0),
                        benefit=c_row["benefit"],
                        condition_value=(
                            float(c_row["condition_value"])
                            if c_row["condition_value"] is not None
                            else None
                        ),
                        active=_resolve_constraint_active(
                            bool(c_row["active"]),
                            str(c_row["type"]),
                            overrides,
                        ),
                        constraint_condition=c_row["constraint_condition"],
                        benefit_condition=c_row["benefit_condition"],
                    )
                    for c_row in c_rows
                )

                tiers.append(Tier(limit=limit_val, rate=rate, constraints=constraints))

            prot_raw = row["protection_limit"]
            protection_limit = (
                float(prot_raw)
                if prot_raw is not None
                else None
            )

            plan = Plan(
                plan_key="base",
                display_name=name,
                monthly_cost=0.0,
                tiers=tuple(tiers),
            )
            institutions.append(
                Institution(
                    name=name,
                    plans=(plan,),
                    institution_type=row["institution_type"],  # type: ignore[arg-type]
                    protection_limit=protection_limit,
                )
            )

        return institutions
    finally:
        conn.close()
