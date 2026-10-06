from collections.abc import Callable
from urllib.parse import urlsplit

from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import RequestException

from lulu_basket.errors import ScrapeError
from lulu_basket.scrape.parse import BASE_URL

HttpGet = Callable[[str], tuple[int, str]]

BACKOFF_SECONDS = (5, 15)
ATTEMPTS = len(BACKOFF_SECONDS) + 1
TIMEOUT_SECONDS = 30
_SITE = urlsplit(BASE_URL)


class TransportError(Exception):
    """The request did not complete (connection failure, timeout, ...)."""


def curl_http_get() -> HttpGet:
    session = curl_requests.Session(
        impersonate="chrome", timeout=TIMEOUT_SECONDS, allow_redirects=True, verify=True
    )

    def http_get(url: str) -> tuple[int, str]:
        try:
            response = session.get(url)
        except RequestException as exc:
            raise TransportError(str(exc)) from exc
        final = urlsplit(response.url)
        if final.scheme != _SITE.scheme or final.hostname != _SITE.hostname:
            raise ScrapeError(f"redirected off-site: {response.url}")
        return response.status_code, response.text

    return http_get


class Fetcher:
    def __init__(self, http_get: HttpGet, sleep: Callable[[float], None], delay: float):
        self._http_get = http_get
        self._sleep = sleep
        self._delay = delay
        self._requested = False

    def get(self, url: str) -> str:
        if self._requested:
            self._sleep(self._delay)
        self._requested = True
        for attempt in range(ATTEMPTS):
            if attempt:
                self._sleep(BACKOFF_SECONDS[attempt - 1])
            try:
                status, text = self._http_get(url)
            except TransportError as exc:
                blocked, failure = False, str(exc)
            else:
                if status == 200:
                    if not _is_access_denied(text):
                        return text
                    blocked, failure = True, "Access Denied"
                elif status in (403, 429) or 500 <= status < 600:
                    blocked, failure = status == 403, f"HTTP {status}"
                else:
                    raise ScrapeError(f"request failed: HTTP {status}: {url}")
        if blocked:
            raise ScrapeError(f"blocked by site after {ATTEMPTS} attempts: {url}")
        raise ScrapeError(f"request failed: {failure}: {url}")


def _is_access_denied(text: str) -> bool:
    return "Access Denied" in text and "__NEXT_DATA__" not in text
