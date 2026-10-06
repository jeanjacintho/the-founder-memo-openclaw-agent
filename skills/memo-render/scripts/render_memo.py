#!/usr/bin/env python3
"""render_memo.py -- the night's memo in, one printed page out.

    render_memo.py <memo.json> [--tournament <tournament.json>] --pdf OUT [--html OUT]

The model fills `memo.json`; this script -- fixed code over a fixed
`template.html` -- turns it into the printable HTML and the PDF. The model
never writes HTML. Every string is HTML-escaped here, once, in code: the
evidence came from the owner's mail and the web, and the page renders on the
owner's Mac.

memo.json is one of two shapes, both with
`"date": "YYYY-MM-DD"`, `"language": "<owner.language>"` and
`"run": {"usd": <float or null>, "minutes": <int>}`:

  * the night's three priorities: `"priority": {"recommendations": [3 items],
    "questions": [...]}`, the culler's card. It prints only beside
    `--tournament`, the accepted checkpoint it came from: dated the memo's
    date, at least three completed generations, its gated stage, and its
    champions and card exactly the ones printed.
  * a night that reached no accepted checkpoint: `"could_not_source":
    ["<why, in the owner's language>"]`, printed as the reason.

The card is refused, by name, when a recommendation's advisor quote is not
verbatim in that advisor's file (bound to its own source URL), when two
recommendations rest on the same quoted line -- across every advisor's file,
not per advisor -- or when the card names a file path or calls the reader
"the founder". The footer is the run's cost and duration; an unknown cost
says so, never $0.00. Exit 1 prints `error: memo refused — <why>`.
The PDF is refused if it exceeds one Letter page; shorten the card and retry.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "memo-shared" / "scripts"))
from owner_phrases import phrase, status  # noqa: E402

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "memo-template.html"
ADVISORS = pathlib.Path(__file__).resolve().parents[2] / "memo-setup" / "assets" / "advisors"
MASTHEAD = "The Founder Memo"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BODY_MAX = 1024
# Page rules on the card's own words: no file or path, never the reader in the third person.
FILE_RE = re.compile(r"\S+\.(?:md|json|csv|py|txt)\b|~/|/var/lib|\brun/")
SELF_RE = re.compile(
    r"\b(?:the (?:founder|ceo|owner)|a founder should|o (?:fundador|ceo|dono)|a (?:fundadora|dona))\b",
    re.I,
)


class CardError(ValueError):
    """The memo cannot be printed as written; the message names every problem."""


def blank(value):
    return not (isinstance(value, str) and value.strip())


def _http(url):
    return isinstance(url, str) and url.strip().startswith(("http://", "https://"))


def _real_date(raw):
    if not (isinstance(raw, str) and DATE_RE.fullmatch(raw)):
        return False
    try:
        date.fromisoformat(raw)
    except ValueError:
        return False
    return True


def advisor_catalog():
    """Advisor name -> {normalized quote: its source URL}, from every advisor file."""
    catalog = {}
    for path in ADVISORS.glob("*.md"):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        front = parts[1] if len(parts) == 3 else ""
        name = next((line.split(":", 1)[1].strip() for line in front.splitlines()
                     if line.startswith("advisor:")), "")
        sources = {line.strip()[2:].strip() for line in front.splitlines()
                   if line.strip().startswith("- http")}
        sourced = text.partition("## Sourced words")[2].split("\n## ", 1)[0]
        quotations = {}
        for line in sourced.splitlines():
            quote, separator, citation = line.removeprefix("- “").rpartition("” — [")
            _label, link_separator, url = citation.rpartition("](")
            url = url.removesuffix(")")
            if line.startswith("- “") and separator and link_separator and url in sources:
                quotations[" ".join(quote.split())] = url
        if name:
            catalog[name] = quotations
    return catalog


def card_problems(priority):
    """Every reason the culler's card cannot print; [] when it can."""
    if not isinstance(priority, dict):
        return ["priority is not an object"]
    failures = []
    advisors = advisor_catalog()
    recommendations = priority.get("recommendations")
    if not isinstance(recommendations, list) or len(recommendations) != 3:
        failures.append("priority.recommendations needs exactly 3 items")
        recommendations = []
    quotes = []
    for i, item in enumerate(recommendations):
        where = f"recommendations[{i}]"
        if not isinstance(item, dict):
            failures.append(f"{where} is not an object")
            continue
        for key in ("headline", "body", "first_step"):
            if blank(item.get(key)):
                failures.append(f"{where}.{key} is blank")
        if isinstance(item.get("body"), str) and len(item["body"]) > BODY_MAX:
            failures.append(f"{where}.body is over {BODY_MAX} characters")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
            failures.append(f"{where}.evidence needs 1 to 3 items")
        else:
            for j, fact in enumerate(evidence):
                if not isinstance(fact, dict) or blank(fact.get("claim")) or blank(fact.get("source")):
                    failures.append(f"{where}.evidence[{j}] needs a claim and a source")
                elif fact.get("url") is not None and not _http(fact["url"]):
                    failures.append(f"{where}.evidence[{j}].url is not an http(s) URL")
        advisor = item.get("advisor")
        if not isinstance(advisor, dict) or blank(advisor.get("name")) or blank(advisor.get("quote")):
            failures.append(f"{where}.advisor needs a name and a quote")
            continue
        if not _http(advisor.get("url")):
            failures.append(f"{where}.advisor.url is not an http(s) URL")
        quote = " ".join(advisor["quote"].split())
        quotes.append(quote)
        source = advisors.get(advisor["name"])
        if source is None:
            failures.append(f"{where}.advisor.name has no named advisor file")
        elif quote not in source:
            failures.append(f"{where}.advisor.quote is not in the named advisor file")
        elif _http(advisor.get("url")) and advisor["url"].strip() != source[quote]:
            failures.append(f"{where}.advisor.url does not match its sourced words entry")
    if len(quotes) != len(set(quotes)):
        failures.append("recommendations reuse an advisor quote")
    questions = priority.get("questions", [])
    if not isinstance(questions, list) or any(blank(q) for q in questions):
        failures.append("priority.questions is not a list of non-blank strings")
    elif len(questions) > 3:
        failures.append("priority.questions has more than 3 items")
    else:
        failures += _page_rules(recommendations, questions)
    return failures


def _page_rules(recommendations, questions):
    own = [(f"questions[{i}]", q) for i, q in enumerate(questions)]
    for i, item in enumerate(recommendations):
        if isinstance(item, dict):
            own += [(f"recommendations[{i}].{k}", item[k]) for k in ("headline", "body", "first_step")
                    if isinstance(item.get(k), str)]
    failures = []
    for field, text in own:
        if match := FILE_RE.search(text):
            failures.append(f"{field} prints a file path or name ({match.group(0)!r})")
        if match := SELF_RE.search(text):
            failures.append(f"{field} calls the reader {match.group(0)!r}")
    return failures


def memo_problems(memo):
    if not isinstance(memo, dict):
        return ["memo.json is not a JSON object"]
    failures = []
    if not _real_date(memo.get("date")):
        failures.append("date is not a real YYYY-MM-DD date")
    if blank(memo.get("language")):
        failures.append("language is blank")
    run = memo.get("run")
    if not isinstance(run, dict):
        failures.append("run is not an object")
    else:
        usd = run.get("usd")
        if usd is not None and (isinstance(usd, bool) or not isinstance(usd, (int, float)) or usd < 0):
            failures.append("run.usd is not a non-negative number or null")
        minutes = run.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            failures.append("run.minutes is not a non-negative integer")
    has_card, reasons = "priority" in memo, memo.get("could_not_source")
    if has_card == (reasons is not None):
        failures.append("a memo is either a priority card or a could_not_source reason, exactly one")
    elif has_card:
        failures += card_problems(memo["priority"])
    elif not isinstance(reasons, list) or not reasons or any(blank(r) for r in reasons):
        failures.append("could_not_source is not a non-empty list of reasons")
    return failures


def checkpoint_problems(memo, tournament):
    """The card prints only as the accepted checkpoint it came from."""
    if not isinstance(tournament, dict):
        return ["tournament.json is not a JSON object"]
    failures = []
    if tournament.get("date") != memo.get("date"):
        failures.append("tournament date does not match the memo's date")
    generation = tournament.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 3:
        failures.append("tournament needs at least 3 completed generations")
    elif tournament.get("stage") != f"generation_{generation}_complete_gate_passed_checkpoint_written":
        failures.append("tournament is not at its completed gated checkpoint")
    champions = tournament.get("champions")
    ranked = sorted((c for c in champions if isinstance(c, dict)),
                    key=lambda c: c.get("rank") if isinstance(c.get("rank"), int) else 10**9) \
        if isinstance(champions, list) else []
    printed = [r.get("headline") for r in (memo.get("priority") or {}).get("recommendations") or []
               if isinstance(r, dict)]
    if len(printed) != 3 or [c.get("headline") for c in ranked] != printed:
        failures.append("tournament champions do not match the ranked recommendations")
    if tournament.get("priority") != memo.get("priority"):
        failures.append("tournament priority does not match the printed recommendations")
    return failures


def duration(minutes):
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest:02d}m" if hours else f"{rest}m"


def cost_line(run, language):
    if run.get("usd") is None:
        return phrase("page.cost_unknown", language, duration=duration(run["minutes"]))
    return phrase("page.cost", language, usd=f"{run['usd']:.2f}", duration=duration(run["minutes"]))


def _esc(text):
    return html.escape(" ".join(str(text).split()))


def _paragraphs(body):
    return "".join(f"<p>{_esc(p)}</p>" for p in re.split(r"\n\s*\n", body.strip()) if p.strip())


def priority_html(rank, item, language):
    advisor = item["advisor"]
    evidence = "".join(
        f'<li>{_esc(fact["claim"])} <span class="src">— '
        + (f'<a href="{_esc(fact["url"])}">{_esc(fact["source"])}</a>' if fact.get("url") else _esc(fact["source"]))
        + "</span></li>"
        for fact in item["evidence"]
    )
    return (
        f'<article class="priority"><p class="rank">{rank}</p>'
        f'<h2>{_esc(item["headline"])}</h2>{_paragraphs(item["body"])}'
        f'<ul class="evidence">{evidence}</ul>'
        f'<p class="first-step"><strong>{_esc(phrase("page.first_step", language))}:</strong> '
        f'{_esc(item["first_step"])}</p>'
        f'<blockquote>“{_esc(advisor["quote"])}” <span class="src">— '
        f'{_esc(phrase("page.advice_from", language))} '
        f'<a href="{_esc(advisor["url"])}">{_esc(advisor["name"])}</a></span></blockquote></article>'
    )


def render(memo, template_text=None):
    """The memo's HTML; CardError names every problem instead."""
    problems = memo_problems(memo)
    if problems:
        raise CardError("; ".join(problems))
    language = memo["language"]
    if status(language) != "ready":
        raise CardError("owner phrases need translation before rendering the memo")
    if "priority" in memo:
        priority = memo["priority"]
        body = "\n".join(priority_html(rank, item, language)
                         for rank, item in enumerate(priority["recommendations"], 1))
        if priority.get("questions"):
            items = "".join(f"<li>{_esc(q)}</li>" for q in priority["questions"])
            body += f'\n<section class="questions"><h3>{_esc(phrase("page.questions", language))}</h3><ul>{items}</ul></section>'
    else:
        items = "".join(f"<li>{_esc(r)}</li>" for r in memo["could_not_source"])
        body = (f'<section class="unavailable"><h3>{_esc(phrase("page.could_not_source", language))}</h3>'
                f"<ul>{items}</ul></section>")
    text = template_text if template_text is not None else TEMPLATE.read_text(encoding="utf-8")
    for slot, value in {
        "{{LANG}}": _esc(language), "{{MASTHEAD}}": _esc(MASTHEAD),
        "{{DATE}}": _esc(memo["date"]),
        "{{BAND}}": _esc(phrase("page.priority_band", language)),
        "{{BODY}}": body, "{{COST}}": _esc(cost_line(memo["run"], language)),
    }.items():
        text = text.replace(slot, value)
    return text


def write_pdf(html_text, path):
    """The PDF leg. weasyprint is in the image's venv; its absence is a named failure."""
    pathlib.Path(path).unlink(missing_ok=True)
    try:
        from weasyprint import HTML  # noqa: PLC0415 -- the image's dependency, not the tests'
    except ImportError:
        sys.exit("error: weasyprint is not installed; cannot write the memo's PDF")
    document = HTML(string=html_text).render()
    if len(document.pages) != 1:
        raise CardError("memo exceeds one Letter page; shorten the card before rendering")
    document.write_pdf(str(path))


def main(argv=None):
    p = argparse.ArgumentParser(prog="render_memo.py")
    p.add_argument("memo_json")
    p.add_argument("--tournament")
    p.add_argument("--pdf", required=True)
    p.add_argument("--html")
    a = p.parse_args(argv)
    pathlib.Path(a.pdf).unlink(missing_ok=True)
    try:
        memo = json.loads(pathlib.Path(a.memo_json).read_text(encoding="utf-8"))
        problems = memo_problems(memo)
        if not problems and isinstance(memo, dict) and "priority" in memo:
            if not a.tournament:
                problems = ["a priority card prints only with --tournament, its accepted checkpoint"]
            else:
                tournament = json.loads(pathlib.Path(a.tournament).read_text(encoding="utf-8"))
                problems = checkpoint_problems(memo, tournament)
        if problems:
            raise CardError("; ".join(problems))
        page = render(memo)
    except (OSError, ValueError) as exc:
        print(f"error: memo refused — {exc}", file=sys.stderr)
        return 1
    if a.html:
        pathlib.Path(a.html).write_text(page, encoding="utf-8")
    try:
        write_pdf(page, a.pdf)
    except (OSError, ValueError) as exc:
        print(f"error: memo refused — {exc}", file=sys.stderr)
        return 1
    print(f"RENDERED {a.pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
