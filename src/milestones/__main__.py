"""Command-line entrypoint for milestone reading and publication."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from .publisher import publish_milestone_models
from .reader import MilestoneReaderError, process_milestone_family


def _add_note_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("config/milestone_models.yaml"),
        help="milestone catalog YAML",
    )
    parser.add_argument(
        "--notes-root",
        type=Path,
        default=os.getenv("PAPER_NOTES_ROOT"),
        help="private paper Markdown root (or PAPER_NOTES_ROOT)",
    )
    parser.add_argument("--family", default="flux", help="family slug")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m milestones",
        description="Generate, selectively refresh, and publish milestone readings.",
    )
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    read = commands.add_parser("read", help="generate only missing deep readings")
    _add_note_arguments(read)
    read.add_argument(
        "--base-url",
        default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
    )
    read.add_argument("--model", default=os.getenv("VLLM_MODEL"))
    read.add_argument("--release", action="append", dest="releases")

    refresh = commands.add_parser(
        "refresh-limitations",
        help="replace only limitations in existing deep readings",
    )
    _add_note_arguments(refresh)
    refresh.add_argument(
        "--base-url",
        default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
    )
    refresh.add_argument("--model", default=os.getenv("VLLM_MODEL"))
    refresh.add_argument("--release", action="append", dest="releases")

    publish = commands.add_parser(
        "publish", help="render milestone pages without generating the rest of the site"
    )
    _add_note_arguments(publish)
    publish.add_argument(
        "--output-root", type=Path, default=Path("docs/milestone-models")
    )
    return parser


def _require(value, parser: argparse.ArgumentParser, message: str):
    if value is None or (isinstance(value, str) and not value.strip()):
        parser.error(message)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    notes_root = _require(
        args.notes_root,
        parser,
        "--notes-root or PAPER_NOTES_ROOT is required",
    )
    try:
        if args.command == "publish":
            result = publish_milestone_models(
                args.catalog,
                notes_root,
                args.output_root,
                only_family=args.family,
            )
        else:
            model = _require(args.model, parser, "--model or VLLM_MODEL is required")
            result = process_milestone_family(
                args.catalog,
                notes_root,
                args.family,
                args.base_url,
                model,
                refresh_limitations=args.command == "refresh-limitations",
                release_slugs=set(args.releases) if args.releases else None,
            )
    except (OSError, ValueError, MilestoneReaderError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
