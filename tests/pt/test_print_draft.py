import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "memo-print" / "scripts"))
import print_draft as draft


def test_incomplete_old_content_is_escaped_and_explicitly_unverified():
    edition = {"date": "2020-01-01", "priority": {"recommendations": []},
               "failed_read": "<script>failed mail read</script>", "run": {"usd": None}}
    page = draft.draft_html(edition, "en")
    assert 'content: "DRAFT"' in page
    assert "no checkpoint or freshness verification" in page
    assert "exactly 3 items" in page
    assert "2020-01-01" in page
    assert "&lt;script&gt;failed mail read&lt;/script&gt;" in page
    assert '<script>' not in page
    assert '&quot;usd&quot;: null' in page
    assert "Não verificado" in draft.draft_html(edition, "pt", "72mm")
    assert 'size: 72mm' in draft.draft_html(edition, "pt", "72mm")


def test_prints_separate_draft_without_touching_source_or_last_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    source = tmp_path / "edition.json"
    source.write_text('{"failed_read": "calendar unavailable"}')
    original = source.read_bytes()
    final = tmp_path / "last-edition" / "edition.pdf"
    final.parent.mkdir()
    final.write_bytes(b"last delivered")
    monkeypatch.setattr(draft, "owner_language", lambda _: "en")
    monkeypatch.setattr(draft.print_edition, "printer_name", lambda _: "test-printer")
    monkeypatch.setattr(draft.print_edition, "printer_url", lambda _: None)
    monkeypatch.setattr(draft.print_edition, "receipt_paper", lambda _: True)
    rendered = []
    class HTML:
        def __init__(self, string):
            rendered.append(string)
        def write_pdf(self, path):
            Path(path).write_bytes(b"%PDF draft")
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))
    monkeypatch.setattr(draft.print_edition, "connect", lambda: types.SimpleNamespace(call_tool=None))
    calls = []
    monkeypatch.setattr(draft.print_edition, "ship", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert draft.main([str(source), "config.json"]) == 0
    assert "calendar unavailable" in rendered[0]
    assert "72mm" in rendered[0]
    assert calls[0][0][0] == str(tmp_path / "run" / "draft" / "draft.pdf")
    assert calls[0][0][2].endswith("-draft")
    assert calls[0][1] == {}
    assert source.read_bytes() == original
    assert final.read_bytes() == b"last delivered"
    assert not (tmp_path / "paper-attempts-grant").exists()


def test_bad_json_removes_stale_draft_without_printing(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    target = tmp_path / "run" / "draft" / "draft.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stale")
    source = tmp_path / "edition.json"
    source.write_text('{broken')
    assert draft.main([str(source), "config.json"]) == 1
    assert not target.exists()


def test_shared_printer_sends_draft_pdf_without_receipt_conversion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    source = tmp_path / "edition.json"
    source.write_text('{}')
    monkeypatch.setattr(draft, "owner_language", lambda _: "en")
    monkeypatch.setattr(draft.print_edition, "printer_name", lambda _: None)
    monkeypatch.setattr(draft.print_edition, "printer_url", lambda _: "https://printer.invalid")
    monkeypatch.setattr(draft.print_edition, "receipt_paper", lambda _: True)
    monkeypatch.setattr(draft.print_edition, "_printer", lambda _: {"key": "synthetic"})
    class HTML:
        def __init__(self, string):
            assert '72mm 2000mm' in string
        def write_pdf(self, path):
            Path(path).write_bytes(b"%PDF draft")
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))
    calls = []
    monkeypatch.setattr(draft.print_edition, "send_to_url",
                        lambda *args: calls.append(args) or {"position": 2})
    assert draft.main([str(source), "config.json"]) == 0
    assert calls == [(str(tmp_path / "run" / "draft" / "draft.pdf"), "https://printer.invalid", "synthetic")]
    assert "queue position 2" in capsys.readouterr().out
