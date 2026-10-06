from types import SimpleNamespace

import pytest
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import Timeout

from lulu_basket.errors import ScrapeError
from lulu_basket.scrape.fetch import Fetcher, TransportError, curl_http_get

URL = "https://shop.lululemon.com/c/women-clothes/n14uwk"
OTHER_URL = "https://shop.lululemon.com/p/define-jacket-nulu/hnsjuvo8dn"
DENIED = "<html><body>Access Denied</body></html>"
BAD_REQUEST = '{"message": "Bad Request.", "errorCode": "GE401001"}'
PAGE = '<html><script id="__NEXT_DATA__" type="application/json">{}</script></html>'


class FakeHttp:
    def __init__(self, *results):
        self.results = list(results)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class RecordingSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def make_fetcher(*results, delay=1.5):
    http = FakeHttp(*results)
    sleep = RecordingSleep()
    return Fetcher(http, sleep, delay), http, sleep


def test_first_request_has_no_delay_and_later_ones_sleep_delay():
    fetcher, http, sleep = make_fetcher((200, "a"), (200, "b"), (200, "c"))
    assert fetcher.get(URL) == "a"
    assert sleep.calls == []
    assert fetcher.get(OTHER_URL) == "b"
    assert sleep.calls == [1.5]
    assert fetcher.get(URL) == "c"
    assert sleep.calls == [1.5, 1.5]
    assert http.urls == [URL, OTHER_URL, URL]


def test_retry_waits_backoff_only_not_delay_in_addition():
    fetcher, _, sleep = make_fetcher((200, "a"), (403, DENIED), (200, "b"))
    fetcher.get(URL)
    fetcher.get(OTHER_URL)
    assert sleep.calls == [1.5, 5]


def test_403_three_times_is_blocked():
    fetcher, http, sleep = make_fetcher((403, DENIED), (403, DENIED), (403, DENIED))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"blocked by site after 3 attempts: {URL}"
    assert http.urls == [URL] * 3
    assert sleep.calls == [5, 15]


def test_access_denied_page_with_status_200_three_times_is_blocked():
    fetcher, http, sleep = make_fetcher((200, DENIED), (200, DENIED), (200, DENIED))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"blocked by site after 3 attempts: {URL}"
    assert len(http.urls) == 3
    assert sleep.calls == [5, 15]


def test_access_denied_text_with_next_data_is_a_normal_page():
    body = PAGE.replace("</html>", "Access Denied</html>")
    fetcher, http, sleep = make_fetcher((200, body))
    assert fetcher.get(URL) == body
    assert len(http.urls) == 1
    assert sleep.calls == []


def test_403_then_200_succeeds():
    fetcher, http, sleep = make_fetcher((403, DENIED), (200, PAGE))
    assert fetcher.get(URL) == PAGE
    assert len(http.urls) == 2
    assert sleep.calls == [5]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 599])
def test_retryable_statuses_are_retried(status):
    fetcher, http, sleep = make_fetcher((status, ""), (200, PAGE))
    assert fetcher.get(URL) == PAGE
    assert sleep.calls == [5]


def test_transport_error_three_times_reports_the_error():
    fetcher, http, sleep = make_fetcher(
        TransportError("boom"), TransportError("boom"), TransportError("boom")
    )
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"request failed: boom: {URL}"
    assert len(http.urls) == 3
    assert sleep.calls == [5, 15]


def test_transport_error_then_200_succeeds():
    fetcher, _, sleep = make_fetcher(TransportError("timed out"), (200, PAGE))
    assert fetcher.get(URL) == PAGE
    assert sleep.calls == [5]


def test_500_three_times_reports_the_status():
    fetcher, http, sleep = make_fetcher((500, ""), (500, ""), (500, ""))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"request failed: HTTP 500: {URL}"
    assert len(http.urls) == 3
    assert sleep.calls == [5, 15]


def test_404_fails_at_once_without_retry_sleeps():
    fetcher, http, sleep = make_fetcher((404, "not found"))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"request failed: HTTP 404: {URL}"
    assert len(http.urls) == 1
    assert sleep.calls == []


def test_400_bot_block_response_fails_at_once_without_retry_sleeps():
    fetcher, http, sleep = make_fetcher((400, BAD_REQUEST))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"request failed: HTTP 400: {URL}"
    assert len(http.urls) == 1
    assert sleep.calls == []


def test_blocked_message_follows_the_last_attempt():
    fetcher, _, _ = make_fetcher((403, DENIED), (403, DENIED), (500, ""))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"request failed: HTTP 500: {URL}"

    fetcher, _, _ = make_fetcher((500, ""), (500, ""), (403, DENIED))
    with pytest.raises(ScrapeError) as excinfo:
        fetcher.get(URL)
    assert str(excinfo.value) == f"blocked by site after 3 attempts: {URL}"


def test_scrape_error_from_http_get_is_not_retried():
    fetcher, http, sleep = make_fetcher(ScrapeError("redirected off-site: https://x.example/"))
    with pytest.raises(ScrapeError, match="redirected off-site"):
        fetcher.get(URL)
    assert len(http.urls) == 1
    assert sleep.calls == []


def patch_get(monkeypatch, handler):
    sessions = []

    def fake_get(self, url, **kwargs):
        sessions.append(self)
        return handler(url)

    monkeypatch.setattr(curl_requests.Session, "get", fake_get)
    return sessions


def response(final_url, status=200, text="body"):
    return SimpleNamespace(status_code=status, text=text, url=final_url)


def test_curl_http_get_returns_status_and_text(monkeypatch):
    patch_get(monkeypatch, lambda url: response(url, 200, "hello"))
    assert curl_http_get()(URL) == (200, "hello")


def test_curl_http_get_passes_non_200_status_through(monkeypatch):
    patch_get(monkeypatch, lambda url: response(url, 403, DENIED))
    assert curl_http_get()(URL) == (403, DENIED)


@pytest.mark.parametrize(
    "final_url",
    [
        "https://example.com/c/women-clothes",
        "http://shop.lululemon.com/c/women-clothes",
        "https://shop.lululemon.com.evil.example/c/women-clothes",
        "https://www.lululemon.com/c/women-clothes",
        "https://shop.lululemon.com@evil.example/c/women-clothes",
    ],
)
def test_curl_http_get_rejects_off_site_final_url(monkeypatch, final_url):
    patch_get(monkeypatch, lambda url: response(final_url))
    with pytest.raises(ScrapeError) as excinfo:
        curl_http_get()(URL)
    assert str(excinfo.value) == f"redirected off-site: {final_url}"


def test_curl_http_get_accepts_on_site_redirect(monkeypatch):
    final_url = "https://shop.lululemon.com/c/women-clothes/n14uwk?page=2"
    patch_get(monkeypatch, lambda url: response(final_url, 200, "moved"))
    assert curl_http_get()(URL) == (200, "moved")


def test_curl_http_get_maps_curl_errors_to_transport_error(monkeypatch):
    def handler(url):
        raise Timeout("Operation timed out")

    patch_get(monkeypatch, handler)
    with pytest.raises(TransportError, match="Operation timed out"):
        curl_http_get()(URL)


def test_curl_http_get_uses_one_configured_session_for_all_calls(monkeypatch):
    sessions = patch_get(monkeypatch, lambda url: response(url))
    http_get = curl_http_get()
    http_get(URL)
    http_get(OTHER_URL)
    assert sessions[0] is sessions[1]
    session = sessions[0]
    assert session.impersonate == "chrome"
    assert session.timeout == 30
    assert session.allow_redirects is True
    assert session.verify
