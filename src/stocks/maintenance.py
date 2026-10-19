"""Durable Sunday receipts, with completion contingent on remote Git verification."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess

from .data import SHANGHAI, aware_datetime, content_fingerprint, latest_due, load_public_content, official_host, read_json, require
from .site import _atomic_write


def _json_write(path: Path, document: dict) -> None:
    _atomic_write(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, timeout=45, check=False)
    require(result.returncode == 0, "Git verification failed: " + result.stderr.strip())
    return result.stdout.strip()


def output_fingerprint(output_root: Path) -> dict[str, str]:
    result = {}
    for name in ("index.html", "outlook.html", "quant.html"):
        path = output_root / "stocks" / name
        require(path.is_file(), f"Build output missing: {path}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def status(*, config_path: Path, content_root: Path, receipt_root: Path, now: datetime | None = None) -> dict:
    period = latest_due(now).isoformat()
    path = receipt_root / f"{period}.json"
    receipt = read_json(path) if path.exists() else None
    fingerprint = content_fingerprint(config_path, content_root)
    complete = bool(receipt and receipt.get("phase") == "completed" and receipt.get("content_fingerprint") == fingerprint)
    return {"period": period, "timezone": "Asia/Shanghai", "target": f"{period}T08:00:00+08:00", "due": not complete,
            "receipt": receipt, "receipt_path": str(path), "content_fingerprint": fingerprint,
            "next_action": "none" if complete else "preflight Git/maintenance processes/held locks, verify official sources, update public content, validate, build, publish and record completed"}


def record(*, phase: str, config_path: Path, content_root: Path, output_root: Path,
           receipt_root: Path, repository: Path, reason: str = "", now: datetime | None = None) -> dict:
    require(phase in {"validated", "built", "published", "completed", "deferred"}, "Unknown stocks phase")
    local = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    current = status(config_path=config_path, content_root=content_root, receipt_root=receipt_root, now=local)
    path = Path(current["receipt_path"])
    previous = current["receipt"] or {"schema_version": 1, "period": current["period"], "phases": {}}
    receipt = dict(previous)
    receipt["phases"] = dict(previous.get("phases", {}))
    fingerprint = current["content_fingerprint"]
    if phase == "deferred":
        require(bool(reason.strip()), "Deferred receipt requires a reason")
        receipt.update(phase=phase, reason=reason, updated_at=local.isoformat())
        receipt["phases"][phase] = {"at": local.isoformat(), "reason": reason}
        _json_write(path, receipt)
        return receipt
    config, events, outlooks = load_public_content(config_path, content_root)
    require(any(item["period"] == current["period"] for item in outlooks), "Latest due outlook is missing; preserve prior public content and defer")
    require(bool(events["events"]), "Verified event/monitor evidence is missing")
    # The weekly update must include fresh checks, even when no selected releases are due.
    boundary = datetime.fromisoformat(current["period"] + "T00:00:00+08:00")
    require(aware_datetime(events["updated_at"], "events.updated_at") >= boundary,
            "events calendar has not been refreshed this period")
    for event in events["events"]:
        # Historical release evidence stays valid; live monitors and the remaining
        # calendar must be checked again, including dates not yet confirmed.
        if event["kind"] != "monitor" and event.get("scheduled_at") is not None:
            if aware_datetime(event["scheduled_at"], "event.scheduled_at") < local:
                continue
        for indicator in event["indicators"]:
            domains = config["indicators"][indicator]["official_domains"]
            require(any(official_host(source["url"], domains)
                        and aware_datetime(source["verified_at"], "event.source") >= boundary
                        for source in event["sources"]),
                    f"{event['id']}: official sources have not been checked this period")
        if event["kind"] == "monitor":
            for observation in event.get("observations", []):
                actual = observation.get("actual")
                if actual is None:
                    continue
                domains = config["indicators"][observation["indicator"]]["official_domains"]
                require(any(official_host(source["url"], domains)
                            and aware_datetime(source["verified_at"], "observation.source") >= boundary
                            for source in actual["sources"]),
                        f"{event['id']}: observation official source has not been checked this period")
    outlook = next(item for item in outlooks if item["period"] == current["period"])
    require(datetime.fromisoformat(outlook["updated_at"].replace("Z", "+00:00")) >= boundary, "Current outlook has not been verified this period")
    for section in outlook["sections"]:
        require(any(aware_datetime(source["verified_at"], "outlook.source") >= boundary for source in section["sources"]),
                f"{section['indicator']}: official/factual sources have not been checked this period")
    entry = {"at": local.isoformat(), "content_fingerprint": fingerprint}
    actuals = content_root / 'actuals.json'
    entry['actuals_fingerprint'] = hashlib.sha256(actuals.read_bytes() if actuals.exists() else b'').hexdigest()
    if phase in {"built", "published", "completed"}:
        entry["outputs"] = output_fingerprint(output_root)
    if phase in {"published", "completed"}:
        require(config_path.resolve() == (repository / "config/stocks.yaml").resolve()
                and content_root.resolve() == (repository / "content/stocks").resolve()
                and output_root.resolve() == (repository / "docs").resolve(),
                "Publication receipts require the repository's canonical stocks source and docs paths")
        built = receipt["phases"].get("built", {})
        require(built.get("content_fingerprint") == fingerprint and built.get("outputs") == entry["outputs"]
                and built.get('actuals_fingerprint') == entry['actuals_fingerprint'],
                "Record built for the current validated content/output before publication completion")
        # Dirty stock source or site outputs are not evidence of the pushed commit.
        dirty = _git(repository, "status", "--porcelain", "--", "src/stocks", "config/stocks.yaml", "content/stocks", "docs/stocks")
        require(not dirty, "Stocks source and generated pages must be committed before remote verification")
        commit = _git(repository, "rev-parse", "HEAD")
        remote = _git(repository, "ls-remote", "origin", "refs/heads/main").split()
        require(bool(remote) and remote[0] == commit, "origin/main does not match the current publication commit; do not mark complete")
        entry.update(commit=commit, remote_commit=remote[0], remote_ref="refs/heads/main")
    receipt.update(phase=phase, updated_at=local.isoformat(), content_fingerprint=fingerprint)
    receipt.pop("reason", None)
    receipt["phases"][phase] = entry
    _json_write(path, receipt)
    return receipt
