#!/usr/bin/env python3
"""Award Holopin badges to Dapr contributors via the local `gh` CLI.

Run locally as an eligible Dapr + Holopin org member (gh must be authenticated
as that member). See README.md for the new-folder backfill caveat.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    import yaml
except ImportError:  # pragma: no cover - actionable message on missing dep
    sys.exit("PyYAML is required. Install it with: pip install pyyaml")

# Bot logins to exclude beyond the generic `[bot]` suffix. gh reports GitHub
# App authors with an `app/` prefix (e.g. `app/dependabot`), which is stripped
# before matching.
BOT_LOGINS = {"dependabot", "github-actions", "dapr-bot", "copilot-swe-agent"}

# Date used to reach back to the beginning when no since-cursor exists.
BACKFILL_SINCE = "2025-11-18"


class GhError(RuntimeError):
    """Raised when a `gh` invocation fails."""


def is_bot(login: str) -> bool:
    """True if the login is a bot we should never award."""
    if not login:
        return True
    if login.endswith("[bot]"):
        return True
    # GitHub App authors appear as "app/<name>"; match on the bare name.
    # A "/" can only come from that prefix (usernames cannot contain "/").
    name = login.rsplit("/", 1)[-1]
    return name.lower() in BOT_LOGINS


def resolve_default_sticker(yaml_text: str) -> tuple:
    """Parse holopin.yml text and return (alias, badge_id) for the default sticker.

    Raises ValueError if the config has no defaultSticker, the sticker is not
    found, or the matched sticker has no alias.
    """
    config = yaml.safe_load(yaml_text) or {}
    default_id = config.get("defaultSticker")
    if not default_id:
        raise ValueError("holopin.yml has no defaultSticker")
    for sticker in config.get("stickers", []) or []:
        if sticker.get("id") == default_id:
            alias = sticker.get("alias")
            if not alias:
                raise ValueError(f"sticker {default_id} has no alias")
            return alias, default_id
    raise ValueError(f"defaultSticker {default_id} not found in stickers")


def read_since(repo_dir: str, override: str = None) -> str:
    """Return the since-cursor: the override if given, else state.json's lastRun,
    else None (meaning reach back to the beginning)."""
    if override:
        return override
    state_path = os.path.join(repo_dir, "state.json")
    if not os.path.exists(state_path):
        return None
    with open(state_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("lastRun")


def write_last_run(repo_dir: str, run_start_iso: str) -> None:
    """Persist the run-start timestamp as the new lastRun cursor."""
    state_path = os.path.join(repo_dir, "state.json")
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump({"lastRun": run_start_iso}, fh, indent=2)


def read_awarded(repo_dir: str) -> list:
    """Load the awarded.json ledger as a list of {username, badgeId} dicts."""
    path = os.path.join(repo_dir, "awarded.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def already_awarded(ledger: list, username: str, badge_id: str) -> bool:
    """True if (username, badge_id) is already in the ledger."""
    return any(
        entry.get("username") == username and entry.get("badgeId") == badge_id
        for entry in ledger
    )


def append_awarded(repo_dir: str, ledger: list, username: str, badge_id: str) -> None:
    """Append a new award to the in-memory ledger and persist the whole list."""
    ledger.append({"username": username, "badgeId": badge_id})
    path = os.path.join(repo_dir, "awarded.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2)


def distinct_human_authors(prs: list) -> list:
    """From merged-PR records, return [(login, pr_number), ...] with one entry per
    human author (most recent PR kept), ordered most-recent-first. Bots and ghost
    (null) authors are excluded."""
    ordered = sorted(prs, key=lambda p: p.get("mergedAt") or "", reverse=True)
    seen = set()
    result = []
    for pr in ordered:
        author = pr.get("author") or {}
        login = author.get("login")
        # gh's is_bot flag is the most reliable signal; fall back to login matching.
        if author.get("is_bot") or not login or is_bot(login):
            continue
        if login in seen:
            continue
        seen.add(login)
        result.append((login, pr["number"]))
    return result


# ---------------------------------------------------------------------------
# Task 7: The `gh` runner and fetch_holopin_yml
# ---------------------------------------------------------------------------

def run_gh(args: list) -> str:
    """Run `gh` with the given args and return stdout. Raises GhError on failure."""
    # gh emits UTF-8; force it so Windows doesn't decode as cp1252 and choke on
    # emoji / non-Latin characters in PR titles or author names.
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise GhError(
            f"`gh {' '.join(args)}` failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def fetch_holopin_yml(owner: str, repo: str, run_gh=run_gh) -> str:
    """Fetch and base64-decode .github/holopin.yml from the remote repo."""
    out = run_gh(["api", f"repos/{owner}/{repo}/contents/.github/holopin.yml"])
    data = json.loads(out)
    return base64.b64decode(data["content"]).decode("utf-8")


# ---------------------------------------------------------------------------
# Task 8: query_merged_prs
# ---------------------------------------------------------------------------

def query_merged_prs(owner: str, repo: str, since: str, limit: int, run_gh=run_gh) -> list:
    """List merged PRs (number, author, mergedAt) merged on/after `since`.
    `since` of None reaches back to BACKFILL_SINCE."""
    effective_since = since or BACKFILL_SINCE
    out = run_gh([
        "pr", "list",
        "--repo", f"{owner}/{repo}",
        "--state", "merged",
        "--search", f"merged:>={effective_since}",
        "--json", "number,author,mergedAt",
        "--limit", str(limit),
    ])
    return json.loads(out)


# ---------------------------------------------------------------------------
# Task 9: award_badge
# ---------------------------------------------------------------------------

def award_badge(owner: str, repo: str, pr_number: int, username: str, alias: str,
                dry_run: bool, run_gh=run_gh) -> str:
    """Post the Holopin trigger comment on the PR. Returns the comment body.
    In dry-run, builds the body but posts nothing."""
    body = f"@holopin-bot @{username} {alias} Thank you! Here's a digital badge as a small token of appreciation."
    if not dry_run:
        run_gh([
            "pr", "comment", str(pr_number),
            "--repo", f"{owner}/{repo}",
            "--body", body,
        ])
    return body


# ---------------------------------------------------------------------------
# Task 10: discover_repos
# ---------------------------------------------------------------------------

def discover_repos(base_dir: str) -> list:
    """Return sorted [(owner, repo), ...] from two-level paths under repos/.
    The presence of a folder is the opt-in."""
    repos_root = os.path.join(base_dir, "repos")
    if not os.path.isdir(repos_root):
        return []
    result = []
    for owner in sorted(os.listdir(repos_root)):
        owner_path = os.path.join(repos_root, owner)
        if not os.path.isdir(owner_path):
            continue
        for repo in sorted(os.listdir(owner_path)):
            if os.path.isdir(os.path.join(owner_path, repo)):
                result.append((owner, repo))
    return result


# ---------------------------------------------------------------------------
# Task 11: process_repo
# ---------------------------------------------------------------------------

def process_repo(owner: str, repo: str, base_dir: str, *,
                 since_override: str = None, dry_run: bool = False,
                 limit: int = 1000, sleep_seconds: float = 3,
                 run_start: str = None, run_gh=run_gh, sleep_fn=time.sleep,
                 log=print) -> dict:
    """Process one repo: resolve sticker, find new human authors since the cursor,
    award each once, then (unless dry-run) advance the cursor.

    Raises on unrecoverable per-repo errors; the caller isolates each repo."""
    repo_dir = os.path.join(base_dir, "repos", owner, repo)
    os.makedirs(repo_dir, exist_ok=True)

    yaml_text = fetch_holopin_yml(owner, repo, run_gh=run_gh)
    alias, badge_id = resolve_default_sticker(yaml_text)

    since = read_since(repo_dir, override=since_override)
    prs = query_merged_prs(owner, repo, since, limit, run_gh=run_gh)
    authors = distinct_human_authors(prs)

    ledger = read_awarded(repo_dir)
    awarded = []
    for username, pr_number in authors:
        if already_awarded(ledger, username, badge_id):
            continue
        award_badge(owner, repo, pr_number, username, alias, dry_run, run_gh=run_gh)
        log(f"[{owner}/{repo}] {'(dry-run) would award' if dry_run else 'awarded'} "
            f"{alias} to @{username} (PR #{pr_number})")
        if not dry_run:
            # Award-then-record: persist the ledger AFTER the comment succeeds.
            append_awarded(repo_dir, ledger, username, badge_id)
            sleep_fn(sleep_seconds)
        awarded.append((username, pr_number))

    if not dry_run:
        write_last_run(repo_dir, run_start)

    return {"alias": alias, "badgeId": badge_id, "awarded": awarded}


# ---------------------------------------------------------------------------
# Task 12: preflight
# ---------------------------------------------------------------------------

def preflight(run_gh=run_gh) -> None:
    """Verify `gh auth status` succeeds. PyYAML is checked at import time.
    Exits with an actionable message on failure.

    Note: this cannot verify Dapr Holopin org membership; running as a
    non-eligible account will silently produce no badges."""
    try:
        run_gh(["auth", "status"])
    except Exception as exc:  # noqa: BLE001 - surface any gh failure clearly
        raise SystemExit(
            "Preflight failed: `gh auth status` did not succeed. "
            "Install the gh CLI and run `gh auth login` as an eligible "
            f"Dapr + Holopin org member.\nDetails: {exc}"
        )


# ---------------------------------------------------------------------------
# Task 13: CLI parsing and main wiring
# ---------------------------------------------------------------------------

HELP_EPILOG = """\
CAVEAT — new repo folders reach back to the beginning. A brand-new folder with
no state.json queries ALL historical merged PRs and will re-award contributors
who were already awarded manually (Holopin mints a new claim URL each time).
For such repos, run --dry-run first and/or pre-populate awarded.json with
already-awarded contributors before the first live run.
"""


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Award Holopin badges to Dapr contributors via the local gh CLI.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be awarded; touch nothing. "
                             "Recommended for the first run on a big repo.")
    parser.add_argument("--repo", action="append", default=[], metavar="owner/repo",
                        help="Process only this repo (repeatable). Default: all repo folders.")
    parser.add_argument("--since", default=None, metavar="ISO8601",
                        help="Override the stored lastRun for this run only (not persisted).")
    parser.add_argument("--base-dir", default=None, metavar="PATH",
                        help="Where repos/ lives (default: alongside the script).")
    parser.add_argument("--sleep", type=float, default=3.0, metavar="SECONDS",
                        help="Delay between awards (default 3.0).")
    return parser.parse_args(argv)


def utc_now_iso() -> str:
    """Run-start timestamp in UTC, e.g. 2026-06-12T10:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    args = parse_args(argv)
    preflight()

    base_dir = args.base_dir or os.path.dirname(os.path.abspath(__file__))
    run_start = utc_now_iso()

    if args.repo:
        for r in args.repo:
            if "/" not in r:
                print(f"ERROR: --repo value {r!r} must be in owner/repo format.", file=sys.stderr)
                return 1
        repos = [tuple(r.split("/", 1)) for r in args.repo]
    else:
        repos = discover_repos(base_dir)

    if not repos:
        print("No repos to process. Create folders under repos/<owner>/<repo> "
              "or pass --repo owner/repo.", file=sys.stderr)
        return 0

    had_error = False
    for owner, repo in repos:
        try:
            summary = process_repo(
                owner, repo, base_dir,
                since_override=args.since,
                dry_run=args.dry_run,
                sleep_seconds=args.sleep,
                run_start=run_start,
            )
            count = len(summary["awarded"])
            print(f"[{owner}/{repo}] done: {count} "
                  f"{'would be awarded' if args.dry_run else 'awarded'} "
                  f"({summary['alias']})")
        except Exception as exc:  # noqa: BLE001 - per-repo isolation
            print(f"[{owner}/{repo}] ERROR: {exc}", file=sys.stderr)
            had_error = True
    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
