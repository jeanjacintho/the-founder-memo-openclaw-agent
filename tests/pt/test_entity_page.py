"""entity_page.py -- one investigator's dossier merged into its shared wiki page."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

ep = load_module("entity_page", "memo-shared/scripts/entity_page.py")
wiki = load_module("wiki", "memo-shared/scripts/wiki.py")

D = {"description": "Partner at Acme Ventures; owes a term sheet.",
     "now": "Waiting on Acme's term sheet; ball: them.",
     "timeline": [{"date": "2026-09-30", "fact": "Said the sheet comes Friday", "item": "gmail:me:t1"}],
     "sources": [{"resource": "gmail:me:t1"}], "tags": ["investor"]}


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
    f = tmp_path / "d.json"
    f.write_text(json.dumps(D))
    code = ep.main(["merge", "--kind", "people", "--slug", "jane-doe", "--title", "Jane Doe",
                    "--dossier", str(f), "--today", "2026-10-02"], call_tool=mac.call_tool)
    assert code == 1
    assert "entities/people/jane-doe.md" in capsys.readouterr().err
