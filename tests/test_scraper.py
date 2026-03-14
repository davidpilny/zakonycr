"""Unit tests for the Scraper orchestration class."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from scraper.scraper import Scraper, _build_metadata, _extract_year_number
from scraper.client import ESbirkaClient
from scraper.storage import LawStorage


# ---------------------------------------------------------------------------
# _extract_year_number
# ---------------------------------------------------------------------------

class TestExtractYearNumber:
    def test_flat_dict(self):
        doc = {"cislo": 89, "rok": 2012}
        assert _extract_year_number(doc) == (2012, 89)

    def test_flat_dict_string_values(self):
        doc = {"cislo": "89", "rok": "2012"}
        assert _extract_year_number(doc) == (2012, 89)

    def test_oznaceni_nested(self):
        doc = {"oznaceni": {"cislo": 10, "rok": 1999}}
        assert _extract_year_number(doc) == (1999, 10)

    def test_path_style_id(self):
        doc = {"id": "/sb/2020/150"}
        assert _extract_year_number(doc) == (2020, 150)

    def test_path_style_path_key(self):
        doc = {"path": "/sb/1964/40"}
        assert _extract_year_number(doc) == (1964, 40)

    def test_returns_none_for_empty_dict(self):
        assert _extract_year_number({}) is None

    def test_returns_none_for_unparseable(self):
        doc = {"foo": "bar"}
        assert _extract_year_number(doc) is None


# ---------------------------------------------------------------------------
# _build_metadata
# ---------------------------------------------------------------------------

class TestBuildMetadata:
    def test_extracts_nazev(self):
        doc = {"nazev": "Občanský zákoník", "cislo": 89, "rok": 2012}
        meta = _build_metadata(doc)
        assert meta["nazev"] == "Občanský zákoník"

    def test_extracts_url(self):
        doc = {"url": "https://api.e-sbirka.cz/sb/2012/89"}
        meta = _build_metadata(doc)
        assert meta["url"] == "https://api.e-sbirka.cz/sb/2012/89"

    def test_extracts_datum_ucinnosti(self):
        doc = {"datumUcinnosti": "2014-01-01"}
        meta = _build_metadata(doc)
        assert meta["datum_ucinnosti"] == "2014-01-01"

    def test_empty_doc_returns_empty_meta(self):
        assert _build_metadata({}) == {}

    def test_nazev_fallback_to_nadpis(self):
        doc = {"nadpis": "Zákon o XYZ"}
        meta = _build_metadata(doc)
        assert meta["nazev"] == "Zákon o XYZ"

    def test_nazev_fallback_to_oznaceni(self):
        doc = {"oznaceni": {"nazev": "Zákon ze zákonů"}}
        meta = _build_metadata(doc)
        assert meta["nazev"] == "Zákon ze zákonů"

    def test_missing_optional_fields_not_in_result(self):
        doc = {"cislo": 1, "rok": 2000}
        meta = _build_metadata(doc)
        assert "castka" not in meta
        assert "url" not in meta


# ---------------------------------------------------------------------------
# Scraper.run  (full sync)
# ---------------------------------------------------------------------------

def _make_client(docs: list[dict], text: str = "Full text") -> ESbirkaClient:
    """Return a mock ESbirkaClient that yields the given docs."""
    client = MagicMock(spec=ESbirkaClient)
    client.iter_all_documents.return_value = iter(docs)
    client.get_document.side_effect = lambda year, num: {"cislo": num, "rok": year}
    client.get_document_text.return_value = text
    client.list_changes.return_value = []
    return client


class TestScraperFullSync:
    def test_saves_all_documents(self, tmp_path):
        docs = [{"cislo": i, "rok": 2020} for i in range(1, 4)]
        client = _make_client(docs)
        storage = LawStorage(tmp_path)

        with patch("scraper.scraper.time.sleep"):
            result = Scraper(client, storage, force_full=True).run()

        assert result["saved"] == 3
        assert result["failed"] == 0
        assert storage.count_laws() == 3

    def test_sets_last_sync_after_run(self, tmp_path):
        client = _make_client([{"cislo": 1, "rok": 2020}])
        storage = LawStorage(tmp_path)

        with patch("scraper.scraper.time.sleep"):
            Scraper(client, storage, force_full=True).run()

        assert storage.get_last_sync() is not None

    def test_skips_unparseable_docs(self, tmp_path):
        docs = [{"foo": "bar"}, {"cislo": 1, "rok": 2020}]
        client = _make_client(docs)
        storage = LawStorage(tmp_path)

        with patch("scraper.scraper.time.sleep"):
            result = Scraper(client, storage, force_full=True).run()

        assert result["failed"] == 1
        assert result["saved"] == 1

    def test_records_failed_when_text_fetch_errors(self, tmp_path):
        docs = [{"cislo": 1, "rok": 2020}]
        client = _make_client(docs)
        client.get_document_text.side_effect = requests.RequestException("API unavailable")
        storage = LawStorage(tmp_path)

        with patch("scraper.scraper.time.sleep"):
            result = Scraper(client, storage, force_full=True).run()

        assert result["failed"] == 1
        assert result["saved"] == 0

    def test_calls_on_progress(self, tmp_path):
        docs = [{"cislo": i, "rok": 2020} for i in range(1, 4)]
        client = _make_client(docs)
        storage = LawStorage(tmp_path)
        progress_calls = []

        with patch("scraper.scraper.time.sleep"):
            Scraper(
                client, storage, force_full=True,
                on_progress=lambda d, t: progress_calls.append((d, t)),
            ).run()

        assert len(progress_calls) == 3
        assert progress_calls[-1][0] == 3


# ---------------------------------------------------------------------------
# Scraper.run  (incremental sync)
# ---------------------------------------------------------------------------

class TestScraperIncrementalSync:
    def test_uses_list_changes_when_last_sync_set(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.set_last_sync("2024-01-01T00:00:00Z")

        client = _make_client([])
        client.list_changes.return_value = [{"cislo": 42, "rok": 2024}]
        client.get_document.return_value = {"cislo": 42, "rok": 2024}
        client.get_document_text.return_value = "text"

        with patch("scraper.scraper.time.sleep"):
            result = Scraper(client, storage, force_full=False).run()

        client.iter_all_documents.assert_not_called()
        client.list_changes.assert_called_once()
        assert result["saved"] == 1

    def test_force_full_ignores_last_sync(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.set_last_sync("2024-01-01T00:00:00Z")

        docs = [{"cislo": 1, "rok": 2024}]
        client = _make_client(docs)

        with patch("scraper.scraper.time.sleep"):
            Scraper(client, storage, force_full=True).run()

        client.iter_all_documents.assert_called()
        client.list_changes.assert_not_called()
