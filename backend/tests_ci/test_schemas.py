"""Request-schema validators: the page cap (kept in sync with the Modal
timeout), version/test validation, and URL normalization."""

import pytest
from pydantic import ValidationError

from app.schemas import CrawlRequest, ALL_TESTS


def test_page_cap_is_15():
    # Cap must match modal_app.py's 1800s timeout budget (15 * ~90s).
    assert CrawlRequest(url="http://x", max_pages=30).max_pages == 15
    assert CrawlRequest(url="http://x", max_pages=15).max_pages == 15
    assert CrawlRequest(url="http://x", max_pages=8).max_pages == 8
    assert CrawlRequest(url="http://x", max_pages=0).max_pages == 1  # floor
    assert CrawlRequest(url="http://x").max_pages == 15               # default


def test_depth_cap():
    assert CrawlRequest(url="http://x", max_depth=99).max_depth == 5
    assert CrawlRequest(url="http://x", max_depth=0).max_depth == 0   # single-page


def test_url_normalization_adds_scheme():
    assert CrawlRequest(url="example.com").url == "https://example.com"
    assert CrawlRequest(url="http://example.com").url == "http://example.com"
    assert CrawlRequest(url="https://example.com").url == "https://example.com"


def test_wcag_version_falls_back_to_22():
    assert CrawlRequest(url="http://x", wcag_version="2.1").wcag_version == "2.1"
    assert CrawlRequest(url="http://x", wcag_version="9.9").wcag_version == "2.2"


def test_unknown_test_rejected():
    with pytest.raises(ValidationError):
        CrawlRequest(url="http://x", tests=["not_a_real_test"])


def test_empty_tests_defaults_to_all():
    assert CrawlRequest(url="http://x", tests=[]).tests == ALL_TESTS
