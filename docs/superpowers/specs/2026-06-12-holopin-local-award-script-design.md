# Holopin badge awards via a local Python script + `gh` CLI

## Summary

A single cross-platform Python script, `award_holopin_badges.py`, that **@marcduiker**
runs locally to award Holopin badges to Dapr contributors. The script:

1. discovers participating repos from local per-repo folders,
2. finds human contributors whose PRs merged since the last run,
3. awards each the repo's **default** Holopin badge once, by posting
   `@holopin-bot @user <alias>` as a comment on one of their merged PRs via `gh`.

Dedup and the "what's new since last time" cursor are kept in **local per-repo files**.

## Why this replaces the Actions approach

The original automation (see `holopin-automation.md`) ran in GitHub Actions and therefore
needed a personal access token (`HOLOPIN_AWARD_TOKEN`) so that award comments were authored
by an eligible Dapr + Holopin org member rather than `github-actions[bot]`.

Running locally removes that entire problem. `gh` is already authenticated as **@marcduiker**,
who is a member of both the Dapr GitHub org and the Dapr Holopin org, so every comment the
script posts is already authored by an authorized issuer. **No PAT, no org secret, no
`pull_request_target` machinery.**

> **Linchpin (unchanged from the original):** Holopin only honors a trigger from someone who
> is a member of both the Dapr GitHub org *and* the Dapr Holopin org. Here that issuer is
> whoever `gh` is authenticated as — which must be @marcduiker (or another eligible member).
> The script's preflight verifies `gh auth status`, but it cannot verify Holopin org
> membership; running as a non-eligible account will silently produce no badges.

## Prerequisites

- **`gh` CLI** installed and authenticated as @marcduiker (`gh auth status` succeeds), with
  scope to read PRs and write issue/PR comments on the participating `dapr/*` repos.
- **Python 3.9+** with **PyYAML** (`pip install pyyaml`). Standard library otherwise.
- @marcduiker is a member of the Dapr Holopin org with linked accounts on holopin.io.

## Folder layout

You create one folder per participating repo. **The presence of the folder is the opt-in.**
The `owner/repo` path under `repos/` *is* the GitHub repo identity.

```
holopin/
  repos/
    dapr/dapr/
      awarded.json     # [ { "username": "...", "badgeId": "..." }, ... ]  — dedup ledger
      state.json       # { "lastRun": "2026-06-12T10:00:00Z" }              — since-cursor
    dapr/docs/
      awarded.json
      state.json
```

- A repo folder is identified by its two-level path under `repos/` (`<owner>/<repo>`).
- `awarded.json` and `state.json` are created automatically on first run if missing.
- `--base-dir` overrides where `repos/` lives (default: alongside the script).

### `awarded.json` format

A list of `{username, badgeId}` objects. Dedup is keyed on the **`(username, badgeId)`
pair**, so a contributor can still earn a *different* badge in the same repo later.

```json
[
  { "username": "alice", "badgeId": "clrqh1xny39170fl75cawk0h5" },
  { "username": "bob",   "badgeId": "clrqh1xny39170fl75cawk0h5" }
]
```

### `state.json` format

```json
{ "lastRun": "2026-06-12T10:00:00Z" }
```

Absent or missing `lastRun` → the run reaches back to the beginning (first-run backfill).

## Per-repo data flow (each run)

For every repo folder discovered (or each `--repo` given):

1. **Resolve the default sticker.** Read remote `.github/holopin.yml` via
   `gh api repos/<owner>/<repo>/contents/.github/holopin.yml`, decode, and parse with
   PyYAML. Resolve `defaultSticker` → the matching sticker's `(alias, badgeId)`.
   - No `holopin.yml`, or sticker unresolvable → **skip the repo** with a warning.
2. **Read the since-cursor.** Load local `state.json`; take `lastRun` (absent → reach back
   to the beginning). `--since <ISO8601>` overrides the stored value for this run only.
3. **Query merged PRs.** `gh pr list --repo <owner>/<repo> --state merged
   --search "merged:>=<since>" --json number,author,mergedAt --limit <n>`. Collect the
   **distinct human authors**, keeping one PR number per author (e.g. the most recent).
   Filter out bots: any login ending in `[bot]`, plus `dependabot`, `github-actions`,
   `dapr-bot`.
4. **Award the new ones.** Load local `awarded.json`. For each author **not** already
   holding `(username, badgeId)`:
   - Post the trigger comment via
     `gh pr comment <number> --repo <owner>/<repo> --body "@holopin-bot @<user> <alias>"`.
   - Append `{username, badgeId}` to `awarded.json` and persist.
   - `sleep` `--sleep` seconds (default ~3s) between awards (rate-limit courtesy).
5. **Advance the cursor.** On a clean repo completion, write
   `state.json.lastRun = <run start time>` (captured once at the start of the run, in UTC).

## CLI

```
award_holopin_badges.py [--dry-run] [--repo owner/repo ...] [--since ISO8601]
                        [--base-dir PATH] [--sleep SECONDS]
```

- `--dry-run` — print what *would* be awarded (resolved alias/badge per repo, and each
  recipient + PR) and touch nothing. **Recommended for the first run on a big repo.**
- `--repo owner/repo` — process only this repo (repeatable). Default: all repo folders.
- `--since <ISO8601>` — override the stored `lastRun` for this run (e.g. force a full
  backfill with `--since 2015-01-01`, or re-check a window). **Not persisted**; the normal
  cursor logic still writes the real run timestamp on success.
- `--base-dir <path>` — where `repos/` lives (default: alongside the script).
- `--sleep <seconds>` — delay between awards (default `3`).

## Error handling

- **Per-repo isolation.** Each repo is processed in its own `try/except`. A failure (missing
  `holopin.yml`, `gh` error, parse error) is logged and the script moves to the next repo —
  one bad repo never aborts the whole run.
- **Award-then-record ordering** (kept from the original doc). Post the comment first, then
  append to `awarded.json`. If recording fails *after* a successful award, the worst case is
  one duplicate award on the next run — deliberately preferred over marking someone awarded
  who never received the badge.
- **Cursor only advances on success.** `state.json.lastRun` is written only if the repo
  completed without an unhandled error, so a mid-run failure means the next run re-checks the
  same window. Dedup via `awarded.json` makes that re-check safe.
- **Preflight.** Verify `gh auth status` succeeds and that `gh` and PyYAML are importable;
  exit with a clear, actionable message if not.

## Edge cases

- **No seeding step.** Because normal runs discover awards from the `lastRun` cursor (not
  full history) and the ledger dedups, there is no separate seed script.
  - **Caveat — new repo folders reach back to the beginning.** A brand-new folder with no
    `state.json` will query all historical merged PRs and re-award contributors who were
    already awarded *manually* before automation existed (Holopin mints a new claim URL each
    time). **Mitigation:** for such repos, run `--dry-run` first and/or pre-populate
    `awarded.json` with already-awarded contributors before the first live run. This caveat
    is documented prominently in the script's `--help` and README.
- **Multiple PRs by one author** in the window → awarded once; the ledger short-circuits
  after the first award that run.
- **Default badge only.** Matches the original's automatic path. Non-default badges remain a
  manual action; record them in `awarded.json` by hand (their own `badgeId`) so dedup stays
  accurate.
- **Holopin idempotency is unconfirmed.** The docs don't state whether re-awarding a held
  sticker is a no-op, so the design treats re-awards as unsafe (hence the ledger + the
  new-folder caveat). If `support@holopin.io` confirms re-awards are no-ops, the new-folder
  caveat becomes harmless.

## Testing

- The script wraps all `gh` calls in a thin `run_gh(args)` helper so the **core logic is
  unit-testable** with a faked `gh`:
  - default-sticker resolution from a sample `holopin.yml`,
  - `(username, badgeId)` dedup against a sample `awarded.json`,
  - bot author filtering,
  - since-cursor read/override/advance behavior.
- **Integration check:** `--dry-run` against a real repo confirms sticker resolution and the
  recipient/PR list without issuing anything.

## Out of scope

- No GitHub Actions workflows of any kind (this design replaces them).
- No PAT / `HOLOPIN_AWARD_TOKEN` org secret (local `gh` identity replaces it).
- No label-based trigger (comment is the proven path; can be added later if needed).
- No multi-issuer fallback (single operator runs locally; if @marcduiker is unavailable,
  another eligible member authenticates their own `gh` and runs the script).
