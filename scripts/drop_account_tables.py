#!/usr/bin/env python3
"""
Removes what the accounts feature left behind in an already-deployed database.

The feature is gone from the code, so nothing reads `accounts` or
`expenses.account_id` any more - but `create_all` only ever creates tables and
`ensure_columns` only ever adds columns, so neither of them disappears on its
own. A database created after the removal never has them and this script says
so and stops.

Run it against whichever database you want cleaned, by pointing DATABASE_URL at
it exactly as the app does (default: the local sqlite file):

    python scripts/drop_account_tables.py                  # show the plan
    python scripts/drop_account_tables.py --yes            # apply it

This deletes data: the accounts themselves, and which account each expense was
paid from. The expenses, their amounts, categories and dates are untouched -
only the pointer goes. That is why --yes is required rather than a prompt: this
is likely to be run against production, where an accidental invocation should
do nothing at all.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from app.database import DATABASE_URL, engine

TABLE = "accounts"
COLUMN_TABLE = "expenses"
COLUMN = "account_id"

# SQLite learned ALTER TABLE ... DROP COLUMN in 3.35 (2021). Older builds would
# need the whole table copied out and back, which is not worth writing for a
# local dev file - upgrading Python is the easier fix.
MIN_SQLITE = (3, 35, 0)


def sqlite_too_old() -> str:
    """The installed SQLite version, if it can't drop a column; "" otherwise."""
    if not DATABASE_URL.startswith("sqlite"):
        return ""
    with engine.connect() as connection:
        version = connection.execute(text("select sqlite_version()")).scalar_one()
    parts = tuple(int(p) for p in version.split("."))
    return "" if parts >= MIN_SQLITE else version


def main() -> int:
    parser = argparse.ArgumentParser(description="Drop the leftover accounts table and column")
    parser.add_argument("--yes", action="store_true", help="Actually apply the changes")
    args = parser.parse_args()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_table = TABLE in tables
    has_column = COLUMN_TABLE in tables and COLUMN in {
        c["name"] for c in inspector.get_columns(COLUMN_TABLE)
    }

    print(f"Database: {DATABASE_URL}")
    if not has_table and not has_column:
        print("Nothing to do - neither the accounts table nor expenses.account_id is there.")
        return 0

    statements = []
    # The column goes first: it is the foreign key into accounts, and Postgres
    # refuses to drop a table something still references.
    if has_column:
        statements.append(f"ALTER TABLE {COLUMN_TABLE} DROP COLUMN {COLUMN}")
    if has_table:
        statements.append(f"DROP TABLE {TABLE}")

    for statement in statements:
        print(f"  {statement};")

    if not args.yes:
        print("\nNothing applied. Re-run with --yes to apply.")
        return 0

    old_sqlite = sqlite_too_old() if has_column else ""
    if old_sqlite:
        print(
            f"\nSQLite {old_sqlite} cannot drop a column (needs "
            f"{'.'.join(str(p) for p in MIN_SQLITE)}+). Delete the local database "
            "file and let the app rebuild it instead.",
            file=sys.stderr,
        )
        return 1

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
