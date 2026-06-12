# Holopin Local Award Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `award_holopin_badges.py`, a cross-platform Python script that awards Holopin badges to Dapr contributors by posting `@holopin-bot @user <alias>` comments on their merged PRs via the local `gh` CLI, with local per-repo dedup and since-cursor files.

**Architecture:** A single importable module with small, pure helper functions (sticker resolution, bot filtering, dedup, cursor I/O, author selection) plus thin `gh`-calling functions that accept an injectable `run_gh` runner. A `process_repo` orchestrator ties them together per repo; `main` discovers repos, captures one run-start timestamp, and isolates each repo in a `try/except`. All `gh` access funnels through one `run_gh(args)` helper so the core logic is unit-testable with a fake runner.

**Tech Stack:** Python 3.9+, PyYAML, the `gh` CLI (subprocess), pytest for tests.

---

## File Structure

- `award_holopin_badges.py` — the entire script/module (root of repo). One responsibility: discover repos, resolve stickers, find new contributors, award badges. All functions live here so it stays a single distributable file (per the spec), but each function is small and independently testable.
- `tests/test_award_holopin_badges.py` — unit tests using a fake `gh` runner and `tmp_path` for filesystem state.
- `tests/fixtures/holopin.yml` — sample Holopin config for sticker-resolution tests.
- `pyproject.toml` — pytest config (`pythonpath = ["."]`) so tests can import the root module.
- `requirements.txt` — runtime deps (PyYAML).
- `requirements-dev.txt` — dev deps (pytest).
- `README.md` — usage, prerequisites, and the prominent new-folder backfill caveat.

A note on `gh` author shape: `gh pr list --json author` returns each author as `{"login": "...", "is_bot": bool, ...}`, and `author` can be `null` for deleted ("ghost") accounts. Helpers must tolerate `null`.

A note on `holopin.yml` shape:

```yaml
organization: dapr
defaultSticker: clrqh1xny39170fl75cawk0h5
stickers:
  - id: clrqh1xny39170fl75cawk0h5
    alias: dapr-contributor
    name: Dapr Contributor
```

`defaultSticker` is a sticker **id**; resolution finds the matching sticker and returns `(alias, id)`. The trigger comment uses the `alias`; the dedup ledger keys on the `id` (the `badgeId`).

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `award_holopin_badges.py`
- Create: `tests/test_award_holopin_badges.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
PyYAML>=6.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=7.0
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 4: Create the module skeleton `award_holopin_badges.py`**

```python
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

# Bot logins to exclude beyond the generic `[bot]` suffix.
BOT_LOGINS = {"dependabot", "github-actions", "dapr-bot"}

# Date used to reach back to the beginning when no since-cursor exists.
BACKFILL_SINCE = "2015-01-01"


class GhError(RuntimeError):
    """Raised when a `gh` invocation fails."""
```

- [ ] **Step 5: Create empty `tests/__init__.py`**

```python
```

- [ ] **Step 6: Create the test file header `tests/test_award_holopin_badges.py`**

```python
import json

import award_holopin_badges as ah
```

- [ ] **Step 7: Verify the module imports**

Run: `python -c "import award_holopin_badges"`
Expected: no output, exit code 0.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml requirements.txt requirements-dev.txt award_holopin_badges.py tests/__init__.py tests/test_award_holopin_badges.py
git commit -m "chore: scaffold holopin award script project"
```

---

## Task 2: Bot author filtering (`is_bot`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_is_bot_detects_bracket_suffix():
    assert ah.is_bot("github-actions[bot]") is True
    assert ah.is_bot("renovate[bot]") is True


def test_is_bot_detects_named_bots_case_insensitive():
    assert ah.is_bot("dependabot") is True
    assert ah.is_bot("Dapr-Bot") is True
    assert ah.is_bot("github-actions") is True


def test_is_bot_allows_humans():
    assert ah.is_bot("alice") is False
    assert ah.is_bot("marcduiker") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k is_bot -v`
Expected: FAIL with `AttributeError: module 'award_holopin_badges' has no attribute 'is_bot'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
def is_bot(login: str) -> bool:
    """True if the login is a bot we should never award."""
    if not login:
        return True
    if login.endswith("[bot]"):
        return True
    return login.lower() in BOT_LOGINS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k is_bot -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: add bot author filtering"
```

---

## Task 3: Default-sticker resolution (`resolve_default_sticker`)

**Files:**
- Modify: `award_holopin_badges.py`
- Create: `tests/fixtures/holopin.yml`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Create the fixture `tests/fixtures/holopin.yml`**

```yaml
organization: dapr
defaultSticker: clrqh1xny39170fl75cawk0h5
stickers:
  - id: clrqh1xny39170fl75cawk0h5
    alias: dapr-contributor
    name: Dapr Contributor
  - id: zzzother0000000000000000z
    alias: dapr-maintainer
    name: Dapr Maintainer
```

- [ ] **Step 2: Write the failing test**

```python
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_resolve_default_sticker_returns_alias_and_id():
    text = (FIXTURES / "holopin.yml").read_text()
    alias, badge_id = ah.resolve_default_sticker(text)
    assert alias == "dapr-contributor"
    assert badge_id == "clrqh1xny39170fl75cawk0h5"


def test_resolve_default_sticker_missing_default_raises():
    import pytest
    with pytest.raises(ValueError):
        ah.resolve_default_sticker("organization: dapr\nstickers: []\n")


def test_resolve_default_sticker_unknown_id_raises():
    import pytest
    text = "defaultSticker: nope\nstickers:\n  - id: other\n    alias: x\n"
    with pytest.raises(ValueError):
        ah.resolve_default_sticker(text)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k resolve_default -v`
Expected: FAIL with `AttributeError: ... has no attribute 'resolve_default_sticker'`.

- [ ] **Step 4: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k resolve_default -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py tests/fixtures/holopin.yml
git commit -m "feat: resolve default Holopin sticker from holopin.yml"
```

---

## Task 4: Since-cursor read / override / advance (`read_since`, `write_last_run`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_read_since_returns_none_when_no_state(tmp_path):
    assert ah.read_since(str(tmp_path)) is None


def test_read_since_reads_last_run(tmp_path):
    (tmp_path / "state.json").write_text('{"lastRun": "2026-06-01T00:00:00Z"}')
    assert ah.read_since(str(tmp_path)) == "2026-06-01T00:00:00Z"


def test_read_since_override_wins(tmp_path):
    (tmp_path / "state.json").write_text('{"lastRun": "2026-06-01T00:00:00Z"}')
    assert ah.read_since(str(tmp_path), override="2020-01-01") == "2020-01-01"


def test_write_last_run_persists(tmp_path):
    ah.write_last_run(str(tmp_path), "2026-06-12T10:00:00Z")
    data = json.loads((tmp_path / "state.json").read_text())
    assert data == {"lastRun": "2026-06-12T10:00:00Z"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k "since or last_run" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'read_since'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k "since or last_run" -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: add since-cursor read/override/advance"
```

---

## Task 5: Dedup ledger (`read_awarded`, `already_awarded`, `append_awarded`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_read_awarded_empty_when_missing(tmp_path):
    assert ah.read_awarded(str(tmp_path)) == []


def test_already_awarded_keys_on_username_and_badge():
    ledger = [{"username": "alice", "badgeId": "b1"}]
    assert ah.already_awarded(ledger, "alice", "b1") is True
    # same user, different badge -> not yet awarded
    assert ah.already_awarded(ledger, "alice", "b2") is False
    # different user -> not yet awarded
    assert ah.already_awarded(ledger, "bob", "b1") is False


def test_append_awarded_persists_and_mutates(tmp_path):
    ledger = []
    ah.append_awarded(str(tmp_path), ledger, "alice", "b1")
    assert ledger == [{"username": "alice", "badgeId": "b1"}]
    on_disk = json.loads((tmp_path / "awarded.json").read_text())
    assert on_disk == [{"username": "alice", "badgeId": "b1"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k awarded -v`
Expected: FAIL with `AttributeError: ... has no attribute 'read_awarded'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k awarded -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: add (username, badgeId) dedup ledger"
```

---

## Task 6: Distinct human authors (`distinct_human_authors`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_distinct_human_authors_one_per_author_most_recent():
    prs = [
        {"number": 1, "author": {"login": "alice"}, "mergedAt": "2026-06-01T00:00:00Z"},
        {"number": 5, "author": {"login": "alice"}, "mergedAt": "2026-06-10T00:00:00Z"},
        {"number": 3, "author": {"login": "bob"}, "mergedAt": "2026-06-05T00:00:00Z"},
    ]
    result = ah.distinct_human_authors(prs)
    # most-recent PR kept per author, ordered most-recent-first
    assert result == [("alice", 5), ("bob", 3)]


def test_distinct_human_authors_filters_bots_and_ghosts():
    prs = [
        {"number": 1, "author": {"login": "dependabot[bot]"}, "mergedAt": "2026-06-01T00:00:00Z"},
        {"number": 2, "author": {"login": "dapr-bot"}, "mergedAt": "2026-06-02T00:00:00Z"},
        {"number": 3, "author": None, "mergedAt": "2026-06-03T00:00:00Z"},
        {"number": 4, "author": {"login": "carol"}, "mergedAt": "2026-06-04T00:00:00Z"},
    ]
    assert ah.distinct_human_authors(prs) == [("carol", 4)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k distinct_human -v`
Expected: FAIL with `AttributeError: ... has no attribute 'distinct_human_authors'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
        if not login or is_bot(login):
            continue
        if login in seen:
            continue
        seen.add(login)
        result.append((login, pr["number"]))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k distinct_human -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: select distinct human PR authors since cursor"
```

---

## Task 7: The `gh` runner and `fetch_holopin_yml`

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fetch_holopin_yml_decodes_base64_content():
    import base64 as b64

    raw = "organization: dapr\ndefaultSticker: x\n"
    payload = {"content": b64.b64encode(raw.encode()).decode()}
    calls = []

    def fake_gh(args):
        calls.append(args)
        return json.dumps(payload)

    text = ah.fetch_holopin_yml("dapr", "dapr", run_gh=fake_gh)
    assert text == raw
    assert calls == [["api", "repos/dapr/dapr/contents/.github/holopin.yml"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k fetch_holopin -v`
Expected: FAIL with `AttributeError: ... has no attribute 'fetch_holopin_yml'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
def run_gh(args: list) -> str:
    """Run `gh` with the given args and return stdout. Raises GhError on failure."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k fetch_holopin -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: add gh runner and remote holopin.yml fetch"
```

---

## Task 8: Query merged PRs (`query_merged_prs`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_query_merged_prs_builds_search_and_parses_json():
    captured = {}

    def fake_gh(args):
        captured["args"] = args
        return json.dumps([{"number": 1, "author": {"login": "a"}, "mergedAt": "2026-06-01T00:00:00Z"}])

    prs = ah.query_merged_prs("dapr", "dapr", "2026-06-01T00:00:00Z", 50, run_gh=fake_gh)
    assert prs[0]["number"] == 1
    assert captured["args"] == [
        "pr", "list", "--repo", "dapr/dapr", "--state", "merged",
        "--search", "merged:>=2026-06-01T00:00:00Z",
        "--json", "number,author,mergedAt", "--limit", "50",
    ]


def test_query_merged_prs_backfills_when_no_since():
    captured = {}

    def fake_gh(args):
        captured["args"] = args
        return "[]"

    ah.query_merged_prs("dapr", "dapr", None, 50, run_gh=fake_gh)
    assert "--search" in captured["args"]
    idx = captured["args"].index("--search")
    assert captured["args"][idx + 1] == f"merged:>={ah.BACKFILL_SINCE}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k query_merged -v`
Expected: FAIL with `AttributeError: ... has no attribute 'query_merged_prs'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k query_merged -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: query merged PRs since cursor via gh"
```

---

## Task 9: Award a badge (`award_badge`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_award_badge_posts_trigger_comment():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return ""

    body = ah.award_badge("dapr", "dapr", 42, "alice", "dapr-contributor",
                          dry_run=False, run_gh=fake_gh)
    assert body == "@holopin-bot @alice dapr-contributor"
    assert calls == [[
        "pr", "comment", "42", "--repo", "dapr/dapr",
        "--body", "@holopin-bot @alice dapr-contributor",
    ]]


def test_award_badge_dry_run_posts_nothing():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return ""

    body = ah.award_badge("dapr", "dapr", 42, "alice", "dapr-contributor",
                          dry_run=True, run_gh=fake_gh)
    assert body == "@holopin-bot @alice dapr-contributor"
    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k award_badge -v`
Expected: FAIL with `AttributeError: ... has no attribute 'award_badge'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
def award_badge(owner: str, repo: str, pr_number: int, username: str, alias: str,
                dry_run: bool, run_gh=run_gh) -> str:
    """Post the Holopin trigger comment on the PR. Returns the comment body.
    In dry-run, builds the body but posts nothing."""
    body = f"@holopin-bot @{username} {alias}"
    if not dry_run:
        run_gh([
            "pr", "comment", str(pr_number),
            "--repo", f"{owner}/{repo}",
            "--body", body,
        ])
    return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k award_badge -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: post Holopin trigger comment to award a badge"
```

---

## Task 10: Repo discovery (`discover_repos`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_discover_repos_finds_two_level_paths(tmp_path):
    (tmp_path / "repos" / "dapr" / "dapr").mkdir(parents=True)
    (tmp_path / "repos" / "dapr" / "docs").mkdir(parents=True)
    (tmp_path / "repos" / "other" / "thing").mkdir(parents=True)
    result = ah.discover_repos(str(tmp_path))
    assert result == [("dapr", "dapr"), ("dapr", "docs"), ("other", "thing")]


def test_discover_repos_empty_when_no_repos_dir(tmp_path):
    assert ah.discover_repos(str(tmp_path)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k discover_repos -v`
Expected: FAIL with `AttributeError: ... has no attribute 'discover_repos'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k discover_repos -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: discover participating repos from folder layout"
```

---

## Task 11: Per-repo orchestration (`process_repo`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
import base64 as _b64


def _make_fake_gh(holopin_text, prs):
    """Fake gh that answers the three calls process_repo makes."""
    posted = []

    def fake_gh(args):
        if args[0] == "api":
            return json.dumps({"content": _b64.b64encode(holopin_text.encode()).decode()})
        if args[:2] == ["pr", "list"]:
            return json.dumps(prs)
        if args[:2] == ["pr", "comment"]:
            posted.append(args)
            return ""
        raise AssertionError(f"unexpected gh call: {args}")

    return fake_gh, posted


HOLOPIN = (
    "organization: dapr\n"
    "defaultSticker: b1\n"
    "stickers:\n"
    "  - id: b1\n"
    "    alias: dapr-contributor\n"
)


def test_process_repo_awards_new_human_authors(tmp_path):
    prs = [
        {"number": 7, "author": {"login": "alice"}, "mergedAt": "2026-06-10T00:00:00Z"},
        {"number": 2, "author": {"login": "dapr-bot"}, "mergedAt": "2026-06-09T00:00:00Z"},
    ]
    fake_gh, posted = _make_fake_gh(HOLOPIN, prs)
    summary = ah.process_repo(
        "dapr", "dapr", str(tmp_path),
        dry_run=False, run_gh=fake_gh, sleep_fn=lambda s: None,
        run_start="2026-06-12T10:00:00Z",
    )
    assert summary["alias"] == "dapr-contributor"
    assert summary["badgeId"] == "b1"
    assert summary["awarded"] == [("alice", 7)]
    # comment posted for alice only
    assert posted == [[
        "pr", "comment", "7", "--repo", "dapr/dapr",
        "--body", "@holopin-bot @alice dapr-contributor",
    ]]
    # ledger and cursor persisted
    repo_dir = tmp_path / "repos" / "dapr" / "dapr"
    assert json.loads((repo_dir / "awarded.json").read_text()) == [
        {"username": "alice", "badgeId": "b1"}
    ]
    assert json.loads((repo_dir / "state.json").read_text()) == {
        "lastRun": "2026-06-12T10:00:00Z"
    }


def test_process_repo_skips_already_awarded(tmp_path):
    repo_dir = tmp_path / "repos" / "dapr" / "dapr"
    repo_dir.mkdir(parents=True)
    (repo_dir / "awarded.json").write_text('[{"username": "alice", "badgeId": "b1"}]')
    prs = [{"number": 7, "author": {"login": "alice"}, "mergedAt": "2026-06-10T00:00:00Z"}]
    fake_gh, posted = _make_fake_gh(HOLOPIN, prs)
    summary = ah.process_repo(
        "dapr", "dapr", str(tmp_path),
        dry_run=False, run_gh=fake_gh, sleep_fn=lambda s: None,
        run_start="2026-06-12T10:00:00Z",
    )
    assert summary["awarded"] == []
    assert posted == []


def test_process_repo_dry_run_writes_nothing(tmp_path):
    prs = [{"number": 7, "author": {"login": "alice"}, "mergedAt": "2026-06-10T00:00:00Z"}]
    fake_gh, posted = _make_fake_gh(HOLOPIN, prs)
    summary = ah.process_repo(
        "dapr", "dapr", str(tmp_path),
        dry_run=True, run_gh=fake_gh, sleep_fn=lambda s: None,
        run_start="2026-06-12T10:00:00Z",
    )
    assert summary["awarded"] == [("alice", 7)]
    assert posted == []
    repo_dir = tmp_path / "repos" / "dapr" / "dapr"
    assert not (repo_dir / "awarded.json").exists()
    assert not (repo_dir / "state.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k process_repo -v`
Expected: FAIL with `AttributeError: ... has no attribute 'process_repo'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k process_repo -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: orchestrate per-repo award flow"
```

---

## Task 12: Preflight checks (`preflight`)

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_preflight_passes_when_gh_auth_ok():
    def fake_gh(args):
        assert args == ["auth", "status"]
        return "Logged in to github.com as marcduiker"

    ah.preflight(run_gh=fake_gh)  # should not raise


def test_preflight_exits_when_gh_auth_fails():
    import pytest

    def fake_gh(args):
        raise ah.GhError("not logged in")

    with pytest.raises(SystemExit):
        ah.preflight(run_gh=fake_gh)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k preflight -v`
Expected: FAIL with `AttributeError: ... has no attribute 'preflight'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k preflight -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: add gh auth preflight check"
```

---

## Task 13: CLI parsing and `main` wiring

**Files:**
- Modify: `award_holopin_badges.py`
- Test: `tests/test_award_holopin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_args_defaults():
    args = ah.parse_args([])
    assert args.dry_run is False
    assert args.repo == []
    assert args.since is None
    assert args.base_dir is None
    assert args.sleep == 3.0


def test_parse_args_flags():
    args = ah.parse_args([
        "--dry-run", "--repo", "dapr/dapr", "--repo", "dapr/docs",
        "--since", "2020-01-01", "--base-dir", "/tmp/holo", "--sleep", "1.5",
    ])
    assert args.dry_run is True
    assert args.repo == ["dapr/dapr", "dapr/docs"]
    assert args.since == "2020-01-01"
    assert args.base_dir == "/tmp/holo"
    assert args.sleep == 1.5


def test_utc_now_iso_format():
    stamp = ah.utc_now_iso()
    # YYYY-MM-DDTHH:MM:SSZ
    assert stamp.endswith("Z")
    assert len(stamp) == 20
    assert stamp[4] == "-" and stamp[10] == "T"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_award_holopin_badges.py -k "parse_args or utc_now" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'parse_args'`.

- [ ] **Step 3: Write minimal implementation (append to `award_holopin_badges.py`)**

```python
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
                        help="Delay between awards (default 3).")
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
        repos = [tuple(r.split("/", 1)) for r in args.repo]
    else:
        repos = discover_repos(base_dir)

    if not repos:
        print("No repos to process. Create folders under repos/<owner>/<repo> "
              "or pass --repo owner/repo.", file=sys.stderr)
        return 0

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
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_award_holopin_badges.py -k "parse_args or utc_now" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Verify `--help` renders and shows the caveat**

Run: `python award_holopin_badges.py --help`
Expected: usage text printed including the "new repo folders reach back to the beginning" caveat.

- [ ] **Step 7: Commit**

```bash
git add award_holopin_badges.py tests/test_award_holopin_badges.py
git commit -m "feat: wire up CLI and main entry point"
```

---

## Task 14: README and documentation

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

````markdown
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
- Python 3.9+ with PyYAML: `pip install -r requirements.txt`.
- The authenticated user is a member of the Dapr Holopin org with linked accounts.

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
pip install -r requirements-dev.txt
pytest -v
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with usage and backfill caveat"
```

---

## Self-Review Notes (verified against the spec)

- **Local `gh` identity / no PAT** — Tasks 7, 12; README "Why local". ✔
- **Folder layout = opt-in, two-level path** — Task 10 `discover_repos`. ✔
- **`awarded.json` format + `(username, badgeId)` dedup** — Task 5. ✔
- **`state.json` `lastRun`, absent → backfill** — Tasks 4, 8 (`BACKFILL_SINCE`). ✔
- **Default sticker resolution from remote `holopin.yml`** — Tasks 3, 7. ✔
- **Skip repo on missing/unresolvable holopin.yml** — Task 11 raises; Task 13 `main` isolates per-repo. ✔
- **Merged-PR query + distinct human authors + bot filter** — Tasks 2, 6, 8. ✔
- **Award-then-record ordering** — Task 11 (`append_awarded` after `award_badge`). ✔
- **Cursor advances only on success** — Task 11 (`write_last_run` at end, skipped in dry-run); Task 13 (`run_start` captured once). ✔
- **Sleep between awards** — Task 11 (`sleep_fn`, default 3s via `--sleep`). ✔
- **CLI flags** (`--dry-run`, `--repo`, `--since`, `--base-dir`, `--sleep`) — Task 13. ✔
- **Per-repo isolation try/except** — Task 13 `main`. ✔
- **Preflight (gh auth + PyYAML)** — Task 12; PyYAML at import (Task 1). ✔
- **Thin `run_gh` + injectable fakes for unit tests** — Tasks 7–9, 11 use `run_gh=` injection. ✔
- **Required test coverage** (sticker resolution, dedup, bot filtering, since-cursor) — Tasks 3, 5, 2, 4. ✔
- **Dry-run integration check** — Task 13 Step 6 (`--help`); a real `--dry-run` against a live repo is a manual post-merge check noted in the README. ✔
- **New-folder caveat in `--help` and README** — Task 13 (`HELP_EPILOG`), Task 14. ✔
