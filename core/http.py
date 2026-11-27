"""Validated JSON HTTP client for Graph and SharePoint REST.

Guarantees:
- Only HTTPS URLs on allow-listed hosts (graph.microsoft.com, *.sharepoint.com).
- HTTP 401 -> one silent token renewal, then a single retry.
- HTTP 429 / 503 -> Retry-After-aware exponential backoff (rclone-style).
- Transient network errors -> bounded retries.
- ``pages()`` follows @odata.nextLink / d.__next transparently.
- Write verbs (POST / PATCH / DELETE) supported for the remediation layer.

Ported from the previous project's GovernanceHttpClient and extended with
throttling backoff and write-verb support.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator, Mapping

from core.auth import TokenSession

LOGGER = logging.getLogger("s3scope.http")

ALLOWED_HOST_SUFFIXES = ("graph.microsoft.com", ".sharepoint.com")
MAX_ATTEMPTS = 6
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 32.0
MAX_RETRY_AFTER_SECONDS = 120.0
MAX_PAGES = 1000


class RequestError(RuntimeError):
    """A request failed after all retries."""

    def __init__(self, status: int | None, url: str, body: str, note: str = "") -> None:
        self.status = status
        self.url = url
        self.body = body
        self.note = note
        label = f"HTTP {status}" if status is not None else "network error"
        detail = note or _excerpt(body, 200)
        super().__init__(f"{label} for {urllib.parse.urlsplit(url).path}: {detail}")


def _excerpt(text: Any, limit: int = 200) -> str:
    value = str(text or "")
    return value[:limit] + ("..." if len(value) > limit else "")


def backoff_delay(attempt: int, retry_after: str | None) -> float:
    """Backoff seconds for a throttled attempt (1-based); honors Retry-After."""
    if retry_after:
        stripped = str(retry_after).strip()
        if stripped.isdigit():
            return min(float(stripped), MAX_RETRY_AFTER_SECONDS)
    exponential = BASE_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))
    return min(exponential, MAX_BACKOFF_SECONDS)


def next_link(body: Any) -> str | None:
    """Extract the next-page link from Graph / SharePoint REST responses."""
    if not isinstance(body, Mapping):
        return None
    link = body.get("@odata.nextLink") or body.get("nextLink") or body.get("odata.nextLink")
    if isinstance(link, str) and link:
        return link
    nested = body.get("d")
    if isinstance(nested, Mapping):
        link = nested.get("__next")
        if isinstance(link, str) and link:
            return link
    return None


def _path_of(url: str) -> str:
    return urllib.parse.urlsplit(url).path


class ScHttpClient:
    """Minimal JSON client for Graph and SharePoint REST endpoints."""

    def __init__(self, session: TokenSession, *, timeout: int = 120) -> None:
        self.session = session
        self.timeout = timeout

    # -- public API --------------------------------------------------------------

    def get_json(self, url: str, *, accept: str | None = None) -> Any:
        return self.request("GET", url, accept=accept)

    def post_json(self, url: str, body: Any = None, *, accept: str | None = None) -> Any:
        return self.request("POST", url, json_body=body, accept=accept)

    def patch_json(self, url: str, body: Any, *, accept: str | None = None) -> Any:
        return self.request("PATCH", url, json_body=body, accept=accept)

    def delete(self, url: str, *, accept: str | None = None) -> Any:
        return self.request("DELETE", url, accept=accept)

    def pages(self, url: str, *, accept: str | None = None) -> Iterator[Any]:
        """Yield each page's parsed body, following Graph/SharePoint next links."""
        current: str | None = url
        for _ in range(MAX_PAGES):
            if current is None:
                return
            body = self.request("GET", current, accept=accept)
            yield body
            current = next_link(body)

    # -- core -----------------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        accept: str | None = None,
    ) -> Any:
        self._validate_url(url)
        accept = accept or self._default_accept(url)
        payload = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        renewed = False
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._send(method, url, payload, accept)
            except urllib.error.HTTPError as error:
                status = error.code
                body = self._read_error_body(error)
                if status in (429, 503) and attempt < MAX_ATTEMPTS:
                    headers = error.headers or {}
                    delay = backoff_delay(attempt, headers.get("Retry-After"))
                    LOGGER.warning(
                        "[HTTP] %s %s -> %s; throttled, retrying in %.1fs (attempt %d/%d)",
                        method, _path_of(url), status, delay, attempt, MAX_ATTEMPTS,
                    )
                    time.sleep(delay)
                    continue
                if status == 401 and not renewed:
                    renewed = True
                    LOGGER.info(
                        "[AUTH] HTTP 401 for %s; renewing token silently and retrying once.",
                        _path_of(url),
                    )
                    try:
                        self.session.refresh_for_url(url)
                    except Exception as renew_error:
                        raise RequestError(
                            status, url, body, f"token renewal failed: {renew_error}"
                        ) from renew_error
                    continue
                raise RequestError(status, url, body)
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < MAX_ATTEMPTS:
                    delay = backoff_delay(attempt, None)
                    LOGGER.warning(
                        "[HTTP] %s %s failed (%s); retrying in %.1fs (attempt %d/%d)",
                        method, _path_of(url), error, delay, attempt, MAX_ATTEMPTS,
                    )
                    time.sleep(delay)
                    continue
                raise RequestError(None, url, str(error))

    def _send(self, method: str, url: str, payload: bytes | None, accept: str) -> Any:
        request = urllib.request.Request(url, data=payload, method=method)
        request.add_header("Authorization", f"Bearer {self.session.get_token_for_url(url)}")
        request.add_header("Accept", accept)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else None

    def _default_accept(self, url: str) -> str:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host.endswith(".sharepoint.com"):
            return "application/json;odata=minimalmetadata"
        return "application/json"

    def _validate_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https":
            raise RequestError(None, url, "", f"only HTTPS is allowed: {parsed.scheme or 'none'}")
        host = (parsed.hostname or "").lower()
        if not any(
            host == suffix.lstrip(".") or host.endswith(suffix)
            for suffix in ALLOWED_HOST_SUFFIXES
        ):
            raise RequestError(None, url, "", f"host not allowed: {host}")

    def _read_error_body(self, error: urllib.error.HTTPError) -> str:
        try:
            return error.read().decode("utf-8", errors="replace")
        except Exception:
            return ""
