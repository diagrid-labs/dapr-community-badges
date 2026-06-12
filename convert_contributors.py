#!/usr/bin/env python3
"""One-time: convert per-repo contributors.txt files into awarded.json ledgers.

Each repos/<owner>/<repo>/contributors.txt holds comma-separated GitHub handles
already awarded that repo's default Holopin badge. This pre-populates awarded.json
with {username, badgeId} so the first live run of award_holopin_badges.py does not
re-award them (see the new-folder backfill caveat in the design spec).

badgeId is the repo's defaultSticker, resolved from its remote .github/holopin.yml.
"""
from __future__ import annotations

import json
import os

from award_holopin_badges import (
    discover_repos,
    fetch_holopin_yml,
    resolve_default_sticker,
)


def parse_contributors(text: str) -> list:
    """Split a contributors.txt body into a de-duplicated, order-preserving list
    of handles. Tolerates extra whitespace, blank entries, and trailing commas."""
    seen = set()
    result = []
    for chunk in text.replace("\n", ",").split(","):
        handle = chunk.strip()
        if not handle or handle in seen:
            continue
        seen.add(handle)
        result.append(handle)
    return result


def main() -> int:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for owner, repo in discover_repos(base_dir):
        repo_dir = os.path.join(base_dir, "repos", owner, repo)
        contributors_path = os.path.join(repo_dir, "contributors.txt")
        if not os.path.exists(contributors_path):
            print(f"[{owner}/{repo}] no contributors.txt, skipping")
            continue

        try:
            yaml_text = fetch_holopin_yml(owner, repo)
            _alias, badge_id = resolve_default_sticker(yaml_text)
        except Exception as exc:  # noqa: BLE001 - per-repo isolation
            print(f"[{owner}/{repo}] ERROR resolving sticker: {exc}")
            continue

        with open(contributors_path, encoding="utf-8") as fh:
            handles = parse_contributors(fh.read())

        ledger = [{"username": h, "badgeId": badge_id} for h in handles]
        out_path = os.path.join(repo_dir, "awarded.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, indent=2)
        print(f"[{owner}/{repo}] wrote {len(ledger)} awards -> awarded.json "
              f"(badgeId={badge_id})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
