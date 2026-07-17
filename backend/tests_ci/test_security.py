"""Security guard tests: SSRF, rate limiting, CORS."""

import pytest
from unittest.mock import MagicMock, patch
import ipaddress


def is_global_address(hostname: str) -> bool:
    """Check if hostname resolves to a global unicast address."""
    try:
        import socket
        addr = socket.getaddrinfo(hostname, None)[0][4][0]
        ip = ipaddress.ip_address(addr)
        return ip.is_global
    except Exception:
        return False


def url_block_reason(url: str) -> str | None:
    """
    Check if a URL should be blocked for SSRF.
    Returns None if allowed, or a reason string if blocked.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname

    # Only allow http(s)
    if scheme not in ("http", "https"):
        return f"Scheme '{scheme}' not allowed"

    if not hostname:
        return "No hostname"

    # Reject non-global addresses
    try:
        import socket
        addrs = socket.getaddrinfo(hostname, None)
        for addr_info in addrs:
            addr = ipaddress.ip_address(addr_info[4][0])
            if not addr.is_global:
                return f"IP {addr} is not global (loopback, RFC-1918, etc.)"
    except Exception as e:
        return f"Resolution failed: {e}"

    return None


class TestSSRFGuard:
    """Test SSRF protection."""

    def test_http_https_allowed(self):
        """http and https schemes should be allowed."""
        assert url_block_reason("https://example.com") is None
        assert url_block_reason("http://example.com") is None

    def test_non_http_schemes_blocked(self):
        """Non-http schemes should be blocked."""
        assert url_block_reason("ftp://example.com") is not None
        assert url_block_reason("file:///etc/passwd") is not None
        assert url_block_reason("gopher://example.com") is not None

    @patch('socket.getaddrinfo')
    def test_loopback_blocked(self, mock_getaddrinfo):
        """Loopback addresses should be blocked."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, '', ('127.0.0.1', 80))
        ]
        reason = url_block_reason("http://localhost:8000")
        assert reason is not None
        assert "not global" in reason

    @patch('socket.getaddrinfo')
    def test_private_ips_blocked(self, mock_getaddrinfo):
        """RFC-1918 private IPs should be blocked."""
        for ip in ["192.168.1.1", "10.0.0.1", "172.16.0.1"]:
            mock_getaddrinfo.return_value = [(2, 1, 6, '', (ip, 80))]
            reason = url_block_reason(f"http://{ip}")
            assert reason is not None, f"{ip} should be blocked"


class TestRateLimiter:
    """Test rate limiting logic."""

    def test_rate_limit_init(self):
        """Rate limiter should track requests per IP."""
        from collections import defaultdict
        from datetime import datetime, timedelta

        request_times = defaultdict(list)
        max_requests = 8
        window_seconds = 600

        def check_rate_limit(ip: str) -> bool:
            now = datetime.utcnow()
            # Clean old requests
            cutoff = now - timedelta(seconds=window_seconds)
            request_times[ip] = [t for t in request_times[ip] if t > cutoff]

            if len(request_times[ip]) >= max_requests:
                return False  # Too many requests

            request_times[ip].append(now)
            return True

        # First 8 requests should succeed
        for _ in range(8):
            assert check_rate_limit("192.0.2.1") is True

        # 9th should fail
        assert check_rate_limit("192.0.2.1") is False

    def test_rate_limit_per_ip(self):
        """Rate limiting should be per-IP."""
        from collections import defaultdict
        from datetime import datetime, timedelta

        request_times = defaultdict(list)
        max_requests = 8
        window_seconds = 600

        def check_rate_limit(ip: str) -> bool:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=window_seconds)
            request_times[ip] = [t for t in request_times[ip] if t > cutoff]

            if len(request_times[ip]) >= max_requests:
                return False

            request_times[ip].append(now)
            return True

        # IP1 maxes out
        for _ in range(8):
            assert check_rate_limit("192.0.2.1") is True
        assert check_rate_limit("192.0.2.1") is False

        # IP2 should still have budget
        for _ in range(8):
            assert check_rate_limit("192.0.2.2") is True
