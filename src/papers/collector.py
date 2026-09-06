"""Collect the public arXiv list on a GitHub-hosted runner."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
import time

import arxiv
import requests
import yaml

from .candidate_ledger import (
    atomic_write_json,
    load_candidate_ledger,
    merge_collected_candidates,
)


logging.basicConfig(
    format="[%(asctime)s %(levelname)s] %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)

ARXIV_BASE_URL = "https://arxiv.org/"
ARXIV_REQUEST_DELAY_SECONDS = 10.0
ARXIV_RETRY_ATTEMPTS = 4
ARXIV_RETRY_BACKOFF_SECONDS = 30
ARXIV_CONNECT_TIMEOUT_SECONDS = 10
ARXIV_READ_TIMEOUT_SECONDS = 60
RETRYABLE_ARXIV_STATUSES = {429, 500, 502, 503, 504}


class ArxivRetryExhausted(RuntimeError):
    """Raised after a transient arXiv API failure exhausts its backoff."""


class ArxivTimeoutSession(requests.Session):
    """Apply finite connect/read timeouts to the arxiv package session."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault(
            "timeout",
            (ARXIV_CONNECT_TIMEOUT_SECONDS, ARXIV_READ_TIMEOUT_SECONDS),
        )
        return super().request(method, url, **kwargs)


def make_arxiv_client(page_size: int) -> arxiv.Client:
    client = arxiv.Client(
        page_size=page_size,
        delay_seconds=ARXIV_REQUEST_DELAY_SECONDS,
        num_retries=0,
    )
    client._session = ArxivTimeoutSession()
    return client


def is_retryable_arxiv_error(error: Exception) -> bool:
    if isinstance(error, arxiv.HTTPError):
        return error.status in RETRYABLE_ARXIV_STATUSES
    return isinstance(
        error,
        (arxiv.UnexpectedEmptyPageError, requests.ConnectionError, requests.Timeout),
    )


def fetch_arxiv_results(
    client: arxiv.Client, search: arxiv.Search, topic: str
) -> list[arxiv.Result]:
    for attempt in range(1, ARXIV_RETRY_ATTEMPTS + 1):
        try:
            return list(client.results(search))
        except (arxiv.ArxivError, requests.RequestException) as error:
            if not is_retryable_arxiv_error(error):
                raise
            if attempt == ARXIV_RETRY_ATTEMPTS:
                raise ArxivRetryExhausted(
                    f"arXiv request for {topic!r} failed after "
                    f"{ARXIV_RETRY_ATTEMPTS} attempts: {error}"
                ) from error
            wait_seconds = ARXIV_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logging.warning(
                "Transient arXiv error for %s (attempt %d/%d): %s; "
                "retrying in %d seconds",
                topic,
                attempt,
                ARXIV_RETRY_ATTEMPTS,
                error,
                wait_seconds,
            )
            time.sleep(wait_seconds)
    raise AssertionError("unreachable")


def format_query_term(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' if len(term.split()) > 1 else escaped


def build_filter_query(
    filters: list[str],
    fields: list[str] | None = None,
    categories: list[str] | None = None,
) -> str:
    if not filters:
        raise ValueError("Keyword filters must not be empty")
    if fields:
        scoped_terms = []
        for filter_term in filters:
            formatted_term = format_query_term(filter_term)
            field_query = " OR ".join(
                f"{field}:{formatted_term}" for field in fields
            )
            scoped_terms.append(f"({field_query})")
        filter_query = f'({" OR ".join(scoped_terms)})'
    else:
        filter_query = " OR ".join(format_query_term(term) for term in filters)
    if not categories:
        return filter_query
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    return f"{filter_query} AND ({category_query})"


def load_config(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    config["queries"] = {
        topic: build_filter_query(
            settings["filters"],
            fields=settings.get("fields"),
            categories=settings.get("categories"),
        )
        for topic, settings in config["keywords"].items()
    }
    return config


def paper_record(result: arxiv.Result, topic: str) -> dict:
    paper_id = result.get_short_id().split("v", 1)[0]
    title = result.title
    first_author = str(result.authors[0])
    updated = result.updated.date().isoformat()
    paper_url = f"{ARXIV_BASE_URL}abs/{paper_id}"
    pdf_url = (result.pdf_url or f"{ARXIV_BASE_URL}pdf/{paper_id}.pdf").replace(
        "http://", "https://"
    )
    archive_row = (
        f"|**{updated}**|**{title}**|{first_author} et.al.|"
        f"[{paper_id}]({paper_url})|null|\n"
    )
    return {
        "id": paper_id,
        "title": title,
        "abstract": result.summary,
        "authors": f"{first_author} et.al.",
        "updated": updated,
        "paper_url": paper_url,
        "pdf_url": pdf_url,
        "topic": topic,
        "archive_row": archive_row,
    }


def fetch_topic(
    client: arxiv.Client, topic: str, query: str, max_results: int | None = None
) -> list[dict]:
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    records = [
        paper_record(result, topic)
        for result in fetch_arxiv_results(client, search, topic)
    ]
    for record in records:
        logging.info(
            "Time = %s title = %s author = %s",
            record["updated"],
            record["title"],
            record["authors"],
        )
    return records


def fetch_collection(
    config: dict, ledger: dict, *, now: dt.datetime | None = None
) -> tuple[list[dict], list[str], dict[str, str]]:
    """Read every page in each topic's UTC window; advance only complete topics."""
    settings = config.get("collection", {})
    lookback_days = max(1, int(settings.get("lookback_days", 7)))
    overlap_days = max(2, int(settings.get("overlap_days", 2)))
    batch_size = max(1, int(settings.get("query_batch_size", 8)))
    page_size = min(2000, max(1, int(settings.get("page_size", 100))))
    end = now or dt.datetime.now(dt.timezone.utc)
    if end.tzinfo is None:
        raise ValueError("Collection time must include a timezone")
    end = end.astimezone(dt.timezone.utc).replace(microsecond=0)
    cursors = dict(ledger.get("collection_cursors", {}))
    client = make_arxiv_client(page_size)
    records: list[dict] = []
    failed_topics: list[str] = []
    for topic, keyword_settings in config["keywords"].items():
        start = end - dt.timedelta(days=lookback_days)
        if topic in cursors:
            cursor = dt.datetime.fromisoformat(cursors[topic])
            if cursor.tzinfo is None or cursor > end:
                raise ValueError(f"Invalid collection cursor for {topic!r}")
            start = cursor.astimezone(dt.timezone.utc) - dt.timedelta(days=overlap_days)
        window = f"submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"
        filters = keyword_settings["filters"]
        if not filters:
            raise ValueError(f"Keyword filters must not be empty: {topic}")
        topic_records: dict[str, dict] = {}
        try:
            for offset in range(0, len(filters), batch_size):
                query = build_filter_query(
                    filters[offset : offset + batch_size],
                    fields=keyword_settings.get("fields"),
                    categories=keyword_settings.get("categories"),
                )
                for record in fetch_topic(client, topic, f"({query}) AND {window}"):
                    topic_records[record["id"]] = record
        except (ArxivRetryExhausted, arxiv.ArxivError, requests.RequestException) as error:
            logging.error("Preserving cursor for failed topic %s: %s", topic, error)
            failed_topics.append(topic)
            continue
        records.extend(topic_records.values())
        cursors[topic] = end.isoformat()
    if failed_topics and len(failed_topics) == len(config["keywords"]):
        raise RuntimeError("All arXiv topics failed: " + ", ".join(failed_topics))
    return records, failed_topics, cursors


def fetch_all_topics(queries: dict[str, str], max_results: int) -> tuple[list, list]:
    client = make_arxiv_client(min(max(max_results, 1), 100))
    records: list[dict] = []
    failed_topics: list[str] = []
    for topic, query in queries.items():
        logging.info("Keyword: %s", topic)
        try:
            records.extend(fetch_topic(client, topic, query, max_results))
        except ArxivRetryExhausted as error:
            logging.error("Skipping topic after retries: %s", error)
            failed_topics.append(topic)
    if failed_topics and len(failed_topics) == len(queries):
        raise RuntimeError(
            "All arXiv topics failed after retries: " + ", ".join(failed_topics)
        )
    if failed_topics:
        logging.warning(
            "Completed with stale data preserved for failed topics: %s",
            ", ".join(failed_topics),
        )
    return records, failed_topics


def load_archive(path: str | Path) -> dict:
    archive_path = Path(path)
    if not archive_path.exists():
        return {}
    content = archive_path.read_text(encoding="utf-8")
    return json.loads(content) if content else {}


def collect(config_path: str | Path) -> dict[str, int]:
    config = load_config(config_path)
    archive_path = config["json_gitpage_path"]
    html_path = config["html_gitpage_path"]
    output_root = config.get("output_root", str(Path(html_path).parent))
    search_index_path = config.get(
        "search_index_path", str(Path(output_root) / "search-index.json")
    )
    ledger_path = config["candidate_ledger_path"]
    milestone_catalog_path = config["milestone_catalog_path"]
    topics = list(config["queries"])
    archive = load_archive(archive_path)
    ledger = load_candidate_ledger(ledger_path)
    records, failed_topics, cursors = fetch_collection(config, ledger)
    _, next_ledger, added = merge_collected_candidates(
        archive, ledger, records, topics
    )
    next_ledger["collection_cursors"] = cursors
    atomic_write_json(ledger_path, next_ledger)
    result = {
        "collected": len(records),
        "new_candidates": added,
        "failed_topics": len(failed_topics),
    }
    logging.info("Cloud candidate collection result = %s", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/site.yaml")
    args = parser.parse_args()
    collect(args.config)


if __name__ == "__main__":
    main()
