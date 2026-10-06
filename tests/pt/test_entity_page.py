"""entity_page.py -- one investigator's dossier merged into its shared wiki page."""
from __future__ import annotations

import json
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from conftest import load_module

ep = load_module("entity_page", "memo-shared/scripts/entity_page.py")
wiki = load_module("wiki", "memo-shared/scripts/wiki.py")

D = {"description": "Partner at Acme Ventures; owes a term sheet.",
     "now": "Waiting on Acme's term sheet; ball: them.",
     "timeline": [{"date": "2026-09-30", "fact": "Said the sheet comes Friday", "item": "gmail:me:t1"}],
     "sources": [{"resource": "gmail:me:t1"}], "tags": ["investor"]}


@pytest.fixture(autouse=True)
def local_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "state"))


def test_new_page_is_valid_okf_with_now_and_timeline():
    meta, body = wiki.split_page(ep.merge(None, D, "people", "Jane Doe", "2026-10-01"))
    assert meta["type"] == "Person" and meta["category"] == "entities"
    assert meta["created"] == meta["updated"] == "2026-10-01"
    assert "## Now\nWaiting on Acme's term sheet; ball: them.\n" in body
    assert "- 2026-09-30 · Said the sheet comes Friday · {gmail:me:t1}" in body


def test_refresh_replaces_now_dedupes_timeline_and_keeps_owner_sections():
    first = ep.merge(None, D, "orgs", "Acme", "2026-10-01")
    owned = first + "\n## My notes\nNever take their first offer.\n"
    owned = owned.replace("## Timeline\n", "## Timeline\nmet at the dinner, liked them\n")
    later = {**D, "now": "Sheet received.", "timeline": [
        {"date": "2026-09-30", "fact": "Said the sheet comes Friday (confirmed)", "item": "gmail:me:t1"},
        {"date": "2026-10-03", "fact": "Sent the sheet", "item": "gmail:me:t2"}],
        "sources": [{"resource": "gmail:me:t2"}]}
    meta, body = wiki.split_page(ep.merge(owned, later, "orgs", "Acme", "2026-10-04"))
    assert meta["type"] == "Organization" and meta["created"] == "2026-10-01"
    assert meta["updated"] == "2026-10-04"
    assert [s["resource"] for s in meta["sources"]] == ["gmail:me:t1", "gmail:me:t2"]
    assert "## Now\nSheet received.\n" in body and "ball: them" not in body
    assert body.count("{gmail:me:t1}") == 1 and "(confirmed)" in body
    assert body.index("{gmail:me:t2}") < body.index("{gmail:me:t1}")  # newest first
    assert "met at the dinner, liked them" in body and "## My notes\nNever take" in body


def test_timeline_caps_at_twenty_newest():
    many = {**D, "timeline": [{"date": f"2026-09-{d:02d}", "fact": f"f{d}", "item": f"i{d}"} for d in range(1, 26)]}
    body = ep.merge(None, many, "people", "Jane Doe", "2026-10-01")
    assert body.count(" · {i") == 20 and "{i25}" in body and "{i5}" not in body


@pytest.mark.parametrize("bad", [
    {**D, "timeline": [{"date": "Friday", "fact": "x", "item": "y"}]},
    {**D, "timeline": [{"date": "2026-09-30", "fact": "x", "item": ""}]},
    {k: v for k, v in D.items() if k != "now"},
])
def test_malformed_dossier_fails_loudly(bad):
    with pytest.raises(ValueError):
        ep.merge(None, bad, "people", "Jane Doe", "2026-10-01")


def test_cli_writes_then_validates_on_the_mac(mac, tmp_path):
    mac.wiki("init", "~/Plow/wiki")  # plow-wiki seeds wiki.toml with the shared entity roots
    f = tmp_path / "d.json"
    f.write_text(json.dumps(D))
    code = ep.main(["merge", "--kind", "people", "--slug", "jane-doe", "--title", "Jane Doe",
                    "--dossier", str(f), "--today", "2026-10-01"], call_tool=mac.call_tool)
    assert code == 0
    assert (mac.home / "Plow/wiki/entities/people/jane-doe.md").exists()


def test_a_page_the_wiki_refuses_fails_the_run(mac, tmp_path, capsys):
    mac.wiki("init", "~/Plow/wiki")
    page = mac.home / "Plow/wiki/entities/people/jane-doe.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(ep.merge(None, D, "people", "Jane Doe", "2026-10-01").replace(
        "category: entities", "category: entities\norg: not a link"))
    original = page.read_text()
    f = tmp_path / "d.json"
    f.write_text(json.dumps(D))
    code = ep.main(["merge", "--kind", "people", "--slug", "jane-doe", "--title", "Jane Doe",
                    "--dossier", str(f), "--today", "2026-10-02"], call_tool=mac.call_tool)
    assert code == 1
    assert "entities/people/jane-doe.md" in capsys.readouterr().err
    assert page.read_text() == original


@pytest.mark.parametrize("slug", ["../../owner/goals", "../jane", "a/b", "a\\b", ".", "..", "/jane", "jane\n"])
def test_invalid_slug_never_calls_latch(slug, tmp_path):
    def forbidden(*args):
        pytest.fail("invalid slug reached Latch")
    assert ep.main(["merge", "--kind", "people", "--slug", slug, "--title", "Jane",
                    "--dossier", str(tmp_path / "missing")], call_tool=forbidden) == 1


def test_rejected_new_page_is_removed(mac, tmp_path, capsys):
    mac.wiki("init", "~/Plow/wiki")
    f = tmp_path / "d.json"
    f.write_text(json.dumps({**D, "sources": [{"resource": ""}]}))
    assert ep.main(["merge", "--kind", "people", "--slug", "jane-doe", "--title", "Jane",
                    "--dossier", str(f), "--today", "2026-10-01"], call_tool=mac.call_tool) == 1
    assert "wiki validate" in capsys.readouterr().err
    assert not (mac.home / "Plow/wiki/entities/people/jane-doe.md").exists()


def test_bare_cli_uses_owner_day(mac, tmp_path, monkeypatch):
    mac.wiki("init", "~/Plow/wiki")
    monkeypatch.setattr(ep, "owner_today", lambda: date(2026, 10, 2))
    f = tmp_path / "d.json"
    f.write_text(json.dumps(D))
    assert ep.main(["merge", "--kind", "people", "--slug", "jane-doe", "--title", "Jane",
                    "--dossier", str(f)], call_tool=mac.call_tool) == 0
    meta, _ = wiki.split_page((mac.home / "Plow/wiki/entities/people/jane-doe.md").read_text())
    assert meta["created"] == meta["updated"] == "2026-10-02"


@pytest.mark.parametrize("reject_second", [False, True])
def test_overlapping_updates_preserve_successful_page(mac, tmp_path, reject_second):
    mac.wiki("init", "~/Plow/wiki")
    first_read, release, second_read = Event(), Event(), Event()
    first = tmp_path / "first.json"
    first.write_text(json.dumps(D))
    second = tmp_path / "second.json"
    second.write_text(json.dumps({**D, "timeline": [{"date": "2026-10-02", "fact": "New fact", "item": "gmail:me:t2"}],
                                  "sources": [{"resource": "" if reject_second else "gmail:me:t2"}]}))

    def call(which):
        def tool(name, args):
            result = mac.call_tool(name, args)
            if name == "plow_read_file":
                # Missing pages raise before this point, so seed the page below.
                if which == 1:
                    first_read.set()
                    assert release.wait(5)
                else:
                    second_read.set()
            return result
        return tool

    page = mac.home / "Plow/wiki/entities/people/jane-doe.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(ep.merge(None, {**D, "timeline": []}, "people", "Jane", "2026-10-01"))
    argv = ["merge", "--kind", "people", "--slug", "jane-doe", "--title", "Jane", "--today", "2026-10-02", "--dossier"]
    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(ep.main, [*argv, str(first)], call(1))
        try:
            assert first_read.wait(5)
            two = pool.submit(ep.main, [*argv, str(second)], call(2))
            assert not second_read.wait(0.2)
        finally:
            release.set()
        assert one.result(timeout=5) == 0
        assert two.result(timeout=5) == int(reject_second)
    text = page.read_text()
    assert "{gmail:me:t1}" in text
    assert ("{gmail:me:t2}" in text) is not reject_second
