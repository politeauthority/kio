"""Tests for the URL safety / normalization helpers in kio_agent.cdp."""

import pytest

from kio_agent.cdp import _normalize_url, is_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com/path?q=1",
        "about:blank",
        "  HTTPS://EXAMPLE.COM  ",  # leading/trailing space + uppercase
        "HtTp://example.com",
    ],
)
def test_is_safe_url_accepts_allowed_schemes(url):
    assert is_safe_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>",
        "file:///etc/passwd",
        "chrome://settings",
        "ftp://example.com",
        "",
        "   ",
    ],
)
def test_is_safe_url_rejects_other_schemes(url):
    assert is_safe_url(url) is False


@pytest.mark.parametrize(
    "value",
    [None, 123, ["http://example.com"], {"url": "http://x"}],
)
def test_is_safe_url_rejects_non_strings(value):
    assert is_safe_url(value) is False


def test_normalize_url_drops_fragment():
    assert _normalize_url("http://x.com/page#section") == "http://x.com/page"


def test_normalize_url_drops_single_trailing_slash():
    assert _normalize_url("http://x.com/page/") == "http://x.com/page"


def test_normalize_url_keeps_query_string():
    assert _normalize_url("http://x.com/p?a=1") == "http://x.com/p?a=1"


def test_normalize_url_fragment_and_slash_together():
    # Fragment is stripped first; the resulting path has no trailing slash to drop.
    assert _normalize_url("http://x.com/p/#frag") == "http://x.com/p"


def test_normalize_url_handles_none():
    assert _normalize_url(None) == ""


def test_normalize_url_two_pages_match_after_normalization():
    assert _normalize_url("http://x.com/a/") == _normalize_url("http://x.com/a#top")
