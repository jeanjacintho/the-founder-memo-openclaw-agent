#!/usr/bin/env python3
"""public_page.py -- one public web page as plain text, for an event memo with no connections.

    public_page.py <http(s) URL>

Prints `URL: <final url>`, `TITLE: <title>`, then the page's visible text (at most
6,000 characters) and, under `LINKS:`, up to 12 links on the same site. Only a public
http(s) address is fetched: a host that resolves to a private, loopback or link-local
address is refused, because this machine runs local services (the gateway, the wiki
stand-in) that a page must never reach. At most 1 MB is read, 15 s timeout.
Exit 1 prints `error: <why>`.
"""
from __future__ import annotations

import html
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


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: public_page.py <http(s) URL>", file=sys.stderr)
        return 2
    try:
        final, raw = fetch(argv[0])
    except (ValueError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    title, text, links = page_text(raw, final)
    print(f"URL: {final}\nTITLE: {title}\n\n{text}\n\nLINKS:\n" + "\n".join(links))
    return 0


if __name__ == "__main__":
    sys.exit(main())
