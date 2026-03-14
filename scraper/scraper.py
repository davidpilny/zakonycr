"""Main scraper orchestration: fetch laws from e-Sbírka and store them.

Typical usage::

    from scraper import ESbirkaClient, LawStorage, Scraper

    client = ESbirkaClient()          # reads ESBIRKA_API_KEY from env
    storage = LawStorage("laws/")
    s = Scraper(client, storage)
    s.run()                           # full sync on first run, incremental after
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import requests

from .client import ESbirkaClient
from .storage import LawStorage

logger = logging.getLogger(__name__)

# Pause between individual law-text downloads (seconds)
_TEXT_FETCH_DELAY = 0.2


def _extract_year_number(doc: dict) -> Optional[tuple[int, int]]:
    """Parse year and number from an API document summary dict.

    The API returns documents with a ``cislo`` (number) and ``rok`` (year)
    field, or they may be embedded inside a ``oznaceni`` structure.  This
    function tries several common shapes so the scraper is resilient against
    minor API response format variations.
    """
    # Shape 1: flat {"cislo": 89, "rok": 2012, ...}
    if "cislo" in doc and "rok" in doc:
        try:
            return int(doc["rok"]), int(doc["cislo"])
        except (ValueError, TypeError):
            pass

    # Shape 2: {"oznaceni": {"cislo": 89, "rok": 2012}, ...}
    oznaceni = doc.get("oznaceni", {})
    if oznaceni:
        try:
            return int(oznaceni["rok"]), int(oznaceni["cislo"])
        except (KeyError, ValueError, TypeError):
            pass

    # Shape 3: path-style id, e.g. "/sb/2012/89"
    doc_id: str = doc.get("id", "") or doc.get("path", "")
    if doc_id:
        parts = doc_id.strip("/").split("/")
        if len(parts) >= 3:
            try:
                return int(parts[-2]), int(parts[-1])
            except ValueError:
                pass

    return None


def _build_metadata(doc: dict) -> dict:
    """Extract storage-relevant metadata from an API document summary."""
    meta: dict = {}

    def _pick(*keys: str) -> Optional[object]:
        for k in keys:
            v = doc.get(k)
            if v is not None:
                return v
        return None

    nazev = _pick("nazev", "nadpis", "title")
    if not nazev:
        oznaceni = doc.get("oznaceni", {})
        nazev = oznaceni.get("nazev") if oznaceni else None
    if nazev:
        meta["nazev"] = nazev

    castka = _pick("castka", "cisloCastky")
    if castka is not None:
        meta["castka"] = castka

    datum = _pick("datumUcinnosti", "ucinnostOd", "platnostOd")
    if datum:
        meta["datum_ucinnosti"] = datum

    url = _pick("url", "uri", "permalink")
    if url:
        meta["url"] = url

    return meta


class Scraper:
    """Orchestrates fetching and storing Czech laws.

    Parameters
    ----------
    client:
        :class:`ESbirkaClient` instance (authenticated or not).
    storage:
        :class:`LawStorage` instance pointing at the target directory.
    force_full:
        When *True*, ignore the stored last-sync timestamp and re-fetch
        every law.
    on_progress:
        Optional callback ``(done: int, total: Optional[int]) -> None``
        called after each law is processed; useful for progress reporting.
    """

    def __init__(
        self,
        client: ESbirkaClient,
        storage: LawStorage,
        force_full: bool = False,
        on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> None:
        self.client = client
        self.storage = storage
        self.force_full = force_full
        self.on_progress = on_progress

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """Run a full or incremental sync, return a stats dict."""
        last_sync = None if self.force_full else self.storage.get_last_sync()

        if last_sync:
            logger.info("Running incremental sync (changed since %s).", last_sync)
            return self._incremental_sync(last_sync)
        else:
            logger.info("Running full sync.")
            return self._full_sync()

    # ------------------------------------------------------------------
    # Sync strategies
    # ------------------------------------------------------------------

    def _full_sync(self) -> dict:
        """Fetch every document and store its text."""
        saved = 0
        failed = 0
        skipped = 0
        docs = list(self.client.iter_all_documents())
        total = len(docs)
        logger.info("Full sync: %d documents to process.", total)

        for i, doc in enumerate(docs, start=1):
            yr_no = _extract_year_number(doc)
            if yr_no is None:
                logger.warning("Could not parse year/number from doc: %s", doc)
                failed += 1
                continue
            year, number = yr_no
            outcome = self._fetch_and_save(year, number, doc)
            if outcome == "saved":
                saved += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
            if self.on_progress:
                self.on_progress(i, total)
            time.sleep(_TEXT_FETCH_DELAY)

        self.storage.set_last_sync()
        result = {"saved": saved, "skipped": skipped, "failed": failed, "total": total}
        logger.info("Full sync complete: %s", result)
        return result

    def _incremental_sync(self, since: str) -> dict:
        """Fetch only laws that changed since *since*."""
        saved = 0
        failed = 0
        changes = self.client.list_changes(since=since)
        total = len(changes)
        logger.info("Incremental sync: %d changed documents.", total)

        for i, doc in enumerate(changes, start=1):
            yr_no = _extract_year_number(doc)
            if yr_no is None:
                logger.warning("Could not parse year/number from change: %s", doc)
                failed += 1
                continue
            year, number = yr_no
            outcome = self._fetch_and_save(year, number, doc)
            if outcome == "saved":
                saved += 1
            else:
                failed += 1
            if self.on_progress:
                self.on_progress(i, total)
            time.sleep(_TEXT_FETCH_DELAY)

        self.storage.set_last_sync()
        result = {"saved": saved, "failed": failed, "total": total}
        logger.info("Incremental sync complete: %s", result)
        return result

    # ------------------------------------------------------------------
    # Per-law helper
    # ------------------------------------------------------------------

    def _fetch_and_save(
        self,
        year: int,
        number: int,
        summary: dict,
    ) -> str:
        """Fetch full text of one law and persist it.  Returns outcome string."""
        try:
            # Prefer to get the most up-to-date metadata from the detail endpoint
            try:
                detail = self.client.get_document(year, number)
            except requests.RequestException:
                detail = summary

            metadata = _build_metadata(detail)

            text = self.client.get_document_text(year, number)
            self.storage.save_law(year, number, metadata, text)
            logger.debug("Saved %d/%d", number, year)
            return "saved"
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.error("Failed to fetch/save %d/%d: %s", number, year, exc)
            return "failed"
