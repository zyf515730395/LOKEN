"""Command line interface for private local paper summarization."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .models import PaperSummaryError
from .workflow import run_summaries, status_snapshot


DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise PaperSummaryError("invalid_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeParser(prog="python -m papers.summaries")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="generate missing accepted paper summaries")
    run.add_argument(
        "--model", default=os.environ.get("TOGOS_WSL_LLM_MODEL"), help="local model name"
    )
    run.add_argument(
        "--base-url",
        default=os.environ.get("TOGOS_WSL_LLM_BASE_URL", DEFAULT_BASE_URL),
        help="literal loopback OpenAI-compatible /v1 URL",
    )
    run.add_argument("--timeout", type=float, default=180.0)
    run.add_argument("--paper", action="append", default=[], help="accepted arXiv ID; repeatable")
    run.add_argument("--limit", type=int, default=10)
    run.add_argument("--refresh", action="store_true")
    status = commands.add_parser("status", help="show accepted summary coverage")
    status.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _execute(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "status":
        snapshot = status_snapshot()
        if arguments.as_json:
            print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"accepted={snapshot['accepted']} ready={snapshot['ready']} "
                f"pending={snapshot['pending']}"
            )
        return 0
    if not isinstance(arguments.model, str) or not arguments.model.strip():
        raise PaperSummaryError(
            "model_required", "pass --model or set TOGOS_WSL_LLM_MODEL"
        )
    if arguments.refresh and len(arguments.paper) != 1:
        raise PaperSummaryError(
            "refresh_requires_one_paper", "--refresh requires exactly one --paper"
        )
    result = run_summaries(
        model=arguments.model.strip(),
        base_url=arguments.base_url,
        timeout=arguments.timeout,
        paper_ids=tuple(arguments.paper),
        limit=arguments.limit,
        refresh=arguments.refresh,
    )
    print(
        f"selected={result.selected} succeeded={result.succeeded} "
        f"failed={result.failed} published={result.published}"
    )
    for record in result.records:
        if record.status == "succeeded":
            print(
                f"succeeded {record.arxiv_id} {record.topic} source={record.source}"
            )
        else:
            print(
                f"failed {record.arxiv_id} {record.topic} "
                f"{record.error_code}: {record.error_message}",
                file=sys.stderr,
            )
    return 3 if result.partial else 0


def main() -> None:
    try:
        raise SystemExit(_execute())
    except PaperSummaryError as error:
        print(f"error {error.code}: {error.message}", file=sys.stderr)
        raise SystemExit(2) from None
