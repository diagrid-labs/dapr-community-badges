import json
import pathlib

import award_holopin_badges as ah

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_is_bot_detects_bracket_suffix():
    assert ah.is_bot("github-actions[bot]") is True
    assert ah.is_bot("renovate[bot]") is True


def test_is_bot_detects_named_bots_case_insensitive():
    assert ah.is_bot("dependabot") is True
    assert ah.is_bot("Dapr-Bot") is True
    assert ah.is_bot("github-actions") is True


def test_is_bot_detects_app_prefixed_logins():
    # gh reports GitHub App authors as "app/<name>"
    assert ah.is_bot("app/dependabot") is True
    assert ah.is_bot("app/github-actions") is True
    assert ah.is_bot("app/copilot-swe-agent") is True


def test_is_bot_allows_humans():
    assert ah.is_bot("alice") is False
    assert ah.is_bot("marcduiker") is False


def test_distinct_human_authors_filters_is_bot_field():
    # An author flagged is_bot by gh is excluded even if the login is unknown.
    prs = [
        {"number": 1, "author": {"login": "app/some-future-bot", "is_bot": True},
         "mergedAt": "2026-06-01T00:00:00Z"},
        {"number": 2, "author": {"login": "carol", "is_bot": False},
         "mergedAt": "2026-06-02T00:00:00Z"},
    ]
    assert ah.distinct_human_authors(prs) == [("carol", 2)]


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


# ---------------------------------------------------------------------------
# Task 7: run_gh runner + fetch_holopin_yml
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 8: query_merged_prs
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 9: award_badge
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 10: discover_repos
# ---------------------------------------------------------------------------

def test_discover_repos_finds_two_level_paths(tmp_path):
    (tmp_path / "repos" / "dapr" / "dapr").mkdir(parents=True)
    (tmp_path / "repos" / "dapr" / "docs").mkdir(parents=True)
    (tmp_path / "repos" / "other" / "thing").mkdir(parents=True)
    result = ah.discover_repos(str(tmp_path))
    assert result == [("dapr", "dapr"), ("dapr", "docs"), ("other", "thing")]


def test_discover_repos_empty_when_no_repos_dir(tmp_path):
    assert ah.discover_repos(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# Task 11: process_repo
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 12: preflight
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 13: parse_args, utc_now_iso
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 13: main end-to-end (monkeypatched)
# ---------------------------------------------------------------------------

def test_main_rejects_malformed_repo(monkeypatch, capsys):
    monkeypatch.setattr(ah, "preflight", lambda **kw: None)
    result = ah.main(["--repo", "dapr"])
    assert result == 1
    captured = capsys.readouterr()
    assert "owner/repo" in captured.err


def test_main_returns_1_when_repo_errors(monkeypatch, capsys):
    monkeypatch.setattr(ah, "preflight", lambda **kw: None)
    monkeypatch.setattr(ah, "process_repo", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    result = ah.main(["--repo", "dapr/dapr"])
    assert result == 1
    captured = capsys.readouterr()
    assert "boom" in captured.err


def test_main_returns_0_on_success(monkeypatch, capsys):
    monkeypatch.setattr(ah, "preflight", lambda **kw: None)
    monkeypatch.setattr(ah, "process_repo",
                        lambda *a, **kw: {"alias": "a", "badgeId": "b", "awarded": []})
    result = ah.main(["--repo", "dapr/dapr"])
    assert result == 0


def test_main_no_repos_message(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ah, "preflight", lambda **kw: None)
    result = ah.main(["--base-dir", str(tmp_path)])
    assert result == 0
    captured = capsys.readouterr()
    assert "No repos to process" in captured.err


def test_preflight_exits_when_gh_auth_fails_message():
    import pytest

    def fake_gh(args):
        raise ah.GhError("not logged in")

    with pytest.raises(SystemExit, match="gh auth login"):
        ah.preflight(run_gh=fake_gh)
