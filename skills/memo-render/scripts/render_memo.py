#!/usr/bin/env python3
"""render_memo.py -- the night's memo in, one printed page out.

    render_memo.py <edition.json> [--tournament <tournament.json>] --pdf OUT [--html OUT]

The model fills `edition.json`; this script -- fixed code over a fixed
`template.html` -- turns it into the printable HTML and the PDF. The model
never writes HTML. Every string is HTML-escaped here, once, in code: the
evidence came from the owner's mail and the web, and the page renders on the
owner's Mac.

edition.json is one of two shapes, both with
`"date": "YYYY-MM-DD"`, `"language": "<owner.language>"` and
`"run": {"usd": <float or null>, "minutes": <int>}`:

  * the night's ranked card: `"priority": {"recommendations": [3 items],
    "questions": [...]}`, the culler's card. The page and receipt print all three
    ranked recommendations with the questions and cost line. It prints only beside
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
import os
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "memo-shared" / "scripts"))
from owner_phrases import phrase, status  # noqa: E402

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "template.html"
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
        return ["edition.json is not a JSON object"]
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
    body = priorities_html(memo, language)
    text = template_text if template_text is not None else TEMPLATE.read_text(encoding="utf-8")
    for slot, value in {
        "{{LANG}}": _esc(language), "{{MASTHEAD}}": _esc(MASTHEAD),
        "{{DATE}}": _esc(memo["date"]),
        "{{BAND}}": _esc(phrase("page.priority_band", language)),
        "{{BODY}}": body, "{{COST}}": _esc(cost_line(memo["run"], language)),
    }.items():
        text = text.replace(slot, value)
    return text


def priorities_html(memo, language):
    """The three ranked recommendations and questions, or why the night has none."""
    if "priority" in memo:
        body = "\n".join(priority_html(rank, item, language)
                         for rank, item in enumerate(memo["priority"]["recommendations"], 1))
    else:
        items = "".join(f"<li>{_esc(r)}</li>" for r in memo["could_not_source"])
        body = (f'<section class="unavailable"><h3>{_esc(phrase("page.could_not_source", language))}</h3>'
                f"<ul>{items}</ul></section>")
    questions = memo.get("priority", {}).get("questions")
    if questions:
        items = "".join(f"<li>{_esc(q)}</li>" for q in questions)
        body += f'\n<section class="questions"><h3>{_esc(phrase("page.questions", language))}</h3><ul>{items}</ul></section>'
    return body

# A 72 mm thermal roll (printer.paper "72mm"; Star TSP100). The Letter page shrunk
# to 72 mm prints ~2.5 pt type, so the roll gets its own page with the same card.
# One tall page; the driver's variable-length mode cuts the paper after the ink.
# Set like a broadsheet front page for a 203 dpi black-only head: the fonts ship
# beside this script and embed in the PDF (the image has only DejaVu), every mark
# is solid black, and no rule is under 2 px (4 dots), so nothing dithers or drops out.
FONTS = pathlib.Path(__file__).resolve().parent.parent / "fonts"
RECEIPT_CSS = """
@font-face { font-family: "Memo Display"; font-weight: 900; src: url("{display}"); }
@font-face { font-family: "Memo Text"; font-weight: 400; src: url("{text}"); }
@font-face { font-family: "Memo Text"; font-weight: 400; font-style: italic; src: url("{italic}"); }
@font-face { font-family: "Memo Text"; font-weight: 700; src: url("{bold}"); }
@page { size: 72mm 2000mm; margin: 3mm 3mm 8mm; }
body { margin: 0; color: #000; font: 12.5px/1.42 "Memo Text", "DejaVu Serif", serif; overflow-wrap: break-word; }
a { color: #000; text-decoration: none; }
p { margin: 0 0 6px; }

.r-head { border-top: 5px solid #000; padding-top: 7px; text-align: center; }
.r-the { margin: 0; font: 700 10px/1 "Memo Text", serif; letter-spacing: 5px; text-transform: uppercase; }
.r-the::before, .r-the::after { content: ""; display: inline-block; width: 52px; margin: 0 6px 3px;
  border-top: 2px solid #000; vertical-align: middle; }
.r-masthead { margin: 3px 0 0; font: 900 47px/0.94 "Memo Display", serif; text-transform: uppercase; }
.r-masthead span { display: block; }
.r-rule { margin: 7px 0 0; border-top: 2px solid #000; border-bottom: 5px solid #000; height: 2px; }
.r-date { margin: 0; padding: 5px 0 6px; font: 700 11px/1 "Memo Text", serif; letter-spacing: 4px;
  border-bottom: 2px solid #000; }

.priority { margin-top: 30px; border-top: 3px solid #000; }
.priority .rank { width: 32px; height: 32px; margin: -19px auto 6px; border: 3px solid #fff;
  border-radius: 50%; background: #000; color: #fff; text-align: center;
  font: 900 21px/27px "Memo Display", serif; font-variant-numeric: lining-nums; }
.priority h2 { margin: 0 0 8px; font: 900 21px/1.1 "Memo Display", serif; text-align: center; }
.evidence { margin: 8px 0; padding: 0 0 0 9px; border-left: 2px solid #000; list-style: none;
  font-size: 10.5px; line-height: 1.35; }
.evidence li { margin-bottom: 3px; }
.src { font-style: italic; }
.first-step { margin: 10px 0; border: 3px solid #000; padding: 0 8px 7px; font-weight: 700; font-size: 13px;
  line-height: 1.35; }
.first-step strong { display: block; margin: 0 -8px 6px; padding: 4px 8px 5px; background: #000; color: #fff;
  font-size: 10px; letter-spacing: 3px; text-align: center; }
blockquote { margin: 10px 0 0; padding: 1px 0 1px 10px; border-left: 5px solid #000; font-style: italic; }
blockquote .src { display: block; margin-top: 4px; font: 700 9.5px/1.3 "Memo Text", serif;
  letter-spacing: 1px; text-transform: uppercase; }

.questions, .unavailable { margin-top: 28px; border: 3px solid #000; padding: 0 9px 4px; }
.questions h3, .unavailable h3 { margin: 0 -9px 8px; padding: 5px 6px 6px; background: #000; color: #fff;
  font: 700 9.5px/1.3 "Memo Text", serif; letter-spacing: 1px; text-align: center; text-transform: uppercase; }
.questions ul, .unavailable ul { margin: 0; padding: 0; list-style: none; }
.questions li, .unavailable li { padding: 0 0 6px; margin-bottom: 6px; border-bottom: 2px dotted #000;
  font-weight: 700; }
.questions li:last-child, .unavailable li:last-child { border-bottom: 0; margin-bottom: 0; }

footer { margin-top: 26px; padding-top: 7px; border-top: 5px solid #000; font: 700 9.5px/1.4 "Memo Text", serif;
  letter-spacing: 1.5px; text-align: center; text-transform: uppercase; }
footer::after { content: "\\25C6"; display: block; margin-top: 8px; font-size: 12px; }
"""


def receipt_html(memo):
    """The roll's page: the same card as the Letter page, at 72 mm, set as a broadsheet front page."""
    language = memo["language"]
    css = RECEIPT_CSS
    for slot, name in (("{display}", "PlayfairDisplay-Black"), ("{text}", "SourceSerif4-Regular"),
                       ("{italic}", "SourceSerif4-Italic"), ("{bold}", "SourceSerif4-Bold")):
        css = css.replace(slot, (FONTS / f"{name}.ttf").as_uri())
    the, _, title = MASTHEAD.partition(" ")
    lines = "".join(f"<span>{_esc(word)}</span>" for word in title.split())
    # The questions label is two phrases; at 72 mm it breaks at its middle dot, not mid-phrase.
    label = f'<h3>{_esc(phrase("page.questions", language))}</h3>'
    body = priorities_html(memo, language).replace(label, label.replace(" · ", "<br>", 1))
    return (f'<!doctype html><html lang="{_esc(language)}"><head><meta charset="utf-8">'
            f"<title>{_esc(MASTHEAD)} · {_esc(memo['date'])}</title><style>{css}</style></head><body>"
            f'<header class="r-head"><p class="r-the">{_esc(the)}</p><h1 class="r-masthead">{lines}</h1>'
            f'<div class="r-rule"></div><p class="r-date">{_esc(memo["date"])}</p></header>'
            f"{body}<footer>{_esc(cost_line(memo['run'], language))}</footer></body></html>")


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
                # An event install's card comes from one short read, not a tournament
                # (memo-tournament § Event): the image says so, never the card.
                if not os.environ.get("MEMO_EVENT"):
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
