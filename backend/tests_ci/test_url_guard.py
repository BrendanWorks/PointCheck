"""SSRF guard — the security-critical check that crawl targets can't point at
internal/private hosts. Regressing this silently re-opens the SSRF hole, so
these assertions are the whole point of having CI."""

import pytest

from app.url_guard import url_block_reason


@pytest.mark.parametrize("url", [
    "https://pointcheck.org",
    "https://alphagov.github.io/accessibility-tool-audit/test-cases.html",
    "https://example.com/path?q=1",
])
def test_public_urls_allowed(url):
    assert url_block_reason(url) is None


@pytest.mark.parametrize("url", [
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:5000/admin",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://10.0.0.5",                              # RFC-1918
    "http://192.168.1.1",
    "http://172.16.0.1",
    "http://100.64.0.1",                            # CGNAT
    "http://[::1]:8080",                            # IPv6 loopback
])
def test_internal_addresses_blocked(url):
    assert url_block_reason(url) is not None


@pytest.mark.parametrize("url", [
    "ftp://example.com",
    "file:///etc/passwd",
    "gopher://example.com",
])
def test_non_http_schemes_blocked(url):
    assert url_block_reason(url) is not None


def test_unresolvable_host_blocked():
    assert url_block_reason("https://no-such-host-4a9f2b1c.example") is not None


def test_missing_hostname_blocked():
    assert url_block_reason("http://") is not None
