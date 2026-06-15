# Dapr Community Holopin Badges

A local cross-platform Python script, `award_holopin_badges.py`, that awards
Holopin badges to Dapr contributors. It discovers participating repos from local
folders, finds human contributors whose PRs merged since the last run, and awards
each the repo's **default** Holopin badge once by posting
`@holopin-bot @user <alias>` on one of their merged PRs via the `gh` CLI.

## Why local (not GitHub Actions)

Holopin only honors a trigger from someone who is a member of **both** the Dapr
GitHub org and the Dapr Holopin org. Running locally, `gh` is already authenticated
as that eligible member, so every comment is authored by an authorized issuer — no
PAT, no org secret, no `pull_request_target` machinery.

> The preflight verifies `gh auth status`, but it **cannot** verify Holopin org
> membership. Running as a non-eligible account silently produces no badges.

## Prerequisites

- `gh` CLI installed and authenticated as an eligible member (`gh auth status`
  succeeds), with scope to read PRs and write issue/PR comments on the `dapr/*` repos.
- [`uv`](https://docs.astral.sh/uv/) installed (it provisions Python 3.9+ and
  the PyYAML dependency for you — see [Running the script](#running-the-script)).
- The authenticated user is a member of the Dapr Holopin org with linked accounts.

## Running the script

[`uv`](https://docs.astral.sh/uv/) handles the virtual environment and the
PyYAML dependency for you. First install `uv` (one time):

- **Windows (PowerShell):** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

(Or use a package manager — `winget install astral-sh.uv` on Windows,
`brew install uv` on macOS.)

Then run the script from the repo root — the commands are identical on every
platform. `uv run` reads `pyproject.toml`, creates an isolated environment, and
installs the dependencies on first use:

```bash
# Preview what would be awarded (recommended first run)
uv run award_holopin_badges.py --dry-run

# Award for real
uv run award_holopin_badges.py
```

See [Usage](#usage) for the available flags.

## Folder layout — the folder is the opt-in

```
repos/
  dapr/dapr/
    awarded.json     # [ { "username": "...", "badgeId": "..." }, ... ]  dedup ledger
    state.json       # { "lastRun": "2026-06-12T10:00:00Z" }            since-cursor
  dapr/docs/
    awarded.json
    state.json
```

`awarded.json` and `state.json` are created automatically on first run. Dedup is
keyed on the `(username, badgeId)` pair, so a contributor can still earn a
*different* badge in the same repo later.

## Usage

```
award_holopin_badges.py [--dry-run] [--repo owner/repo ...] [--since ISO8601]
                        [--base-dir PATH] [--sleep SECONDS]
```

- `--dry-run` — print what would be awarded and touch nothing.
- `--repo owner/repo` — process only this repo (repeatable). Default: all folders.
- `--since ISO8601` — override the stored `lastRun` for this run only (not persisted).
- `--base-dir PATH` — where `repos/` lives (default: alongside the script).
- `--sleep SECONDS` — delay between awards (default 3).

## ⚠️ Caveat: new repo folders reach back to the beginning

A brand-new folder with no `state.json` queries **all** historical merged PRs and
will re-award contributors who were already awarded manually (Holopin mints a new
claim URL each time). For such repos:

1. Run with `--dry-run` first to review the recipient list, and/or
2. Pre-populate `awarded.json` with already-awarded contributors (with the correct
   `badgeId`) before the first live run.

## Non-default badges

Only the **default** badge is awarded automatically. Non-default badges are a manual
action — record them in `awarded.json` by hand (with their own `badgeId`) so dedup
stays accurate.

## Development

```bash
uv run pytest -v
```
