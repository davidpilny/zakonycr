"""Unit tests for LawStorage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scraper.storage import LawStorage, _sanitize


# ---------------------------------------------------------------------------
# _sanitize helper
# ---------------------------------------------------------------------------

class TestSanitize:
    def test_plain_string_unchanged(self):
        assert _sanitize("hello") == "hello"

    def test_string_with_colon_gets_quoted(self):
        result = _sanitize("Zákon: o věcech")
        assert result.startswith('"') and result.endswith('"')

    def test_none_returns_empty_string(self):
        assert _sanitize(None) == ""

    def test_integer_value(self):
        assert _sanitize(42) == "42"


# ---------------------------------------------------------------------------
# LawStorage construction
# ---------------------------------------------------------------------------

class TestLawStorageConstruction:
    def test_creates_laws_dir(self, tmp_path):
        laws_dir = tmp_path / "laws"
        assert not laws_dir.exists()
        LawStorage(laws_dir)
        assert laws_dir.exists()

    def test_accepts_string_path(self, tmp_path):
        storage = LawStorage(str(tmp_path / "laws"))
        assert storage.laws_dir.exists()


# ---------------------------------------------------------------------------
# State / sync tracking
# ---------------------------------------------------------------------------

class TestState:
    def test_get_last_sync_returns_none_when_no_state(self, tmp_path):
        storage = LawStorage(tmp_path)
        assert storage.get_last_sync() is None

    def test_set_and_get_last_sync(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.set_last_sync("2024-06-01T00:00:00+00:00")
        assert storage.get_last_sync() == "2024-06-01T00:00:00+00:00"

    def test_set_last_sync_defaults_to_now(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.set_last_sync()
        ts = storage.get_last_sync()
        assert ts is not None
        assert "T" in ts  # ISO-8601 format

    def test_state_round_trip(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_state({"last_sync": "2024-01-01T00:00:00Z", "extra": "data"})
        state = storage.load_state()
        assert state["last_sync"] == "2024-01-01T00:00:00Z"
        assert state["extra"] == "data"

    def test_load_state_returns_empty_dict_on_corrupt_file(self, tmp_path):
        state_file = tmp_path / "_state.json"
        state_file.write_text("not valid json", encoding="utf-8")
        storage = LawStorage(tmp_path)
        assert storage.load_state() == {}


# ---------------------------------------------------------------------------
# save_law / exists / law_path
# ---------------------------------------------------------------------------

class TestSaveLaw:
    def test_saves_file_at_expected_path(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2012, 89, {"nazev": "Občanský zákoník"}, "Text zákona")
        expected = tmp_path / "2012" / "89.md"
        assert expected.exists()

    def test_file_contains_frontmatter(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2012, 89, {"nazev": "Zákon o věcech"}, "Tělo zákona")
        content = (tmp_path / "2012" / "89.md").read_text(encoding="utf-8")
        assert "cislo: 89" in content
        assert "rok: 2012" in content
        assert "Zákon o věcech" in content

    def test_file_contains_body(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2012, 89, {}, "§ 1 Úvodní ustanovení")
        content = (tmp_path / "2012" / "89.md").read_text(encoding="utf-8")
        assert "§ 1 Úvodní ustanovení" in content

    def test_creates_year_subdirectory(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(1999, 100, {}, "body")
        assert (tmp_path / "1999").is_dir()

    def test_exists_returns_true_after_save(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2020, 10, {}, "body")
        assert storage.exists(2020, 10)

    def test_exists_returns_false_before_save(self, tmp_path):
        storage = LawStorage(tmp_path)
        assert not storage.exists(2020, 999)

    def test_overwrites_existing_file(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2020, 1, {}, "original")
        storage.save_law(2020, 1, {}, "updated")
        content = (tmp_path / "2020" / "1.md").read_text(encoding="utf-8")
        assert "updated" in content
        assert "original" not in content

    def test_metadata_with_url(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2012, 89, {"url": "https://api.e-sbirka.cz/sb/2012/89"}, "body")
        content = (tmp_path / "2012" / "89.md").read_text(encoding="utf-8")
        assert "url: https://api.e-sbirka.cz/sb/2012/89" in content

    def test_metadata_with_datum_ucinnosti(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2012, 89, {"datum_ucinnosti": "2014-01-01"}, "body")
        content = (tmp_path / "2012" / "89.md").read_text(encoding="utf-8")
        assert "datum_ucinnosti: 2014-01-01" in content


# ---------------------------------------------------------------------------
# load_law / _parse_law_file
# ---------------------------------------------------------------------------

class TestLoadLaw:
    def test_load_saved_law(self, tmp_path):
        storage = LawStorage(tmp_path)
        storage.save_law(2012, 89, {"nazev": "Obč. zákoník"}, "§ 1")
        result = storage.load_law(2012, 89)
        assert result is not None
        meta, body = result
        assert meta["cislo"] == "89"
        assert meta["rok"] == "2012"
        assert "§ 1" in body

    def test_load_nonexistent_returns_none(self, tmp_path):
        storage = LawStorage(tmp_path)
        assert storage.load_law(2000, 1) is None

    def test_parse_file_without_frontmatter(self):
        content = "Just some text without frontmatter"
        meta, body = LawStorage._parse_law_file(content)
        assert meta == {}
        assert body == content

    def test_parse_file_with_nazev_containing_colon(self, tmp_path):
        storage = LawStorage(tmp_path)
        nazev = "Zákon: o různých věcech"
        storage.save_law(2020, 5, {"nazev": nazev}, "body text")
        result = storage.load_law(2020, 5)
        assert result is not None
        meta, _ = result
        assert meta["nazev"] == nazev


# ---------------------------------------------------------------------------
# list_laws / count_laws / stats
# ---------------------------------------------------------------------------

class TestListLaws:
    def _populate(self, storage: LawStorage, entries: list[tuple[int, int]]) -> None:
        for year, number in entries:
            storage.save_law(year, number, {}, "body")

    def test_empty_storage(self, tmp_path):
        storage = LawStorage(tmp_path)
        assert storage.list_laws() == []
        assert storage.count_laws() == 0

    def test_lists_saved_laws(self, tmp_path):
        storage = LawStorage(tmp_path)
        self._populate(storage, [(2020, 1), (2020, 2), (2021, 1)])
        laws = storage.list_laws()
        assert (2020, 1) in laws
        assert (2020, 2) in laws
        assert (2021, 1) in laws

    def test_count_laws(self, tmp_path):
        storage = LawStorage(tmp_path)
        self._populate(storage, [(2020, 1), (2020, 2), (2021, 5)])
        assert storage.count_laws() == 3

    def test_stats_structure(self, tmp_path):
        storage = LawStorage(tmp_path)
        self._populate(storage, [(2020, 1), (2020, 2), (2021, 1)])
        storage.set_last_sync("2024-01-01T00:00:00Z")
        info = storage.stats()
        assert info["total"] == 3
        assert info["years"][2020] == 2
        assert info["years"][2021] == 1
        assert info["last_sync"] == "2024-01-01T00:00:00Z"

    def test_ignores_non_directory_entries(self, tmp_path):
        storage = LawStorage(tmp_path)
        # Create a file (not a dir) in the laws root
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        self._populate(storage, [(2022, 3)])
        assert storage.count_laws() == 1

    def test_ignores_non_md_files(self, tmp_path):
        storage = LawStorage(tmp_path)
        yr_dir = tmp_path / "2022"
        yr_dir.mkdir()
        (yr_dir / "1.txt").write_text("not a law", encoding="utf-8")
        assert storage.count_laws() == 0
