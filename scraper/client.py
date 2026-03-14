"""Client for the official Czech e-Sbírka REST API.

Official API: https://api.e-sbirka.cz
Documentation: https://e-sbirka.gov.cz/restful-api
Authentication: register at the Ministry of Interior and obtain an API key,
then pass it via ESBIRKA_API_KEY environment variable or the ``api_key``
constructor argument.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Generator, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.e-sbirka.cz"

# Default number of laws to request per page
_DEFAULT_PAGE_SIZE = 100

# Seconds to wait between paginated requests to be a polite client
_INTER_REQUEST_DELAY = 0.3


def _build_session(api_key: Optional[str]) -> requests.Session:
    """Create a requests Session with retry logic and optional auth."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "zakonycr-scraper/1.0 (https://github.com/davidpilny/zakonycr)",
        }
    )
    if api_key:
        session.headers["esel-api-access-key"] = api_key
    return session


class ESbirkaClient:
    """Thin wrapper around the e-Sbírka REST API.

    Parameters
    ----------
    api_key:
        API key obtained from the Ministry of Interior registration process.
        Falls back to the ``ESBIRKA_API_KEY`` environment variable.
    base_url:
        Override the API base URL (useful for testing against a mock server).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = BASE_URL,
    ) -> None:
        resolved_key = api_key or os.environ.get("ESBIRKA_API_KEY")
        self.api_key = resolved_key
        self.base_url = base_url.rstrip("/")
        self._session = _build_session(resolved_key)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        """Perform a GET request and return the parsed JSON body."""
        url = f"{self.base_url}{path}"
        logger.debug("GET %s params=%s", url, params)
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _get_text(self, path: str) -> str:
        """Perform a GET request and return raw text."""
        url = f"{self.base_url}{path}"
        logger.debug("GET (text) %s", url)
        response = self._session.get(
            url,
            headers={"Accept": "text/plain"},
            timeout=60,
        )
        response.raise_for_status()
        return response.text

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def list_documents(
        self,
        page: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> dict:
        """Return one page of document summaries from the collection.

        The response contains a ``polozky`` list and paging metadata.
        """
        return self._get(
            "/dokumenty-sbirky",
            params={"stranka": page, "pocetNaStranku": page_size},
        )

    def get_document(self, year: int, number: int) -> dict:
        """Return full metadata for law *number/year*."""
        encoded = quote(f"/sb/{year}/{number}", safe="")
        return self._get(f"/dokumenty-sbirky/{encoded}")

    def get_document_text(self, year: int, number: int) -> str:
        """Return the plain-text full body of law *number/year*."""
        encoded = quote(f"/sb/{year}/{number}", safe="")
        return self._get_text(f"/dokumenty-sbirky/{encoded}/text")

    def list_changes(self, since: Optional[str] = None) -> list[dict]:
        """Return documents that changed after *since* (ISO-8601 datetime).

        If *since* is omitted all recent changes are returned.
        """
        params: dict[str, str] = {}
        if since:
            params["od"] = since
        data = self._get("/dokumenty-sbirky/zmeny", params=params or None)
        # The API may return a dict with a ``polozky`` key or a bare list
        if isinstance(data, list):
            return data
        return data.get("polozky", [])

    def iter_all_documents(self) -> Generator[dict, None, None]:
        """Yield every document summary in the collection, across all pages."""
        page = 1
        while True:
            data = self.list_documents(page=page)
            items: list[dict] = data.get("polozky", [])
            if not items:
                logger.debug("No more items at page %d, stopping.", page)
                break
            yield from items
            total_pages = data.get("celkemStranek", 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(_INTER_REQUEST_DELAY)
