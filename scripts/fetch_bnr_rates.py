#!/usr/bin/env python3
"""
Fetches today's BNR reference rates (plus BTC/ETH) and writes them into
cursuri_bnr/ as a dated snapshot and latest.json.

This is what the weekly automation runs - see .github/workflows/bnr-rates.yml
for the scheduled job, or run it by hand any time:

    python scripts/fetch_bnr_rates.py

BNR publishes on banking days only, so a weekend or holiday run finds the same
banking date as the previous one. That's not an error; by default the snapshot
is simply rewritten. Pass --skip-existing to leave an already-fetched day
alone, which is what the automation does so an unchanged week produces no
commit.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bnr  # noqa: E402  (path has to be set up first)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch BNR exchange rates into cursuri_bnr/")
    parser.add_argument(
        "--dir",
        default=None,
        help=f"Where to write the snapshot (default: {bnr.RATES_DIR})",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do nothing if this banking day was already fetched",
    )
    parser.add_argument(
        "--no-crypto",
        action="store_true",
        help="Fetch only BNR's fiat rates, skipping the BTC/ETH lookup",
    )
    args = parser.parse_args()

    target = Path(args.dir) if args.dir else bnr.RATES_DIR

    try:
        snapshot = bnr.build_snapshot(include_crypto=not args.no_crypto)
    except Exception as error:
        print(f"Could not fetch rates from BNR: {error}", file=sys.stderr)
        return 1

    dated = target / f"{snapshot['date']}.json"
    if args.skip_existing and dated.is_file():
        print(f"{snapshot['date']} already fetched - nothing to do")
        return 0

    path = bnr.save_snapshot(snapshot, directory=target)

    fiat = ", ".join(
        f"{code} {snapshot['rates'][code]:.4f}"
        for code in ("EUR", "USD", "GBP")
        if code in snapshot["rates"]
    )
    crypto = ", ".join(f"{code} {entry['ron']:,.0f}" for code, entry in sorted(snapshot["crypto"].items()))

    print(f"BNR {snapshot['date']}: {fiat}" + (f" | {crypto}" if crypto else " | (no crypto rates)"))
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
