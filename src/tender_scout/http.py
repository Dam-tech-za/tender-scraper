"""Shared HTTP client: polite delay between requests, retries with backoff, host allowlist.

Adapted from the HttpClient in Job Scout (tiaandelange/Career-Python-Scraper, MIT).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from tender_scout.config import get_settings

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def redact_url(url: str) -> str:
    """Drop the query string so keys or tokens never reach the logs."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class HttpClient:
    def __init__(
        self,
        *,
        allowed_hosts: set[str] | None = None,
        timeout: float = 60.0,
        retries: int = 2,
        backoff: float = 2.0,
        delay: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())}
        self.retries = retries
        self.backoff = backoff
        self.delay = delay
        self._owns = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": get_settings().user_agent, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"},
        )
        self._last = 0.0

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def _check_host(self, url: str) -> None:
        if not self.allowed_hosts:
            return
        host = (urlsplit(url).hostname or "").lower()
        if host not in self.allowed_hosts:
            raise ValueError(f"Host not allowlisted: {host or '<none>'}")

    def request(self, method: str, url: str, *, retries: int | None = None, **kwargs: Any) -> httpx.Response:
        self._check_host(url)
        retries = self.retries if retries is None else retries
        safe = redact_url(url)
        last: Exception | None = None
        for attempt in range(retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.client.request(method, url, **kwargs)
                self._last = time.monotonic()
                if response.status_code in RETRY_STATUS and attempt < retries:
                    logger.warning("%s %s -> %s, retrying", method, safe, response.status_code)
                    time.sleep(self.backoff * (2**attempt))
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                # 4xx other than 429 is a definite answer; retrying only burns time.
                if exc.response.status_code not in RETRY_STATUS:
                    raise
                last = exc
            except httpx.TransportError as exc:
                self._last = time.monotonic()
                last = exc
                logger.warning("%s %s failed (attempt %s): %s", method, safe, attempt + 1, type(exc).__name__)
                if attempt < retries:
                    time.sleep(self.backoff * (2**attempt))
        assert last is not None
        raise last

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs).json()
