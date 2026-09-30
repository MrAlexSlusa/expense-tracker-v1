#!/usr/bin/env python3
"""
Copies the rate files the scheduled automation drops into its own folder
(curs_bnr, next to this repo's folder on the desktop) into the repo's
cursuri_bnr/, then commits and pushes them.

The automation writes a spreadsheet to that folder every Monday, but writing
it only updates this machine. The deployed backend reads cursuri_bnr/ as it
exists in the repository, so until the file is copied in and pushed the server
keeps falling back to fetching BNR directly. This is the step that closes that
gap - run it right after the automation writes the file:

    python scripts/publish_bnr_rates.py

The source folder can be changed with --source or the BNR_SOURCE_DIR
environment variable. If it does not exist the copy step is skipped and
whatever is already in cursuri_bnr/ is published as before.

Deliberately narrow. It stages cursuri_bnr/ and nothing else, so it is safe to
run with unrelated work in progress: whatever else is in the working tree stays
uncommitted and untouched. If the folder has not changed it does nothing and
says so, which is the normal outcome on a holiday week when BNR published the
same banking day twice.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RATES_SUBDIR = "cursuri_bnr"

# Where the automation leaves the files it produces. Outside the repo on
# purpose: the automation should not need to know about git.
DEFAULT_SOURCE = Path(os.environ.get("BNR_SOURCE_DIR") or Path.home() / "Desktop" / "claude" / "curs_bnr")
RATE_FILE_SUFFIXES = (".xlsx", ".xlsm", ".json")


def git(*args) -> subprocess.CompletedProcess:
    """Runs a git command in the repo. Never raises - every caller checks the
    return code itself, because a non-zero exit here is information (nothing
    to commit, push rejected) rather than a crash."""
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def import_from_source(source: Path) -> list[str]:
    """
    Copies new or changed rate files from the automation's folder into the
    repo's cursuri_bnr/. Returns the names that were copied.

    Files are only ever copied in, never deleted from either side, and Excel's
    `~$` lock files (a sheet someone has open) are ignored.
    """
    if not source.is_dir():
        print(f"{source} does not exist - skipping the copy step")
        return []

    target = REPO / RATES_SUBDIR
    target.mkdir(parents=True, exist_ok=True)

    copied = []
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.suffix.lower() not in RATE_FILE_SUFFIXES or path.name.startswith("~$"):
            continue
        destination = target / path.name
        if destination.is_file() and destination.read_bytes() == path.read_bytes():
            continue
        shutil.copy2(path, destination)
        copied.append(path.name)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit and push new BNR rate files")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Folder the automation writes rate files to (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be committed, then stop")
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Don't try to rebase onto the remote when the push is rejected as out of date",
    )
    args = parser.parse_args()

    if git("rev-parse", "--git-dir").returncode != 0:
        return fail(f"{REPO} is not a git repository")

    # The global rule for this repo: commits are the user's, never a tool's.
    # A missing identity would otherwise produce a commit authored by whatever
    # git guesses from the hostname.
    identity = git("config", "user.email").stdout.strip()
    if not identity:
        return fail("git user.email is not set - configure it before committing")

    copied = import_from_source(args.source)
    if copied:
        print(f"Copied {len(copied)} file(s) from {args.source}:")
        for name in copied:
            print(f"  {name}")

    if git("add", "--", RATES_SUBDIR).returncode != 0:
        return fail(f"Could not stage {RATES_SUBDIR}/")

    staged = git("diff", "--staged", "--name-only", "--", RATES_SUBDIR).stdout.strip()

    # A commit from an earlier run whose push failed is still sitting here.
    # Looking for it separately is what stops one bad week - the network was
    # down, the branch had moved on - from stranding that commit forever:
    # from the next run's point of view the folder already looks published.
    unpushed = git("log", "--oneline", "@{upstream}..HEAD").stdout.strip()

    if not staged and not unpushed:
        print(f"{RATES_SUBDIR}/ is unchanged - nothing to publish")
        return 0

    if staged:
        files = staged.splitlines()
        print(f"Publishing {len(files)} file(s) as {identity}:")
        for name in files:
            print(f"  {name}")
    else:
        print(f"Nothing new, but {len(unpushed.splitlines())} earlier commit(s) never reached the remote:")
        for line in unpushed.splitlines():
            print(f"  {line}")

    if args.dry_run:
        git("reset", "--quiet", "HEAD", "--", RATES_SUBDIR)
        print("Dry run - nothing committed or pushed")
        return 0

    if staged:
        # Name the dates in the message, so the history reads as a record of
        # which banking days are covered rather than identical commits.
        dates = sorted({part for name in staged.splitlines() for part in Path(name).stem.split() if any(c.isdigit() for c in part)})
        subject = "Update BNR exchange rates" + (f" ({', '.join(dates)})" if dates else "")

        commit = git("commit", "-m", subject)
        if commit.returncode != 0:
            return fail(f"Commit failed:\n{commit.stderr or commit.stdout}")
        print(f"Committed: {subject}")

    push = git("push")
    if push.returncode == 0:
        print("Pushed")
        return 0

    if args.no_pull:
        return fail(f"Push failed:\n{push.stderr or push.stdout}")

    # A rejected push almost always means the branch moved on elsewhere. Rebase
    # onto it and retry - but only with an otherwise clean tree, since a rebase
    # over unrelated edits is not something an unattended job should attempt.
    # Only tracked edits block a rebase. Untracked files - a stray download, a
    # scratch script - do not, and refusing to recover because of one would
    # strand the commit for a reason git itself doesn't care about.
    dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        return fail(
            f"Push was rejected and the working tree has other changes, so it was left alone.\n"
            f"The commit is made; run `git pull --rebase && git push` once the tree is clean.\n\n"
            f"{push.stderr or push.stdout}"
        )

    print("Push rejected - rebasing onto the remote and retrying")
    if git("pull", "--rebase").returncode != 0:
        git("rebase", "--abort")
        return fail(
            "Could not rebase onto the remote; the local commit is kept and nothing was pushed.\n"
            "Resolve it by hand with `git pull --rebase`."
        )

    retry = git("push")
    if retry.returncode != 0:
        return fail(f"Push still failed after rebasing:\n{retry.stderr or retry.stdout}")

    print("Pushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
