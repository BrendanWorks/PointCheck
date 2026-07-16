"""
URL safety guard — refuses crawl targets that resolve to private, loopback,
link-local, or otherwise non-public addresses (SSRF defense).

Checked once at job creation. Discovered links during a crawl are already
restricted to the same origin as the start URL, so validating the start URL
covers the whole BFS frontier.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def url_block_reason(url: str) -> str | None:
    """
    Return a human-readable reason this URL must not be crawled,
    or None if the URL looks like a legitimate public web target.

    Blocking rules:
      - scheme must be http or https
      - hostname must be present and resolve via DNS
      - every resolved address must be globally routable — rejects loopback,
        RFC-1918 private ranges, link-local / cloud-metadata 169.254.0.0/16,
        CGNAT 100.64.0.0/10, and reserved ranges, for both IPv4 and IPv6.

    Note: addresses are checked at job-creation time. This is an anti-abuse
    guard, not a complete defense against DNS-rebinding attacks.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "URL could not be parsed"

    if parsed.scheme not in ("http", "https"):
        return f"unsupported URL scheme {parsed.scheme!r}"

    host = parsed.hostname
    if not host:
        return "URL has no hostname"

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"hostname {host!r} does not resolve"
    except Exception:
        return f"hostname {host!r} could not be checked"

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not addr.is_global:
            return (
                f"{host} resolves to a non-public address ({addr}) — "
                "scanning internal or private hosts is not allowed"
            )

    return None
