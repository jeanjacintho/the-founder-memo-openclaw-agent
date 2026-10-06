"""wiki.py -- The Founder Memo's pages in the owner's wiki, over Latch.

The wiki is plow-wiki: an Obsidian vault at ~/Plow/wiki in OKF v0.2, kept by
the `wiki` plugin Latch bundles. The memo owns one root,
projects/founder-memo (writer `founder-memo`), and shares one page,
entities/owner/goals.md. Pages move with plow_read_file and
plow_write_file (no approval inside ~/Plow); the CLI runs through
plow_run_command, under whatever approval mode the Mac is in.
"""
from __future__ import annotations

import yaml
import json

from latch_mcp import LatchError, finish_command
from latch_mcp import connect as latch_connect

WIKI = "~/Plow/wiki"
WRITER = "founder-memo"
ROOT = f"projects/{WRITER}"
OVERVIEW = f"{ROOT}/{WRITER}.md"
# The day's printed edition until memo-render records memos/<date>.md instead.
EDITIONS = f"{ROOT}/editions"
MEMOS = f"{ROOT}/memos"
QA = f"{ROOT}/qa.md"
RESOURCES = f"{ROOT}/resources.md"
GOALS = "entities/owner/goals.md"
SCHEMA = f"_meta/schemas/{ROOT}.md"
PAPER_LINK = f"[The Founder Memo](/{OVERVIEW})"


def split_page(text):
    """(frontmatter, body) of an OKF page; a page without frontmatter is ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        return {}, text
    return yaml.safe_load(head) or {}, body


def join_page(meta, body):
    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n{body}"


class Wiki:
    def __init__(self, call_tool):
        self._call = call_tool

    def read_path(self, path):
        """A file's text on the Mac, or None when it does not exist."""
        try:
            return self._call("plow_read_file", {"path": path})["content"]
        except LatchError as exc:
            if "ENOENT" in str(exc):
                return None
            raise

    def read(self, rel):
        return self.read_path(f"{WIKI}/{rel}")

    def write(self, rel, text):
        self._call("plow_write_file", {"path": f"{WIKI}/{rel}", "content": text})

    def run(self, *args, write=False):
        """`wiki <args>` through Latch's wiki plugin: (exit_code, output)."""
        params = {"argv": ["wiki", *args], "wait_ms": 60000,
                  "goal": f"Keep The Founder Memo's pages in your wiki (wiki {args[0]})"}
        if write:
            params["write_paths"] = [WIKI]
        result = finish_command(
            self._call, self._call("plow_run_command", params), f"wiki {args[0]}",
        )
        return int(result["exit_code"]), str(result.get("output") or "")

    def compare_and_swap(self, rel, expected, replacement):
        """Check and replace on the Mac; False means its owner changed the page."""
        script = '''import json, os, sys, tempfile
from pathlib import Path
rel, expected, replacement = json.loads(sys.argv[1])
path = Path.home() / "Plow/wiki" / rel
def current():
    try: return path.read_bytes()
    except FileNotFoundError: return None
expected = expected.encode("utf-8") if expected is not None else None
if current() != expected: sys.exit(3)
if replacement is None:
    path.unlink()
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".memo-")
    try:
        with os.fdopen(fd, "wb") as out: out.write(replacement.encode("utf-8"))
        os.chmod(tmp, path.stat().st_mode & 0o777 if expected is not None else 0o644)
        if current() != expected: sys.exit(3)
        if expected is None:
            try: os.link(tmp, path)
            except FileExistsError: sys.exit(3)
        else: os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
'''
        result = finish_command(self._call, self._call("plow_run_command", {
            "argv": ["python3", "-c", script, json.dumps([rel, expected, replacement])],
            "write_paths": [WIKI], "wait_ms": 60000,
            "goal": "Update the entity page only if its owner has not changed it",
        }), "conditional wiki update")
        code = int(result["exit_code"])
        if code not in (0, 3):
            raise LatchError(f"conditional wiki update: {result.get('output', '')}")
        return code == 0

    def _validate(self, writer, rel=None):
        """`wiki validate --writer <writer>`'s problem lines; exit 2 (unknown writer) raises."""
        code, out = self.run("validate", "--writer", writer)
        if code not in (0, 1):
            raise LatchError(f"wiki validate --writer {writer}: {out.strip()}")
        return [line for line in out.splitlines() if rel is None or line.startswith(rel + ":")] if code else []

    def check(self):
        """`wiki validate` of this paper's root and its one shared page, then
        `wiki index`. Another writer's page is that writer's to fix."""
        ours = self._validate(WRITER) + [
            line for line in self._validate("shared") if line.startswith(GOALS)]
        if ours:
            raise LatchError("wiki validate: " + "; ".join(ours))
        code, out = self.run("index", write=True)
        if code != 0:
            raise LatchError(f"wiki index: {out.strip()}")


def connect():
    return Wiki(latch_connect().call_tool)
