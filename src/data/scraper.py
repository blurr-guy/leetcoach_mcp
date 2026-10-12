"""One-time LeetCode catalog scraper.

This module is used **only** by ``scripts/seed_catalog.py`` to populate the
``problems`` table.  The MCP tools never call LeetCode's live API - they read
the seeded catalog from the local SQLite database.

Implements pagination over the public GraphQL endpoint with polite rate
limiting (fixed delay between pages) and exponential backoff + retry on
429 / 5xx responses.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from src.errors import CoachError, RateLimitError

log = logging.getLogger(__name__)

GRAPHQL_URL = os.getenv("LEETCODE_GRAPHQL_URL", "https://leetcode.com/graphql")
PAGE_SIZE = int(os.getenv("LEETCOACH_SCRAPE_PAGE_SIZE", "50"))
DELAY_SECONDS = float(os.getenv("LEETCOACH_SCRAPE_DELAY_SECONDS", "1.5"))
MAX_RETRIES = int(os.getenv("LEETCOACH_SCRAPE_MAX_RETRIES", "4"))
BACKOFF_BASE = float(os.getenv("LEETCOACH_SCRAPE_BACKOFF_BASE", "2.0"))

_HEADERS = {
    "content-type": "application/json",
    "referer": "https://leetcode.com/problemset/",
    "origin": "https://leetcode.com",
    "user-agent": os.getenv(
        "LEETCOACH_SCRAPE_USER_AGENT",
        "leetcode-coach-mcp/1.0 (offline catalog scraper; opensource)",
    ),
}

_QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int,
                             $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit,
                                       skip: $skip, filters: $filters) {
    total: totalNum
    questions: data {
      acRate
      difficulty
      freqBar
      questionFrontendId
      isPaidOnly
      title
      titleSlug
      topicTags { name slug }
    }
  }
}
"""


@dataclass
class ScrapedProblem:
    id: int
    title: str
    slug: str
    difficulty: str
    topics: list[str]
    leetcode_url: str
    acceptance_rate: float
    frequency: float

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "difficulty": self.difficulty,
            "topics": self.topics,
            "leetcode_url": self.leetcode_url,
            "acceptance_rate": self.acceptance_rate,
            "frequency": self.frequency,
        }


class ScrapeError(CoachError):
    code = "scrape_error"


def _request_page(session: requests.Session, skip: int, limit: int) -> dict[str, Any]:
    """POST one page of the GraphQL query with retry + exponential backoff."""
    payload = {
        "operationName": "problemsetQuestionList",
        "query": _QUERY,
        "variables": {
            "categorySlug": "",
            "skip": skip,
            "limit": limit,
            "filters": {},
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(GRAPHQL_URL, json=payload, timeout=30)
        except requests.RequestException as exc:
            log.warning("Request error (attempt %s/%s): %s", attempt, MAX_RETRIES, exc)
            _sleep_before_retry(attempt)
            continue

        if resp.status_code == 200:
            body = resp.json()
            if "errors" in body:
                raise ScrapeError(
                    f"GraphQL returned error payload: {body['errors']}",
                    code="graphql_error",
                )
            return body["data"]["problemsetQuestionList"]

        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning(
                "HTTP %s on page skip=%s (attempt %s/%s)",
                resp.status_code, skip, attempt, MAX_RETRIES,
            )
            _sleep_before_retry(attempt)
            continue

        raise ScrapeError(
            f"Unhandled HTTP {resp.status_code} from LeetCode GraphQL.",
            code="http_error",
            http_status=resp.status_code,
        )

    raise RateLimitError(
        f"LeetCode scrape failed after {MAX_RETRIES} attempts (skip={skip}).",
        code="scrape_rate_limited",
    )


def _sleep_before_retry(attempt: int) -> None:
    if attempt < MAX_RETRIES:
        time.sleep(min(BACKOFF_BASE ** attempt, 30))


def _parse_questions(raw: list[dict[str, Any]], include_paid: bool = False) -> list[ScrapedProblem]:
    problems: list[ScrapedProblem] = []
    for q in raw:
        if q.get("isPaidOnly") and not include_paid:
            continue
        frontend_id = q.get("questionFrontendId")
        if frontend_id is None:
            continue
        problems.append(
            ScrapedProblem(
                id=int(frontend_id),
                title=q["title"],
                slug=q["titleSlug"],
                difficulty=q["difficulty"],
                topics=[t["name"] for t in (q.get("topicTags") or [])],
                leetcode_url=f"https://leetcode.com/problems/{q['titleSlug']}/",
                acceptance_rate=float(q.get("acRate") or 0.0),
                frequency=float(q.get("freqBar") or 0.0),
            )
        )
    return problems


def scrape_catalog(
    *,
    max_problems: Optional[int] = None,
    include_paid: bool = False,
    delay_seconds: Optional[float] = None,
    page_size: Optional[int] = None,
    progress_callback: Optional[callable] = None,
) -> list[ScrapedProblem]:
    """Scrape the whole LeetCode problem set into a flat list.

    Args:
        max_problems: cap for quick runs (e.g. ``--limit 20``).
        include_paid: keep premium-only problems (default: skip them).
        delay_seconds: override the inter-page delay.
        page_size: override the page size.
        progress_callback: called with ``(index, total, problem)`` per row.

    Returns:
        list[:class:`ScrapedProblem`] - catalog rows ready for upsert.
    """
    delay = delay_seconds if delay_seconds is not None else DELAY_SECONDS
    size = page_size if page_size is not None else PAGE_SIZE
    session = requests.Session()
    session.headers.update(_HEADERS)

    first = _request_page(session, skip=0, limit=size)
    total = int(first.get("total") or 0)
    if max_problems:
        total = min(total, max_problems)

    problems: list[ScrapedProblem] = []
    skip = 0
    count = 0
    while skip < total:
        page = first if skip == 0 else _request_page(session, skip=skip, limit=size)
        parsed = _parse_questions(page.get("questions") or [], include_paid=include_paid)

        remaining = None
        if max_problems is not None:
            remaining = max_problems - count
            if remaining <= 0:
                break
            parsed = parsed[:remaining]

        problems.extend(parsed)
        if progress_callback is not None:
            for i, p in enumerate(parsed):
                progress_callback(count + i, total, p)
        count += len(parsed)

        skip += size
        if count >= total:
            break
        if skip < total:
            time.sleep(delay)

    return problems