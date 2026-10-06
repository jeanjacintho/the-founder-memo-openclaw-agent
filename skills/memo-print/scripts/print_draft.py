#!/usr/bin/env python3
"""Print the current edition.json as a development draft, without research or delivery.

print_draft.py <edition.json> <config.json>
The separate draft.pdf is a diagnostic snapshot, not a validated memo.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "memo-render" / "scripts"))
sys.path.insert(0, str(HERE.parent.parent / "memo-shared" / "scripts"))
import render_memo
import print_edition
from owner_phrases import phrase, status
from owner_time import owner_today
from pt_paths import pt_home
from setup_needed import owner_language


def draft_html(edition, language, paper="Letter"):
    """Preserve all supplied fields, including failed reads; never promote them to advice."""
    problems = render_memo.memo_problems(edition)
    problems.insert(0, phrase("draft.unverified", language))
    width = "72mm 2000mm" if paper == "72mm" else "Letter"
    margin = "4mm" if paper == "72mm" else "15mm"
    payload = html.escape(json.dumps(edition, ensure_ascii=False, indent=2))
    failures = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
    return (f'<!doctype html><html lang="{html.escape(language)}"><meta charset="utf-8">'
            f'<style>@page {{size: {width}; margin: {margin}; '
            '@top-center {content: "DRAFT"; font: bold 10pt sans-serif;}} '
            'body {font: 11pt/1.4 sans-serif;} h1 {font-size: 20pt;} '
            'pre {font: 9pt/1.4 monospace; white-space: pre-wrap; overflow-wrap: anywhere;}'
            '</style><h1>DRAFT</h1>'
            f'<h2>{html.escape(phrase("draft.problems", language))}</h2><ul>{failures}</ul>'
            f'<h2>{html.escape(phrase("draft.content", language))}</h2><pre>{payload}</pre></html>')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("edition_json")
    parser.add_argument("config")
    args = parser.parse_args(argv)
    target = pt_home() / "run" / "draft" / "draft.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        edition = json.loads(Path(args.edition_json).read_text(encoding="utf-8"))
        language = owner_language(args.config)
        if status(language) != "ready":
            raise ValueError("owner phrases need translation before printing a draft")
        printer = print_edition.printer_name(args.config)
        url = print_edition.printer_url(args.config)
        if not printer and not url:
            print("skipped: printer.configured is not true")
            return 0
        roll = print_edition.receipt_paper(args.config)
        from weasyprint import HTML
        HTML(string=draft_html(edition, language, "72mm" if roll else "Letter")).write_pdf(str(target))
        if url:
            key = print_edition._printer(args.config).get("key") or ""
            queued = print_edition.send_to_url(str(target), url, key)
            print(f"draft sent to the event printer (queue position {queued.get('position', '?')})")
        else:
            options = ["-o", f"media={print_edition.RECEIPT_MEDIA}"] if roll else []
            print_edition.ship(str(target), printer, owner_today().isoformat(),
                               print_edition.connect().call_tool, options, draft=True)
            print(f"draft printed on {printer}")
        return 0
    except (OSError, ValueError, ImportError, print_edition.LatchError) as exc:
        target.unlink(missing_ok=True)
        print(f"error: draft not printed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
