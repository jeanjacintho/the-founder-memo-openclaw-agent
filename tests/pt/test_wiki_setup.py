"""wiki_setup.py: the owner's wiki made ready for the memo."""
from __future__ import annotations

import pytest

from conftest import load_module
from wiki import GOALS, OVERVIEW, QA, RESOURCES, ROOT, SCHEMA, Wiki, join_page

ws = load_module("wiki_setup", "memo-shared/scripts/wiki_setup.py")


def wiki_dir(mac):
    return mac.home / "Plow" / "wiki"


def files(mac):
    return {p: p.read_bytes() for p in wiki_dir(mac).rglob("*") if p.is_file()}


class TestEnsure:
    def test_a_mac_without_a_wiki_gets_one_the_paper_can_write(self, mac):
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        toml = (wiki_dir(mac) / "wiki.toml").read_text()
        assert f'[roots."{ROOT}"]\nwriter = "founder-memo"' in toml
        assert (wiki_dir(mac) / SCHEMA).exists() and (wiki_dir(mac) / OVERVIEW).exists()
        assert mac.wiki("validate")["exit_code"] == 0

    def test_ready_means_nothing_is_rewritten(self, mac):
        w = Wiki(mac.call_tool)
        ws.ensure(w, "cht_1", desk=True)
        before = files(mac)
        assert ws.ensure(w, "cht_1", desk=True) == []
        assert files(mac) == before

    def test_another_agents_root_and_pages_are_left_as_they_were(self, mac):
        mac.wiki("init", "~/Plow/wiki")
        toml = wiki_dir(mac) / "wiki.toml"
        toml.write_text(toml.read_text() + '\n[roots."projects/str"]\nwriter = "str"\n')
        theirs = wiki_dir(mac) / "entities" / "people" / "raj.md"
        theirs.parent.mkdir(parents=True, exist_ok=True)
        theirs.write_text("---\ntitle: Raj\n---\n")
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        assert '[roots."projects/str"]\nwriter = "str"' in toml.read_text()
        assert theirs.read_text() == "---\ntitle: Raj\n---\n"

    def test_the_root_already_declared_in_another_spelling_is_left_alone(self, mac):
        mac.wiki("init", "~/Plow/wiki")
        toml = wiki_dir(mac) / "wiki.toml"
        toml.write_text(toml.read_text() + f"\n[roots.'{ROOT}']\nwriter = \"founder-memo\"\n")
        before = toml.read_bytes()
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        assert toml.read_bytes() == before
        assert mac.wiki("validate")["exit_code"] == 0

    def test_without_the_desk_no_owner_page_appears(self, mac):
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        assert not (wiki_dir(mac) / GOALS).exists()
        assert not (wiki_dir(mac) / QA).exists()

    def test_the_desk_gets_valid_empty_pages(self, mac):
        ws.ensure(Wiki(mac.call_tool), "cht_1", desk=True)
        assert "## Goals" in (wiki_dir(mac) / GOALS).read_text()
        qa = (wiki_dir(mac) / QA).read_text()
        assert "type: Synthesis" in qa and "## Open" in qa and "## Answered" in qa
        resources = (wiki_dir(mac) / RESOURCES).read_text()
        assert "## Read capabilities" in resources and "## Sources" in resources
        assert mac.wiki("validate")["exit_code"] == 0

    def test_desk_setup_never_overwrites_the_resource_catalog(self, mac):
        w = Wiki(mac.call_tool)
        ws.ensure(w, "cht_1", desk=True)
        path = wiki_dir(mac) / RESOURCES
        path.write_text(path.read_text() + "\n- owner edit\n")
        ws.ensure(w, "cht_1", desk=True)
        assert path.read_text().endswith("- owner edit\n")

    def test_an_old_install_carries_its_notes_over(self, mac):
        old_notes = mac.home / "Plow" / "prioritization.md"
        old_notes.parent.mkdir(parents=True)
        old_notes.write_text("# What I'm working toward\n\n## Goals\n- Reach $1M ARR\n")
        ws.ensure(Wiki(mac.call_tool), "cht_1", desk=True)
        assert "- Reach $1M ARR" in (wiki_dir(mac) / GOALS).read_text()
        assert old_notes.exists()  # the owner's file is theirs
        assert mac.wiki("validate")["exit_code"] == 0


class TestRoot:
    def test_the_memo_writes_under_its_own_name(self):
        assert ROOT == "projects/founder-memo"
        assert OVERVIEW == f"{ROOT}/founder-memo.md"

    def test_setup_creates_the_memo_root_and_validates(self, mac):
        ws.ensure(Wiki(mac.call_tool), "cht_1", desk=True)
        root = wiki_dir(mac) / ROOT
        assert (root / "founder-memo.md").exists() and (root / "qa.md").exists()
        assert mac.wiki("validate", "--writer", "founder-memo")["exit_code"] == 0


def times_install(mac):
    mac.wiki("init", "~/Plow/wiki")
    root = wiki_dir(mac)
    toml = root / "wiki.toml"
    toml.write_text(toml.read_text() + f'\n[roots."{ws.LEGACY_ROOT}"]\nwriter = "thefoundertimes"\n')
    for rel, asset in [(f"_meta/schemas/{ws.LEGACY_ROOT}.md", "schema.md"),
                      (ws.LEGACY_OVERVIEW, "overview.md"),
                      (f"{ws.LEGACY_ROOT}/qa.md", "qa.md"),
                      (f"{ws.LEGACY_ROOT}/resources.md", "resources.md")]:
        text = (ws.ASSETS / asset).read_text().replace("{today}", "2026-10-04").replace("{chat}", "cht_1")
        text = text.replace(OVERVIEW, ws.LEGACY_OVERVIEW).replace(ROOT, ws.LEGACY_ROOT)
        text = text.replace("The Founder Memo", "The Founder Times")
        if asset == "overview.md":
            text = text.replace("tags: [memo]", "tags: [newspaper]").replace("\n## Memos\n", "")
            text += "\n## My notes\nKeep the pilot outcomes visible.\n"
        if asset in ("qa.md", "resources.md"):
            text += "\n- owner-authored note\n"
            text += f"\n[Earlier advice](/{ws.LEGACY_OVERVIEW})\n"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    edition = root / ws.LEGACY_ROOT / "editions/2026-10-04.md"
    edition.parent.mkdir(parents=True, exist_ok=True)
    edition.write_text(join_page({
        "type": "Edition", "title": "Prior advice", "description": "Prior advice",
        "category": "projects", "tags": ["edition"], "date": "2026-10-04",
        "created": "2026-10-04", "updated": "2026-10-04",
        "sources": [{"resource": "plow-chat:cht_1"}],
        "paper": f"[The Founder Times](/{ws.LEGACY_OVERVIEW})",
        "priority": {"headline": "Close the pilot"},
    }, "# Prior advice\n"))
    notes = root / ws.LEGACY_ROOT / "Café notes.md"
    notes.write_text(edition.read_text().replace("type: Edition", "type: Synthesis"))
    assert mac.wiki("index")["exit_code"] == 0
    return {p: p.read_bytes() for p in (root / ws.LEGACY_ROOT).rglob("*") if p.is_file()}


class TestTimesUpgrade:
    @pytest.mark.parametrize("index_state", ["current", "missing", "stale"])
    def test_upgrade_preserves_owner_notes_links_and_readable_history(self, mac, index_state):
        from datetime import date
        history = load_module("history", "memo-tournament/scripts/history.py")
        before = times_install(mac)
        if index_state == "missing":
            (wiki_dir(mac) / "index.md").unlink()
        expected_history = [{"date": "2026-10-04", "desk": {"headline": "Close the pilot"}}]
        if index_state == "stale":
            edition = wiki_dir(mac) / ws.LEGACY_ROOT / "editions/2026-10-03.md"
            previous = edition.with_name("2026-10-04.md").read_text()
            edition.write_text(previous.replace("2026-10-04", "2026-10-03").replace("Close the pilot", "Review the outcome"))
            assert "2026-10-03" not in (wiki_dir(mac) / "index.md").read_text()
            expected_history.insert(0, {"date": "2026-10-03", "desk": {"headline": "Review the outcome"}})
            # Reindexing refreshes the old overview's generated table, keeping authored notes.
            before.pop(wiki_dir(mac) / ws.LEGACY_OVERVIEW)
            before[edition] = edition.read_bytes()
        w = Wiki(mac.call_tool)
        ws.ensure(w, "cht_1", desk=True)
        for rel in (QA, RESOURCES):
            text = (wiki_dir(mac) / rel).read_text()
            assert "owner-authored note" in text and f"/{OVERVIEW}" in text
            assert ws.LEGACY_ROOT not in text
            assert "[The Founder Times](" not in text
        overview = (wiki_dir(mac) / OVERVIEW).read_text()
        assert "title: The Founder Memo" in overview and "# The Founder Memo\n" in overview
        assert "tags:\n- memo" in overview and "## Memos\n" in overview
        assert "## My notes\nKeep the pilot outcomes visible." in overview
        assert (wiki_dir(mac) / ROOT / "Café notes.md").exists()
        assert history.recent(w, date(2026, 10, 5)) == expected_history
        assert {p: p.read_bytes() for p in before} == before
        legacy_overview = (wiki_dir(mac) / ws.LEGACY_OVERVIEW).read_text()
        assert "# The Founder Times\n" in legacy_overview
        assert "## My notes\nKeep the pilot outcomes visible." in legacy_overview
        assert f'[roots."{ws.LEGACY_ROOT}"]' in (wiki_dir(mac) / "wiki.toml").read_text()
        assert mac.wiki("validate", "--writer", "founder-memo")["exit_code"] == 0
        ready = files(mac)
        assert ws.ensure(w, "cht_1", desk=True) == []
        assert files(mac) == ready

    def test_retry_keeps_copied_owner_edits_and_finishes_remaining_pages(self, mac, monkeypatch):
        times_install(mac)
        w = Wiki(mac.call_tool)
        write = w.write

        def fail_resources(rel, text):
            if rel == RESOURCES:
                raise ws.LatchError("copy interrupted")
            write(rel, text)

        monkeypatch.setattr(w, "write", fail_resources)
        with pytest.raises(ws.LatchError, match="copy interrupted"):
            ws.ensure(w, "cht_1", desk=True)
        assert ROOT not in (wiki_dir(mac) / "wiki.toml").read_text()
        copied = wiki_dir(mac) / QA
        copied.write_text(copied.read_text() + "\n- edited after interruption\n")
        monkeypatch.setattr(w, "write", write)
        ws.ensure(w, "cht_1", desk=True)
        assert copied.read_text().endswith("- edited after interruption\n")
        assert "owner-authored note" in (wiki_dir(mac) / RESOURCES).read_text()

    def test_index_failure_does_not_declare_a_blank_new_root(self, mac, monkeypatch):
        times_install(mac)
        w = Wiki(mac.call_tool)
        monkeypatch.setattr(w, "run", lambda *args, **kwargs: (1, "index failed"))
        with pytest.raises(ws.LatchError, match="wiki index: index failed"):
            ws.ensure(w, "cht_1", desk=True)
        assert not (wiki_dir(mac) / ROOT).exists()
        assert ROOT not in (wiki_dir(mac) / "wiki.toml").read_text()


class TestCli:
    def test_an_unreachable_mac_is_an_error_not_ready(self, mac, monkeypatch):
        mac.asleep = True
        monkeypatch.setattr(ws, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_1")
        with pytest.raises(SystemExit) as exc:
            ws.main(["--desk"])
        assert str(exc.value).startswith("error: wiki not ready — Mac unreachable")
