"""Unit tests for the ESbirkaClient."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper.client import ESbirkaClient, _build_session, BASE_URL


# ---------------------------------------------------------------------------
# _build_session
# ---------------------------------------------------------------------------

class TestBuildSession:
    def test_sets_accept_header(self):
        session = _build_session(None)
        assert session.headers["Accept"] == "application/json"

    def test_sets_user_agent(self):
        session = _build_session(None)
        assert "zakonycr-scraper" in session.headers["User-Agent"]

    def test_sets_api_key_when_provided(self):
        session = _build_session("my-test-key")
        assert session.headers["esel-api-access-key"] == "my-test-key"

    def test_no_api_key_header_when_omitted(self):
        session = _build_session(None)
        assert "esel-api-access-key" not in session.headers


# ---------------------------------------------------------------------------
# ESbirkaClient construction
# ---------------------------------------------------------------------------

class TestESbirkaClientConstruction:
    def test_uses_provided_api_key(self):
        client = ESbirkaClient(api_key="explicit-key")
        assert client.api_key == "explicit-key"

    def test_reads_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ESBIRKA_API_KEY", "env-key")
        client = ESbirkaClient()
        assert client.api_key == "env-key"

    def test_api_key_is_none_when_not_set(self, monkeypatch):
        monkeypatch.delenv("ESBIRKA_API_KEY", raising=False)
        client = ESbirkaClient()
        assert client.api_key is None

    def test_custom_base_url(self):
        client = ESbirkaClient(base_url="http://localhost:8080")
        assert client.base_url == "http://localhost:8080"

    def test_base_url_trailing_slash_stripped(self):
        client = ESbirkaClient(base_url="http://localhost/")
        assert client.base_url == "http://localhost"

    def test_logs_warning_when_no_api_key(self, monkeypatch, caplog):
        import logging
        monkeypatch.delenv("ESBIRKA_API_KEY", raising=False)
        with caplog.at_level(logging.WARNING, logger="scraper.client"):
            ESbirkaClient()
        assert any("No API key" in r.message for r in caplog.records)

    def test_no_warning_when_api_key_provided(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="scraper.client"):
            ESbirkaClient(api_key="some-key")
        assert not any("No API key" in r.message for r in caplog.records)


def _mock_response(data: object, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.text = json.dumps(data) if not isinstance(data, str) else data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_text_response(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# ESbirkaClient.list_documents
# ---------------------------------------------------------------------------

class TestListDocuments:
    def test_calls_correct_endpoint(self, monkeypatch):
        client = ESbirkaClient(api_key="k")
        mock_get = MagicMock(return_value=_mock_response({"polozky": [], "celkemStranek": 1}))
        monkeypatch.setattr(client._session, "get", mock_get)

        client.list_documents(page=2, page_size=50)

        url, = [call.args[0] for call in mock_get.call_args_list]
        assert url == f"{BASE_URL}/dokumenty-sbirky"
        params = mock_get.call_args.kwargs["params"]
        assert params["stranka"] == 2
        assert params["pocetNaStranku"] == 50

    def test_returns_response_json(self, monkeypatch):
        payload = {"polozky": [{"cislo": 1, "rok": 2020}], "celkemStranek": 1}
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(client._session, "get", MagicMock(return_value=_mock_response(payload)))

        result = client.list_documents()
        assert result == payload


# ---------------------------------------------------------------------------
# ESbirkaClient.get_document
# ---------------------------------------------------------------------------

class TestGetDocument:
    def test_url_encodes_path(self, monkeypatch):
        client = ESbirkaClient(api_key="k")
        mock_get = MagicMock(return_value=_mock_response({"cislo": 89, "rok": 2012}))
        monkeypatch.setattr(client._session, "get", mock_get)

        client.get_document(2012, 89)

        url = mock_get.call_args.args[0]
        # The path /sb/2012/89 must appear URL-encoded in the URL
        assert "%2Fsb%2F2012%2F89" in url or "/sb/2012/89" in url

    def test_returns_document(self, monkeypatch):
        doc = {"cislo": 89, "rok": 2012, "nazev": "Občanský zákoník"}
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(client._session, "get", MagicMock(return_value=_mock_response(doc)))

        result = client.get_document(2012, 89)
        assert result == doc


# ---------------------------------------------------------------------------
# ESbirkaClient.get_document_text
# ---------------------------------------------------------------------------

class TestGetDocumentText:
    def test_returns_text(self, monkeypatch):
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(
            client._session,
            "get",
            MagicMock(return_value=_mock_text_response("Plný text zákona...")),
        )

        result = client.get_document_text(2012, 89)
        assert result == "Plný text zákona..."


# ---------------------------------------------------------------------------
# ESbirkaClient.list_changes
# ---------------------------------------------------------------------------

class TestListChanges:
    def test_returns_list_when_api_returns_list(self, monkeypatch):
        payload = [{"cislo": 1, "rok": 2024}]
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(client._session, "get", MagicMock(return_value=_mock_response(payload)))

        result = client.list_changes()
        assert result == payload

    def test_returns_polozky_when_api_returns_dict(self, monkeypatch):
        items = [{"cislo": 1, "rok": 2024}]
        payload = {"polozky": items, "celkemStranek": 1}
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(client._session, "get", MagicMock(return_value=_mock_response(payload)))

        result = client.list_changes()
        assert result == items

    def test_passes_since_parameter(self, monkeypatch):
        client = ESbirkaClient(api_key="k")
        mock_get = MagicMock(return_value=_mock_response([]))
        monkeypatch.setattr(client._session, "get", mock_get)

        client.list_changes(since="2024-01-01T00:00:00Z")

        params = mock_get.call_args.kwargs.get("params") or mock_get.call_args.args[1] if len(mock_get.call_args.args) > 1 else {}
        # Params may be passed as keyword arg
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("params", {}).get("od") == "2024-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# ESbirkaClient.iter_all_documents
# ---------------------------------------------------------------------------

class TestIterAllDocuments:
    def test_yields_all_items_single_page(self, monkeypatch):
        items = [{"cislo": i, "rok": 2020} for i in range(1, 4)]
        payload = {"polozky": items, "celkemStranek": 1}
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(
            client._session,
            "get",
            MagicMock(return_value=_mock_response(payload)),
        )

        result = list(client.iter_all_documents())
        assert result == items

    def test_yields_all_items_multiple_pages(self, monkeypatch):
        page1 = {"polozky": [{"cislo": 1, "rok": 2020}], "celkemStranek": 2}
        page2 = {"polozky": [{"cislo": 2, "rok": 2020}], "celkemStranek": 2}
        client = ESbirkaClient(api_key="k")
        mock_get = MagicMock(
            side_effect=[
                _mock_response(page1),
                _mock_response(page2),
            ]
        )
        monkeypatch.setattr(client._session, "get", mock_get)

        with patch("scraper.client.time.sleep"):  # skip sleep in tests
            result = list(client.iter_all_documents())

        assert len(result) == 2
        assert result[0]["cislo"] == 1
        assert result[1]["cislo"] == 2

    def test_stops_on_empty_page(self, monkeypatch):
        payload = {"polozky": [], "celkemStranek": 1}
        client = ESbirkaClient(api_key="k")
        monkeypatch.setattr(
            client._session,
            "get",
            MagicMock(return_value=_mock_response(payload)),
        )

        result = list(client.iter_all_documents())
        assert result == []

    def test_raises_on_http_error(self, monkeypatch):
        client = ESbirkaClient(api_key="k")
        resp = _mock_response({}, status=500)
        resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        monkeypatch.setattr(client._session, "get", MagicMock(return_value=resp))

        with pytest.raises(requests.HTTPError):
            list(client.iter_all_documents())
