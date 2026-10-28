"""
Pulls new transactions for every linked bank. This is what makes the import
automatic - without it the user still has to open the app and press sync.

Run it on a schedule (Render cron job, see render.yaml):

    python -m scripts.sync_banks

Once a day is plenty: banks only book card payments once a day anyway, and
GoCardless rate-limits transaction calls per account per day, so a tighter
schedule buys nothing and risks hitting the cap.

Exits 0 even when individual connections failed. A dead consent is a normal
state the app shows the user, not a reason to fail the cron job and bury the
successful syncs in a red deploy log; the failures are printed and recorded
on the connection row.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import bank_sync, gocardless  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    if not gocardless.is_configured():
        print("GOCARDLESS_SECRET_ID / GOCARDLESS_SECRET_KEY are not set - nothing to sync")
        return 0

    db = SessionLocal()
    try:
        result = bank_sync.sync_all(db)
    finally:
        db.close()

    print(
        "{} connection(s): {} imported, {} awaiting a category, {} skipped, {} already seen".format(
            result["connections"],
            result["imported"],
            result["pending"],
            result["skipped"],
            result["duplicates"],
        )
    )
    for error in result["errors"]:
        print("  ! " + error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
