"""Storage layer: persist scraped laws as Markdown files on disk.

Directory layout::

    laws/
        {year}/
            {number}.md   ← one file per law, YAML front-matter + body
        _state.json       ← tracks the last successful sync timestamp

Markdown file format::

    ---
    cislo: 89
    rok: 2012
    nazev: Občanský zákoník
    castka: 33
    datum_ucinnosti: 2014-01-01
    url: https://api.e-sbirka.cz/...
    ---

    <full text of the law>
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STATE_FILE = "_state.json"
_FRONTMATTER_FIELDS = (
    "cislo",
    "rok",
    "nazev",
    "castka",
    "datum_ucinnosti",
    "url",
)


def _sanitize(value: object) -> str:
    """Return a YAML-safe string for a scalar value.

    Quoting is applied only when strictly necessary: a bare colon followed by
    a space (``": "``) is the classic YAML mapping ambiguity, as is a leading
    ``#``, ``{``, or embedded newlines.  Plain colons inside URLs (``://``)
    are valid unquoted YAML scalars.
    """
    text = str(value) if value is not None else ""
    needs_quoting = (
        ": " in text          # mapping key ambiguity
        or text.startswith("#")  # comment marker
        or text.startswith("{")  # flow mapping
        or text.startswith("[")  # flow sequence
        or "\n" in text          # multiline value
        or '"' in text           # embedded double-quote
    )
    if needs_quoting:
        text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


class LawStorage:
    """Read and write law files inside *laws_dir*.

    Parameters
    ----------
    laws_dir:
        Root directory that will hold all law files (e.g. ``laws/``).
        Created on first use if it does not exist.
    """

    def __init__(self, laws_dir: str | Path) -> None:
        self.laws_dir = Path(laws_dir)
        self.laws_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # State / sync tracking
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self.laws_dir / _STATE_FILE

    def load_state(self) -> dict:
        """Return the persisted sync state, or an empty dict."""
        path = self._state_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read state file: %s", exc)
        return {}

    def save_state(self, state: dict) -> None:
        """Persist *state* to disk."""
        self._state_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_last_sync(self) -> Optional[str]:
        """Return the ISO-8601 timestamp of the last successful full sync."""
        return self.load_state().get("last_sync")

    def set_last_sync(self, timestamp: Optional[str] = None) -> None:
        """Update the last-sync timestamp (defaults to now)."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        state = self.load_state()
        state["last_sync"] = ts
        self.save_state(state)

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def law_path(self, year: int, number: int) -> Path:
        """Return the file path for a given law."""
        return self.laws_dir / str(year) / f"{number}.md"

    def exists(self, year: int, number: int) -> bool:
        return self.law_path(year, number).exists()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_law(
        self,
        year: int,
        number: int,
        metadata: dict,
        body: str,
    ) -> Path:
        """Write *body* with YAML front-matter to ``laws/{year}/{number}.md``.

        Returns the path of the created/updated file.
        """
        path = self.law_path(year, number)
        path.parent.mkdir(parents=True, exist_ok=True)

        front = self._build_frontmatter(year, number, metadata)
        content = f"---\n{front}---\n\n{body.strip()}\n"
        path.write_text(content, encoding="utf-8")
        logger.debug("Saved %s", path)
        return path

    def _build_frontmatter(self, year: int, number: int, metadata: dict) -> str:
        lines = [
            f"cislo: {number}",
            f"rok: {year}",
        ]
        for field in _FRONTMATTER_FIELDS:
            if field in ("cislo", "rok"):
                continue
            value = metadata.get(field)
            if value is not None:
                lines.append(f"{field}: {_sanitize(value)}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_law(self, year: int, number: int) -> Optional[tuple[dict, str]]:
        """Return ``(metadata, body)`` for *number/year*, or *None*."""
        path = self.law_path(year, number)
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        return self._parse_law_file(content)

    @staticmethod
    def _parse_law_file(content: str) -> tuple[dict, str]:
        """Parse a law file into ``(metadata_dict, body_text)``."""
        if not content.startswith("---"):
            return {}, content

        try:
            end = content.index("---", 3)
        except ValueError:
            # No closing delimiter – treat whole content as body
            return {}, content

        frontmatter_text = content[3:end].strip()
        body = content[end + 3:].strip()

        metadata: dict = {}
        for line in frontmatter_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'^(\w+):\s*(.*)', line)
            if match:
                key, val = match.group(1), match.group(2).strip()
                # Remove surrounding quotes added by _sanitize
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1].replace('\\"', '"')
                metadata[key] = val

        return metadata, body

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_laws(self) -> list[tuple[int, int]]:
        """Return ``[(year, number), ...]`` for every stored law."""
        result = []
        for year_dir in sorted(self.laws_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            try:
                year = int(year_dir.name)
            except ValueError:
                continue
            for law_file in sorted(year_dir.glob("*.md")):
                try:
                    number = int(law_file.stem)
                except ValueError:
                    continue
                result.append((year, number))
        return result

    def count_laws(self) -> int:
        return len(self.list_laws())

    def stats(self) -> dict:
        laws = self.list_laws()
        years: dict[int, int] = {}
        for year, _ in laws:
            years[year] = years.get(year, 0) + 1
        return {
            "total": len(laws),
            "years": years,
            "last_sync": self.get_last_sync(),
        }
