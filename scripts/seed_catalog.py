#!/usr/bin/env python3
"""One-time catalog seeder.

Scrapes LeetCode's public GraphQL endpoint (paginated, rate limited) using
``src.data.scraper`` and upserts every problem into the local SQLite
``problems`` table.  Run from the repo root after installing deps:

    source .venv/bin/activate
    python scripts/seed_catalog.py --limit 100      # quick smoke run
    python scripts/seed_catalog.py                  # full catalog

The MCP tools never touch this live endpoint; they only read the seeded rows.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow running directly from the repo root

from src.data.scraper import scrape_catalog  # noqa: E402
from src.data.db import get_client  # noqa: E402
from src.errors import CoachError  # noqa: E402
from src.services.problem_service import upsert_problems  # noqa: E402

log = logging.getLogger("seed_catalog")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate the local problems catalog.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Scrape at most N problems (handy for local smoke tests).",
    )
    parser.add_argument(
        "--include-paid",
        action="store_true",
        help="Also keep premium-only problems (default: skip them).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Override seconds between GraphQL pages (default from .env / 1.5).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Override GraphQL page size (default 50).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all existing rows from the problems table before seeding.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _on_progress(count: int, total: int, _problem) -> None:
    if count % 100 == 0:
        log.info("scraped %d / %d problems...", count, total)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.limit and args.limit < 0:
        log.error("--limit must be >= 0")
        return 2

    try:
        log.info("Scraping LeetCode catalog (limit=%s, page_size=%s)...",
                 args.limit, args.page_size or "default")
        problems = scrape_catalog(
            max_problems=args.limit,
            include_paid=args.include_paid,
            delay_seconds=args.delay,
            page_size=args.page_size,
            progress_callback=_on_progress if not args.quiet else None,
        )
        log.info("Scraped %d problems. Writing to the local database...", len(problems))

        db = get_client()
        if args.reset:
            db.table("problems").delete().gte("id", 0).execute()
            log.info("Cleared existing catalog.")

        rows = [p.as_row() for p in problems]
        written = 0
        for i in range(0, len(rows), 500):
            written += upsert_problems(db, rows[i:i + 500])
            log.info("upserted %d / %d", written, len(rows))

        log.info("Done: %d problems in the catalog.", written)
        return 0
    except CoachError as exc:
        log.error("Failed to seed catalog: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover - last-resort guard
        log.error("Unexpected failure: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())