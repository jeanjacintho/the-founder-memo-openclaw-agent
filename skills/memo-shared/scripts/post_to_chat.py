#!/usr/bin/env python3
"""Post the memo PDF directly to the owner's Plow Chat, then print and record it.

Endpoint and bearer come from the process environment, never a writable file.
The PDF is delivered immediately. After the confirmed POST, a recovery ticket
snapshots the PDF and sibling edition.json before independent print/record
finalizers run. --recover resumes only those finalizers, never another POST.
--dry-run prints the redacted envelope without sending.
"""
from __future__ import annotations

import argparse
import fcntl
import mimetypes
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from bearer_http import post_json, post_json_read, put_bytes, require
from owner_chat import home_channel, receipt_code
from owner_phrases import phrase
from printer_config import read_printer
import run_attempts
from owner_time import owner_now
from pt_paths import config_file, pt_home
from setup_needed import owner_language


CONFIG_DEFAULT = str(config_file())
PRINT_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "memo-print"
    / "scripts"
    / "print_edition.py"
)
RECORD_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "memo-render"
    / "scripts"
    / "record_memo.py"
)


MAX_FINALIZER_ATTEMPTS = 5


def delivery_recovery_dir():
    return pt_home() / "delivery-recovery"


def last_edition_dir():
    return pt_home() / "last-edition"


def keep_last_edition(folder):
    """The posted memo's PDF and json, for "print it again" (#92): the owner gets
    a page with no research and no model call. Each delivery replaces it."""
    building = pt_home() / f".last-edition-{os.getpid()}"
    shutil.rmtree(building, ignore_errors=True)
    building.mkdir(parents=True)
    for name in ("edition.json", "edition.pdf"):
        if (folder / name).is_file():
            shutil.copyfile(folder / name, building / name)
    shutil.rmtree(last_edition_dir(), ignore_errors=True)
    os.replace(building, last_edition_dir())


def _write_delivery_state(ticket, state):
    temporary = ticket.with_name(f".{ticket.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, ticket)


def persist_posted_delivery(edition_json, pdf, delivered_at):
    """Snapshot a posted edition and its remaining finalizers before running any."""
    if not edition_json or not Path(edition_json).is_file():
        return None
    root = delivery_recovery_dir()
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{delivered_at:%Y%m%dT%H%M%S}-{uuid.uuid4().hex}"
    building = root / f".building-{folder.name}-{os.getpid()}"
    shutil.rmtree(building, ignore_errors=True)
    building.mkdir()
    try:
        edition_json = Path(edition_json)
        shutil.copyfile(edition_json, building / "edition.json")
        actual_pdf = Path(pdf)
        if actual_pdf.is_file():
            shutil.copyfile(actual_pdf, building / "edition.pdf")
        state = {
            "delivered_at": delivered_at.isoformat(),
            "edition_json": "edition.json",
            "pdf": "edition.pdf" if (building / "edition.pdf").is_file() else None,
            "print_path": "edition.pdf" if (building / "edition.pdf").is_file() else str(actual_pdf),
            "finalizers_pending": ["print", "record"],
            "attempts": {},
        }
        _write_delivery_state(building / "delivery.json", state)
        os.replace(building, folder)
        return folder / "delivery.json"
    except Exception:
        shutil.rmtree(building, ignore_errors=True)
        raise


def recover_delivery(ticket, *, notify_print_failure=False, wait=True):
    """Run only persisted finalizers; this path never posts the edition again."""
    ticket = Path(ticket)
    folder = ticket.parent
    if not ticket.exists():
        return []
    lock_path = folder / ".recovery.lock"
    try:
        lock_file = open(lock_path, "a")
    except FileNotFoundError:
        # Another worker completed this ticket between the existence check
        # and acquiring its per-delivery lock.
        return []
    with lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            return []
        if not ticket.exists():
            return []
        try:
            state = json.loads(ticket.read_text(encoding="utf-8"))
            edition_json = str(folder / state["edition_json"])
            delivered_at = datetime.fromisoformat(state["delivered_at"])
            pending = state["finalizers_pending"]
            if not isinstance(pending, list) or not all(isinstance(item, str) for item in pending):
                raise ValueError("finalizers_pending must be a list of names")
            attempts = state.setdefault("attempts", {})
            if not isinstance(attempts, dict) or any(
                not isinstance(value, int) or value < 0 for value in attempts.values()
            ):
                raise ValueError("attempts must map finalizer names to non-negative integers")
            if any(item not in ("print", "record") for item in pending):
                raise ValueError("finalizers_pending contains an unknown finalizer")
        except (OSError, ValueError, TypeError, KeyError):
            return ["invalid delivery recovery state"]
        pending = list(pending)
        failures = []
        for finalizer in ("print", "record"):
            if finalizer not in pending:
                continue
            if attempts.get(finalizer, 0) >= MAX_FINALIZER_ATTEMPTS:
                failures.append(f"{finalizer} retry limit reached")
                continue
            if finalizer == "print":
                print_path = state.get("print_path")
                line = print_page(str(folder / print_path) if print_path == "edition.pdf" else print_path) if print_path else None
                if line:
                    print(line)
                # Why it did not print, or at an event, that it did and where to get it.
                if notify_print_failure and (line or (print_path and event_receipt())):
                    try:
                        base, uid, token = resolve_chat()
                        post_json(base, f"/v1/chats/{uid}/messages", token, "Plow Chat",
                                  {"body": line or printed_line(uid)})
                    except (Exception, SystemExit) as exc:
                        print(f"print notice not posted: {exc}", file=sys.stderr)
                # Printing can have an unknown outcome; never auto-print twice.
                succeeded = True
            else:
                result = _best_effort(
                    run_record_memo, (edition_json, delivered_at), "memo not recorded"
                )
                print(result)
                succeeded = "memo not recorded" not in result
            if succeeded:
                pending.remove(finalizer)
                state["finalizers_pending"] = pending
                _write_delivery_state(ticket, state)
            else:
                attempts[finalizer] = attempts.get(finalizer, 0) + 1
                _write_delivery_state(ticket, state)
                failures.append(finalizer)
        if not pending:
            shutil.rmtree(folder, ignore_errors=True)
        return failures


def resolve_chat():
    """The chat endpoint (base + path) + bearer, validated before anything posts."""
    base = require("PLOW_API_BASE").rstrip("/")
    uid = home_channel()
    token = require("PLOW_AGENT_TOKEN")
    return base, uid, token


def attachment_filename(pdf_path, override=None):
    """The name Plow Chat shows on the attachment.

    Measured live: declare used os.path.basename of the run-dir file, so
    the owner saw "edition.pdf" in the thread. An override is a single
    basename (no slash), and always ends in .pdf.
    """
    name = override if override else os.path.basename(pdf_path)
    name = name.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        sys.exit("error: --filename must be a basename, not a path")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def _best_effort(run, args, failure):
    """One finalizer, run to completion, never raised: SystemExit or any other
    exception becomes a failure string, exactly like the runner's own.
    """
    try:
        out = run(*args)
    except SystemExit as exc:
        out = str(exc) if exc.args else failure
    except Exception as exc:
        out = f"{failure} — {exc}"
    return (out or "").strip() or f"{failure} — empty result"


PRINT_TIMEOUT = 600


def print_page(pdf_path):
    """Print the page; the owner's one chat line if it did not, else None.

    print_edition.py exits 0 when it printed or when printer.configured is
    not true (silence). Any other exit, a hang, or a crash owes the owner a
    line, since the turn ends in NO_REPLY. The exit status says it failed
    and the script's last line says why (issue #79: no phrase is both the
    owner's lede and the selector), kept untranslated as diagnostic detail;
    the words this repo authors follow the owner's language. Measured
    2026-09-22: an on-demand run with a configured printer printed nothing
    and said nothing.
    """
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, str(PRINT_SCRIPT), pdf_path, CONFIG_DEFAULT],
            capture_output=True,
            text=True,
            timeout=PRINT_TIMEOUT,
        )
        blob = ((proc.stdout or "") + (proc.stderr or "")).strip()
        print(blob)
        if proc.returncode == 0:
            return None
        detail = blob.splitlines()[-1] if blob else f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        detail = None
    except Exception as exc:
        detail = str(exc)
    # The print-miss words are owner_phrases.py's: the owner's own language
    # when the paper has written it, curated Portuguese or English otherwise.
    language = owner_language(CONFIG_DEFAULT)
    lede = phrase("print.lede", language)
    if detail is None:  # an unknown outcome may still print: no retry promise
        return lede + phrase("print.timeout", language, seconds=PRINT_TIMEOUT)
    if not os.path.isfile(pdf_path):
        detail = phrase("print.no_pdf", language, path=pdf_path)
    line = lede + detail.removeprefix("error: ")[:200]
    return line if "outcome unknown" in detail else line + phrase("print.retry", language)


RECORD_TIMEOUT = 300


def run_record_memo(edition_json, delivered_at):
    """delivered_at is captured once in main(), immediately before the chat
    POST, under the same delivery-order lock, and passed through -- not a
    fresh owner_now() here, well after whatever the print step's own
    polling took, which would otherwise stand in for this edition's own
    time and let it out-race an already-recorded one that posted later but
    printed faster (issue #48)."""
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, str(RECORD_SCRIPT), edition_json,
             "--now", delivered_at.isoformat()],
            capture_output=True,
            text=True,
            timeout=RECORD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"memo not recorded — timed out after {RECORD_TIMEOUT}s"
    blob = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        if "memo not recorded" in blob:
            return blob
        return f"memo not recorded — {blob or proc.returncode}"
    return blob


def declare_and_upload(base, uid, token, pdf_path, filename=None):
    """Declare the attachment, PUT its bytes to the signed upload_url, return its uid.

    Mirrors plow-chat-platform's own ``_send_attachment`` exactly (same three
    calls, same field names) -- this is not a new contract, just this
    script's own copy of the one Plow's REST API defines.
    """
    if not os.path.isfile(pdf_path):
        sys.exit(f"error: --pdf path does not exist: {pdf_path}")
    with open(pdf_path, "rb") as fh:
        data = fh.read()
    filename = attachment_filename(pdf_path, filename)
    content_type = mimetypes.guess_type(filename)[0] or "application/pdf"
    declared = post_json_read(
        base, f"/v1/chats/{uid}/attachments", token, "Plow Chat attachment declare",
        {"filename": filename, "content_type": content_type, "size_bytes": len(data)},
    )
    put_bytes(declared["upload_url"], declared.get("upload_headers") or {}, data,
              "Plow Chat attachment")
    return declared["uid"]


def main():
    parser = argparse.ArgumentParser(description="Post the memo PDF or recover its finalizers.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--pdf", help="memo PDF to upload and post immediately")
    action.add_argument("--recover", action="store_true", help="resume posted memos' print/record finalizers")
    parser.add_argument("--filename", help="attachment basename shown in chat")
    parser.add_argument("--dry-run", action="store_true", help="print the redacted request without sending")
    parser.add_argument("--clear-attempts", action="store_true", help="clear attempts after confirmed delivery")
    args = parser.parse_args()
    if args.recover:
        sys.exit(main_recover())
    base, uid, token = resolve_chat()
    if args.dry_run:
        print(f"dry-run: would POST pdf-only to {base}/v1/chats/{uid}/messages"
              f" + attach {args.pdf} as {attachment_filename(args.pdf, args.filename)}")
        return
    deliver(base, uid, token, pdf=args.pdf, filename=args.filename,
            on_posted=run_attempts.clear if args.clear_attempts else None)


def event_receipt():
    """An event install's printer (only those have a printer.url, the event's print server):
    a printed memo owes the attendee a line. Read from config, not the environment, so a
    recovery run says it too."""
    printer = read_printer(CONFIG_DEFAULT)
    return printer.get("configured") is True and bool(printer.get("url"))


def printed_line(uid):
    """The attendee's "go get it" once the event printer took the memo (the CEO's words, Oct 6),
    in their language. The code is the one the slip prints, so the slip and the phone match."""
    return phrase("print.ready", owner_language(CONFIG_DEFAULT), code=receipt_code(uid))


def deliver(base, uid, token, *, pdf, filename=None, on_posted=None):
    """POST the PDF, then print and record; a confirmed POST is never retried."""
    attachment_uid = declare_and_upload(base, uid, token, pdf, filename=filename)
    body = {"body": "", "attachment_uids": [attachment_uid]}

    # Two concurrent runs (the daily job and an on-demand copy, say) can
    # commit their messages in one order but have their HTTP responses land
    # in the other -- owner_now() read right after each POST would then
    # stamp the later-sent message as the earlier one, corrupting priority
    # ordering (issue #48). Serializing the clock read together with the
    # POST under one lock keeps send order and stamp order the same. The
    # read comes FIRST, still inside the lock: owner_now() raises on a
    # configured-but-invalid owner.timezone, and that has to fail before the
    # message is actually sent, not after -- post_json() has already
    # delivered the edition by the time any later step, finalizer, or
    # recovery instruction could run, so a bad timezone caught only there
    # would report a generic failure with no "do not repost" and risk a
    # duplicate send on retry.
    lock_path = pt_home() / "run" / "delivery-order.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        delivered_at = owner_now()
        post_json(base, f"/v1/chats/{uid}/messages", token, "Plow Chat", body)
        # Still under the POST lock, before any finalizer: the kept copy is the last
        # memo posted, whatever its finalizers do later (#92). It is posted, so a
        # failed copy costs only "print it again", never this delivery.
        try:
            keep_last_edition(Path(pdf).parent)
        except Exception as exc:
            print(f"last memo not kept for reprint: {exc}", file=sys.stderr)
    edition_json = str(Path(pdf).parent / "edition.json")
    if on_posted:
        on_posted()
    try:
        recovery_ticket = persist_posted_delivery(edition_json, pdf, delivered_at)
    except Exception as exc:
        print(f"post-delivery recovery ticket could not be saved: {exc}; running finalizers inline",
              file=sys.stderr)
        recovery_ticket = None
    print(f"chat edition posted (pdf only) {pdf}")
    if recovery_ticket:
        recoveries = recover_delivery(recovery_ticket, notify_print_failure=True)
        if recoveries:
            sys.exit("error: post-delivery finalization remains pending; memo-deliver retries it; do not repost")
        return

    line = print_page(pdf)
    if line or event_receipt():
        try:  # the edition already posted: exit 0 must keep meaning that
            post_json(base, f"/v1/chats/{uid}/messages", token, "Plow Chat", {"body": line or printed_line(uid)})
        except SystemExit as exc:
            print(f"print notice not posted: {exc}", file=sys.stderr)
    recorded = _best_effort(run_record_memo, (edition_json, delivered_at), "memo not recorded")
    print(recorded)
    recoveries = []
    if "memo not recorded" in recorded:
        recoveries.append(f"record_memo.py <edition.json> --now {delivered_at.isoformat()}")
    if recoveries:
        sys.exit(
            "error: post-delivery finalization failed; recover with "
            + "; ".join(recoveries)
            + "; do not repost"
        )


def main_recover():
    """Resume post-delivery finalizers without posting another memo."""
    failed = False
    recovery_root = delivery_recovery_dir()
    if recovery_root.is_dir():
        for ticket in sorted(recovery_root.glob("*/delivery.json")):
            if ticket.parent.name.startswith("."):
                continue
            failures = recover_delivery(ticket, notify_print_failure=True, wait=False)
            if failures:
                print(f"{ticket.parent.name}: pending finalizers: {', '.join(failures)}", file=sys.stderr)
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    main()
