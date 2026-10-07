#!/usr/bin/env python3
"""public_page.py -- the company's public site as plain text, for an event memo with no connections.

    public_page.py

Run bare: it takes NO arguments. The site is `company.website` from the install's
config.json (setup records it from the attendee), so nothing a fetched page says ever
reaches a shell. It reads the home page, then up to four of the same site's pages whose
address names what a memo needs (about, product, pricing, customers, blog/news), and
prints one block per page: `URL:`, `TITLE:`, then its visible text (at most 6,000
characters). Only a public http(s) address is fetched: a host that resolves to a
private, loopback or link-local address is refused, on every redirect too, because this
machine runs local services (the gateway, the wiki stand-in). At most 1 MB a page, 15 s.
Exit 1 prints `error: <why>` when no page could be read.
"""
from __future__ import annotations

import html
import json
import ipaddress
import re
import socket
import sys
import urllib.parse
import urllib.request

MAX_BYTES = 1_000_000
MAX_TEXT = 6_000
TIMEOUT = 15


def public_host(host: str) -> bool:
    """True when every address the host resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            return False
    return bool(infos)


def checked(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not a web address: {url}")
    if not public_host(parts.hostname):
        raise ValueError(f"not a public address: {parts.hostname}")
    return url


class _PublicOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked(newurl)  # a redirect may not hop to a private address either
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def page_text(raw: str, base: str) -> tuple[str, str, list[str]]:
    title = html.unescape(re.sub(r"\s+", " ", (re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I) or [None, ""])[1])).strip()
    host = urllib.parse.urlsplit(base).hostname or ""
    links = []
    for href in re.findall(r"<a\s[^>]*href=[\"']([^\"'#]+)", raw, re.I):
        absolute = urllib.parse.urljoin(base, html.unescape(href))
        if (urllib.parse.urlsplit(absolute).hostname or "").removeprefix("www.") == host.removeprefix("www.") and absolute not in links:
            links.append(absolute)
    body = re.sub(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    return title, text[:MAX_TEXT], links[:12]


def fetch(url: str) -> tuple[str, str]:
    opener = urllib.request.build_opener(_PublicOnly())
    request = urllib.request.Request(checked(url), headers={"User-Agent": "Mozilla/5.0 (compatible; FounderMemo/1.0)"})
    with opener.open(request, timeout=TIMEOUT) as response:
        raw = response.read(MAX_BYTES).decode(response.headers.get_content_charset() or "utf-8", "replace")
        return response.geturl(), raw


MEMO_WORDS = ("about", "product", "pricing", "customer", "blog", "news", "team", "company")


def company_site(config_path) -> str:
    try:
        company = json.loads(open(config_path, encoding="utf-8").read()).get("company") or {}
    except (OSError, ValueError):
        company = {}
    site = company.get("website") if isinstance(company, dict) else None
    if not isinstance(site, str) or not site.strip():
        raise ValueError("no company.website recorded")
    return site.strip()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print("usage: public_page.py   (no arguments: it reads company.website from config.json)", file=sys.stderr)
        return 2
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "memo-shared" / "scripts"))
    from pt_paths import config_file  # noqa: PLC0415
    try:
        final, raw = fetch(company_site(config_file()))
    except (ValueError, OSError) as exc:
        print(f"error: the company's site could not be read: {exc}")
        return 1
    title, text, links = page_text(raw, final)
    blocks = [f"URL: {final}\nTITLE: {title}\n\n{text}"]
    for link in [l for l in links if any(w in l.lower() for w in MEMO_WORDS)][:4]:
        try:
            url, raw = fetch(link)
        except (ValueError, OSError):
            continue
        title, text, _ = page_text(raw, url)
        blocks.append(f"URL: {url}\nTITLE: {title}\n\n{text}")
    print("\n\n---\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
