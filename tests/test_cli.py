"""Unit tests for the CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper.cli import build_parser, main


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_sync_command_exists(self):
        parser = build_parser()
        args = parser.parse_args(["sync"])
        assert args.command == "sync"

    def test_sync_defaults(self):
        args = build_parser().parse_args(["sync"])
        assert args.incremental is False
        assert args.force is False

    def test_sync_incremental_flag(self):
        args = build_parser().parse_args(["sync", "--incremental"])
        assert args.incremental is True

    def test_sync_force_flag(self):
        args = build_parser().parse_args(["sync", "--force"])
        assert args.force is True

    def test_fetch_command(self):
        args = build_parser().parse_args(["fetch", "89", "2012"])
        assert args.command == "fetch"
        assert args.number == 89
        assert args.year == 2012

    def test_stats_command(self):
        args = build_parser().parse_args(["stats"])
        assert args.command == "stats"

    def test_verbose_flag(self):
        args = build_parser().parse_args(["-v", "stats"])
        assert args.verbose is True

    def test_api_key_flag_exists(self):
        args = build_parser().parse_args(["--api-key", "my-key", "stats"])
        assert args.api_key == "my-key"

    def test_api_key_defaults_to_none(self):
        args = build_parser().parse_args(["stats"])
        assert args.api_key is None



class TestMain:
    def test_stats_command_runs(self, tmp_path, capsys):
        with patch("scraper.cli._laws_dir", return_value=str(tmp_path)):
            rc = main(["stats"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Total laws stored" in out

    def test_stats_shows_last_sync_never(self, tmp_path, capsys):
        with patch("scraper.cli._laws_dir", return_value=str(tmp_path)):
            main(["stats"])
        out = capsys.readouterr().out
        assert "never" in out

    def test_stats_shows_count_after_laws_stored(self, tmp_path, capsys):
        from scraper.storage import LawStorage
        storage = LawStorage(tmp_path)
        storage.save_law(2020, 1, {}, "body")
        storage.save_law(2020, 2, {}, "body")
        with patch("scraper.cli._laws_dir", return_value=str(tmp_path)):
            main(["stats"])
        out = capsys.readouterr().out
        assert "2" in out

    def test_sync_runs_scraper(self, tmp_path):
        fake_result = {"saved": 5, "skipped": 0, "failed": 0, "total": 5}
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient"),
            patch("scraper.cli.Scraper") as MockScraper,
        ):
            instance = MagicMock()
            instance.run.return_value = fake_result
            MockScraper.return_value = instance
            rc = main(["sync"])
        assert rc == 0

    def test_sync_returns_nonzero_on_failures(self, tmp_path):
        fake_result = {"saved": 3, "skipped": 0, "failed": 2, "total": 5}
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient"),
            patch("scraper.cli.Scraper") as MockScraper,
        ):
            instance = MagicMock()
            instance.run.return_value = fake_result
            MockScraper.return_value = instance
            rc = main(["sync"])
        assert rc == 1

    def test_fetch_saves_law(self, tmp_path):
        doc_meta = {"cislo": 89, "rok": 2012, "nazev": "Zákon"}
        doc_text = "Plný text zákona"
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient") as MockClient,
        ):
            inst = MagicMock()
            inst.get_document.return_value = doc_meta
            inst.get_document_text.return_value = doc_text
            MockClient.return_value = inst
            rc = main(["fetch", "89", "2012"])
        assert rc == 0
        from scraper.storage import LawStorage
        assert LawStorage(tmp_path).exists(2012, 89)

    def test_no_api_key_prints_warning(self, tmp_path, monkeypatch, capsys):
        """When no key is set, sync should print a clear warning to stderr."""
        monkeypatch.delenv("ESBIRKA_API_KEY", raising=False)
        fake_result = {"saved": 0, "skipped": 0, "failed": 0, "total": 0}
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient") as MockClient,
            patch("scraper.cli.Scraper") as MockScraper,
        ):
            inst_client = MagicMock()
            inst_client.api_key = None  # no key
            MockClient.return_value = inst_client
            inst_scraper = MagicMock()
            inst_scraper.run.return_value = fake_result
            MockScraper.return_value = inst_scraper
            main(["sync"])
        err = capsys.readouterr().err
        assert "No API key" in err
        assert "ESBIRKA_API_KEY" in err

    def test_api_key_flag_passed_to_client(self, tmp_path):
        """--api-key value must be forwarded to ESbirkaClient."""
        fake_result = {"saved": 0, "skipped": 0, "failed": 0, "total": 0}
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient") as MockClient,
            patch("scraper.cli.Scraper") as MockScraper,
        ):
            inst_client = MagicMock()
            inst_client.api_key = "explicit-key"
            MockClient.return_value = inst_client
            inst_scraper = MagicMock()
            inst_scraper.run.return_value = fake_result
            MockScraper.return_value = inst_scraper
            main(["--api-key", "explicit-key", "sync"])
        MockClient.assert_called_once_with(api_key="explicit-key")

    def test_no_warning_when_key_present(self, tmp_path, capsys):
        """No warning printed when a valid API key is supplied."""
        fake_result = {"saved": 0, "skipped": 0, "failed": 0, "total": 0}
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient") as MockClient,
            patch("scraper.cli.Scraper") as MockScraper,
        ):
            inst_client = MagicMock()
            inst_client.api_key = "valid-key"
            MockClient.return_value = inst_client
            inst_scraper = MagicMock()
            inst_scraper.run.return_value = fake_result
            MockScraper.return_value = inst_scraper
            main(["--api-key", "valid-key", "sync"])
        err = capsys.readouterr().err
        assert "No API key" not in err
    def test_fetch_returns_nonzero_on_error(self, tmp_path, capsys):
        with (
            patch("scraper.cli._laws_dir", return_value=str(tmp_path)),
            patch("scraper.cli.ESbirkaClient") as MockClient,
        ):
            inst = MagicMock()
            inst.get_document.side_effect = requests.RequestException("not found")
            MockClient.return_value = inst
            rc = main(["fetch", "999", "2099"])
        assert rc == 1
