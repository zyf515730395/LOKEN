"""CLI for validated builds and independently scheduled stocks maintenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import subprocess

import yaml

from .data import load_public_content
from .maintenance import record, status
from .site import publish_stocks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verified macro calendar and weekly conditional outlooks")
    parser.add_argument("command", choices=("build", "validate", "status", "record"))
    parser.add_argument("--config", type=Path, default=Path("config/stocks.yaml"))
    parser.add_argument("--content-root", type=Path, default=Path("content/stocks"))
    parser.add_argument("--output-root", type=Path, default=Path("docs"))
    parser.add_argument("--receipt-root", type=Path, default=Path("build/reports/stocks"))
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--phase", choices=("validated", "built", "published", "completed", "deferred"))
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            _, events, outlooks = load_public_content(args.config, args.content_root)
            result = {"valid": True, "events": len(events["events"]), "outlooks": len(outlooks)}
        elif args.command == "build":
            result = {"pages": [str(path) for path in publish_stocks(config_path=args.config, content_root=args.content_root, output_root=args.output_root)]}
        elif args.command == "status":
            result = status(config_path=args.config, content_root=args.content_root, receipt_root=args.receipt_root)
        else:
            if not args.phase:
                parser.error("record requires --phase")
            result = record(phase=args.phase, config_path=args.config, content_root=args.content_root, output_root=args.output_root,
                            receipt_root=args.receipt_root, repository=args.repository, reason=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired, yaml.YAMLError) as error:
        print(json.dumps({"error": str(error), "action": "preserve prior content; correct evidence or record deferred with --reason"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
