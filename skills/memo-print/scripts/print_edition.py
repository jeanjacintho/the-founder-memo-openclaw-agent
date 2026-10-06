#!/usr/bin/env python3
"""print_edition.py -- the paper edition's Latch leg, from disk, not the model.

Measured live 2026-09-17: memo-print told the model to `cat` edition.html and
paste that ~43k page into plow_write_file's `content`. The LLM stream died
mid tool-call (RemoteProtocolError: incomplete chunked read); `lp` never
ran. The chat PDF still arrived because post_to_chat.py reads the file
itself. This script is that same shape for paper.

A later run that DID reach `lp` failed because the CUPS queue refused HTML
(`Unsupported document-format "text/html"` on JornalVirtual). The file
shipped is edition.pdf, the one the chat already got; a 72 mm roll
(printer.paper "72mm") gets receipt.pdf, rendered beside it. Latch write_file is
text, so the PDF rides as base64 and is decoded on the Mac before `lp`.

Usage:

    print_edition.py <edition.pdf> <config.json>

Date comes from sibling edition.json. Skips with exit 0 when
printer.configured is not true. Any failure exits non-zero with its reason
as the last line; post_to_chat.py turns that into the owner's chat line
(issue #79: the exit status, not a phrase, says the page did not print).
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shlex
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent / "memo-shared" / "scripts"))
from latch_mcp import LatchError, connect, finish_command

# tsp143.ppd's tallest 72 mm page. Without it CUPS shrinks the receipt onto
# the default 72x200 mm page; the driver's variable length cuts after the ink.
RECEIPT_MEDIA = "X72MMY2000MM"

PATH_RE = re.compile(
    r"(/Users/[^\s'\"]+/Plow/pt/edition-[0-9-]+\.pdf(?:\.b64)?)"
)


def _printer(config_path):
    try:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    printer = cfg.get("printer") if isinstance(cfg, dict) else None
    return printer if isinstance(printer, dict) else {}


def printer_name(config_path):
    """CUPS name when printer.configured is exactly true; else None (skip)."""
    printer = _printer(config_path)
    if printer.get("configured") is not True:
        return None
    name = printer.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip()


def printer_url(config_path):
    """An event install's shared printer: the https print server its receipt is POSTed to."""
    printer = _printer(config_path)
    url = printer.get("url") if printer.get("configured") is True else None
    return url if isinstance(url, str) and url.startswith("https://") else None


def send_to_url(pdf_path, url, key):
    """POST the receipt to the event's print server (the event Mac, behind Tailscale
    Funnel) with the event's public key. 200 means it is queued and prints in order; a
    refusal names its reason, which post_to_chat shows the owner. No Mac, no Latch."""
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    from bearer_http import require  # noqa: PLC0415
    from owner_chat import fetch_identity  # noqa: PLC0415

    identity = fetch_identity(require("PLOW_API_BASE").rstrip("/"), require("PLOW_AGENT_TOKEN"))
    with open(pdf_path, "rb") as fh:
        data = fh.read()
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/pdf",
        # The server's per-agent cap keys on this: agent.uid is unique across accounts
        # (a line uid like ln_p7 is not).
        "X-Plow-Agent": identity["agent"]["uid"]})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            reason = json.loads(exc.read()).get("reason") or f"HTTP {exc.code}"
        except ValueError:
            reason = f"HTTP {exc.code}"
        sys.exit(f"error: the event printer refused the receipt: {reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"error: the event printer could not be reached: {exc.reason}")


def receipt_paper(config_path):
    """printer.paper "72mm": a thermal roll, which gets the receipt page."""
    return _printer(config_path).get("paper") == "72mm"


def write_receipt(pdf_path):
    """receipt.pdf beside edition.pdf, from the same edition.json."""
    sys.path.insert(0, str(_HERE.parent.parent / "memo-render" / "scripts"))
    import render_memo  # noqa: PLC0415 -- only a roll needs WeasyPrint

    run_dir = Path(pdf_path).resolve().parent
    try:
        memo = json.loads((run_dir / "edition.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.exit(f"error: no edition.json for the receipt page: {exc}")
    receipt = run_dir / "receipt.pdf"
    render_memo.write_pdf(render_memo.receipt_html(memo), receipt)
    return str(receipt)


def read_pdf(path):
    try:
        data = Path(path).read_bytes()
    except OSError:
        sys.exit(f"error: pdf path cannot be read: {path}")
    if not data:
        sys.exit(f"error: pdf is empty: {path}")
    return data


def edition_date(pdf_path):
    sibling = Path(pdf_path).resolve().parent / "edition.json"
    try:
        data = json.loads(sibling.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        sys.exit(f"error: sibling edition.json has no date: {sibling}")
    date = data.get("date") if isinstance(data, dict) else None
    if not isinstance(date, str) or not date.strip():
        sys.exit(f"error: sibling edition.json has no date: {sibling}")
    return date.strip()


def mac_pdf_path(date):
    return f"~/Plow/pt/edition-{date}.pdf"


def mac_b64_path(date):
    return f"~/Plow/pt/edition-{date}.pdf.b64"


def pdf_path_from_b64(b64_path):
    if b64_path.endswith(".b64"):
        return b64_path[:-4]
    return b64_path


def written_path(parsed):
    candidates = []
    if isinstance(parsed, dict):
        for key in ("path", "absolute_path", "file", "wrote"):
            if parsed.get(key):
                candidates.append(parsed[key])
        if parsed.get("raw"):
            candidates.append(parsed["raw"])
    else:
        candidates.append(parsed)
    blob = " ".join(str(c) for c in candidates)
    match = PATH_RE.search(blob)
    if match:
        return match.group(1)
    if candidates:
        first = str(candidates[0])
        if first.startswith("/"):
            return first
    sys.exit("error: write did not return a Mac path")


def is_bfd(parsed):
    blob = json.dumps(parsed) if not isinstance(parsed, str) else parsed
    return "bad file descriptor" in blob.lower()


def require_exit_zero(call_tool, result, step):
    """The finished run's exit_code must be 0; anything else is no page (issue #35)."""
    result = finish_command(call_tool, result, step)
    if result["exit_code"] not in (0, "0"):
        output = " ".join(str(result.get("output", result)).split())
        sys.exit(f"error: {step} {result['exit_code']}: {output}")


def ship(pdf_path, printer, date, call_tool, lp_options=()):
    pdf = read_pdf(pdf_path)
    dest_b64 = mac_b64_path(date)

    wrote = call_tool(
        "plow_write_file",
        {"path": dest_b64, "content": base64.b64encode(pdf).decode("ascii")},
    )
    abs_b64 = written_path(wrote)
    abs_pdf = pdf_path_from_b64(abs_b64)
    decoded = call_tool(
        "plow_run_command",
        {
            "argv": ["base64", "-D", "-i", abs_b64, "-o", abs_pdf],
            "read_paths": [abs_b64],
            "write_paths": [abs_pdf],
            "goal": "Decode the edition PDF on the owner's Mac",
        },
    )
    require_exit_zero(call_tool, decoded, "base64")
    lp = call_tool(
        "plow_run_command",
        {
            "argv": ["lp", "-d", printer, *lp_options, abs_pdf],
            "network": True,
            "read_paths": [abs_pdf],
            "goal": "Print today's Founder Memo",
        },
    )
    lp = finish_command(call_tool, lp, "lp")  # a running lp can still fail with BFD
    if is_bfd(lp):
        cmd = shlex.join(["lp", "-d", printer, *lp_options, abs_pdf])
        lp = call_tool(
            "plow_run_applescript",
            {
                "app": "System Events",
                "script": f"do shell script {json.dumps(cmd)}",
                "goal": "Print today's Founder Memo (sandboxed lp failed)",
            },
        )
    require_exit_zero(call_tool, lp, "lp")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write the edition PDF to the owner's Mac and print it."
    )
    parser.add_argument("pdf")
    parser.add_argument("config")
    parser.add_argument("--date", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    printer = printer_name(args.config)
    url = printer_url(args.config)
    if not printer and not url:
        print("skipped: printer.configured is not true")
        return
    date = args.date or edition_date(args.pdf)
    if url:  # an event install: the receipt goes to the event's shared printer
        if args.dry_run:
            print(f"dry-run: would send the receipt to the event printer {url}")
            return
        key = _printer(args.config).get("key") or ""
        queued = send_to_url(write_receipt(args.pdf) if receipt_paper(args.config) else args.pdf, url, key)
        print(f"page sent to the event printer (queue position {queued.get('position', '?')})")
        return
    lp_options = ["-o", f"media={RECEIPT_MEDIA}"] if receipt_paper(args.config) else []
    if args.dry_run:
        print(f"dry-run: would write {mac_pdf_path(date)} and {shlex.join(['lp', '-d', printer, *lp_options])}")
        return

    pdf = write_receipt(args.pdf) if lp_options else args.pdf
    try:
        ship(pdf, printer, date, connect().call_tool, lp_options)
    except LatchError as exc:
        sys.exit(f"error: {exc}")
    print(f"page printed on {printer}")


if __name__ == "__main__":
    main()
