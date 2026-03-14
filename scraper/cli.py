"""Command-line interface for the zakonycr scraper.

Usage examples::

    # Full sync (all laws)
    python -m scraper.cli sync

    # Incremental sync (only laws changed since last run)
    python -m scraper.cli sync --incremental

    # Force a fresh full sync even if state exists
    python -m scraper.cli sync --force

    # Show storage statistics (no API key needed)
    python -m scraper.cli stats

    # Fetch a single law by number/year
    python -m scraper.cli fetch 89 2012

    # Pass the API key explicitly instead of via the environment variable
    python -m scraper.cli --api-key MY_KEY sync

Environment variables
---------------------
ESBIRKA_API_KEY   API key for the e-Sbírka REST API (required for full access).
                  Alternatively use the ``--api-key`` flag.
LAWS_DIR          Directory to store law files (default: ``laws/``)

Obtaining an API key
--------------------
Register at the Ministry of Interior and request access:
https://e-sbirka.gov.cz/restful-api
The ``stats`` sub-command works without a key because it only reads local files.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import requests

from .client import ESbirkaClient
from .scraper import Scraper
from .storage import LawStorage


_NO_KEY_MESSAGE = """\
Warning: No API key provided.
  The e-Sbírka API requires authentication for most endpoints.
  Requests will likely fail with HTTP 401 (Unauthorized).

  How to get a key:
    1. Fill in the registration form at https://e-sbirka.gov.cz/restful-api
    2. Submit it to the Ministry of Interior via data-box.
    3. You will receive an API key by email.

  Once you have a key, provide it in one of two ways:
    * Environment variable:  export ESBIRKA_API_KEY="your-key"
    * CLI flag:              python -m scraper.cli --api-key "your-key" sync
"""


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _laws_dir() -> str:
    return os.environ.get("LAWS_DIR", "laws")


def _warn_if_no_key(client: ESbirkaClient) -> None:
    """Print a clear, actionable warning if the client has no API key."""
    if not client.api_key:
        print(_NO_KEY_MESSAGE, file=sys.stderr)


# ------------------------------------------------------------------
# Sub-command: sync
# ------------------------------------------------------------------

def cmd_sync(args: argparse.Namespace) -> int:
    client = ESbirkaClient(api_key=args.api_key)
    _warn_if_no_key(client)
    storage = LawStorage(_laws_dir())
    force_full = args.force or not args.incremental

    def _progress(done: int, total: int | None) -> None:
        if total:
            pct = 100 * done // total
            print(f"\r  {done}/{total} ({pct}%)", end="", flush=True)
        else:
            print(f"\r  {done} processed", end="", flush=True)

    scraper = Scraper(
        client,
        storage,
        force_full=force_full,
        on_progress=_progress,
    )

    print("Starting sync...")
    result = scraper.run()
    print()  # newline after progress line
    print(
        f"Done. saved={result.get('saved', 0)}, "
        f"skipped={result.get('skipped', 0)}, "
        f"failed={result.get('failed', 0)}, "
        f"total={result.get('total', 0)}"
    )
    return 0 if result.get("failed", 0) == 0 else 1


# ------------------------------------------------------------------
# Sub-command: fetch
# ------------------------------------------------------------------

def cmd_fetch(args: argparse.Namespace) -> int:
    client = ESbirkaClient(api_key=args.api_key)
    _warn_if_no_key(client)
    storage = LawStorage(_laws_dir())

    year: int = args.year
    number: int = args.number

    print(f"Fetching law {number}/{year}...")
    try:
        detail = client.get_document(year, number)
        text = client.get_document_text(year, number)
    except (requests.RequestException, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    from .scraper import _build_metadata  # local import to avoid circular

    metadata = _build_metadata(detail)
    path = storage.save_law(year, number, metadata, text)
    print(f"Saved to {path}")
    return 0


# ------------------------------------------------------------------
# Sub-command: stats
# ------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace) -> int:  # noqa: ARG001
    storage = LawStorage(_laws_dir())
    info = storage.stats()
    print(f"Total laws stored : {info['total']}")
    print(f"Last sync         : {info['last_sync'] or 'never'}")
    if info["years"]:
        print("Laws per year:")
        for year in sorted(info["years"]):
            print(f"  {year}: {info['years'][year]}")
    return 0


# ------------------------------------------------------------------
# Argument parser
# ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.cli",
        description="Scrape Czech laws from the e-Sbírka API.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help=(
            "e-Sbírka API key. Overrides the ESBIRKA_API_KEY environment "
            "variable. Obtain a key at https://e-sbirka.gov.cz/restful-api"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    p_sync = sub.add_parser("sync", help="Sync laws from e-Sbírka.")
    p_sync.add_argument(
        "--incremental",
        action="store_true",
        default=False,
        help="Only fetch laws changed since the last sync.",
    )
    p_sync.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Ignore stored sync state and perform a full sync.",
    )

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch a single law.")
    p_fetch.add_argument("number", type=int, help="Law number (e.g. 89).")
    p_fetch.add_argument("year", type=int, help="Year of the law (e.g. 2012).")

    # stats
    sub.add_parser("stats", help="Show storage statistics.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    dispatch = {
        "sync": cmd_sync,
        "fetch": cmd_fetch,
        "stats": cmd_stats,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
