"""Strict public-content contracts; no market data is inferred or fetched here."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml


SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
YIELDS = {"treasury_2y", "treasury_10y"}
INDICATORS = {"cpi", "core_cpi", "pce", "core_pce", "nonfarm", "unemployment", "fomc", *YIELDS}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def aware_datetime(value: object, context: str) -> datetime:
    require(isinstance(value, str), f"{context}: expected ISO datetime string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{context}: invalid ISO datetime") from error
    require(result.tzinfo is not None and result.utcoffset() is not None, f"{context}: timezone required")
    return result


def text(value: object, context: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{context}: nonempty text required")
    return value


def valid_url(value: object, context: str) -> str:
    url = text(value, context)
    try:
        parsed = urlsplit(url)
        require(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password,
                f"{context}: public HTTPS URL required")
        require(parsed.port in (None, 443), f"{context}: unsupported port")
    except ValueError as error:
        raise ValueError(f"{context}: invalid public HTTPS URL") from error
    return url


def official_host(url: str, domains: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def sources(value: object, context: str, domains: list[str] | None = None) -> list[dict]:
    require(isinstance(value, list) and bool(value), f"{context}: sources required")
    for source in value:
        require(isinstance(source, dict), f"{context}: source object required")
        text(source.get("title"), context + ".title")
        url = valid_url(source.get("url"), context + ".url")
        aware_datetime(source.get("verified_at"), context + ".verified_at")
        if domains:
            require(official_host(url, domains), f"{context}: expected official domains {domains}")
    return value


def evidence(value: object, context: str) -> None:
    if value is None:
        return
    require(isinstance(value, dict), f"{context}: null or evidence object required")
    fact = value.get("value")
    require(isinstance(fact, (str, int, float)) and not isinstance(fact, bool), f"{context}: value required")
    if isinstance(fact, str):
        text(fact, context + ".value")
    elif isinstance(fact, float):
        require(math.isfinite(fact), f"{context}: finite value required")
    text(value.get("unit"), context + ".unit")
    sources(value.get("sources"), context + ".sources")


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    require(isinstance(value, dict), f"{path}: object required")
    return value


def load_config(path: Path) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    require(isinstance(config, dict) and config.get("schema_version") == 1, "stocks config: schema_version must be 1")
    require(config.get("timezone") == "Asia/Shanghai" and config.get("event_timezone") == "America/New_York",
            "stocks config: explicit Shanghai/New York timezones required")
    require(config.get("update") == {"weekday": "sunday", "hour": 8}, "stocks config: weekly Sunday 08:00 contract required")
    indicators = config.get("indicators")
    require(isinstance(indicators, dict) and set(indicators) == INDICATORS, "stocks config: expected the supported indicator set")
    for key, item in indicators.items():
        text(item.get("label"), key + ".label")
        require(isinstance(item.get("official_domains"), list) and bool(item["official_domains"]), key + ": official domains required")
        for source in item.get("sources", []):
            valid_url(source.get("url"), key + ".source")
    return config


def validate_events(document: dict, config: dict) -> None:
    require(document.get("schema_version") == 1, "events: schema_version must be 1")
    aware_datetime(document.get("updated_at"), "events.updated_at")
    items = document.get("events")
    require(isinstance(items, list), "events: list required")
    ids = set()
    for event in items:
        require(isinstance(event, dict), "event: object required")
        identifier = text(event.get("id"), "event.id")
        require(bool(IDENTIFIER.fullmatch(identifier)) and identifier not in ids, f"event.id: invalid or duplicate {identifier}")
        ids.add(identifier)
        text(event.get("title"), identifier + ".title")
        indicators = event.get("indicators")
        require(isinstance(indicators, list) and bool(indicators) and all(key in INDICATORS for key in indicators), identifier + ": unknown indicators")
        require(len(indicators) == len(set(indicators)), identifier + ": duplicate indicators")
        require(event.get("timezone") == "America/New_York", identifier + ": America/New_York required")
        kind = event.get("kind")
        require(kind in {"release", "meeting", "monitor"}, identifier + ": unknown kind")
        if kind == "monitor":
            require(set(indicators) <= YIELDS and event.get("scheduled_at") is None, identifier + ": yields are continuous, unscheduled observations")
        else:
            require(not (set(indicators) & YIELDS), identifier + ": yields cannot have scheduled releases")
            if event.get("scheduled_at") is not None:
                instant = aware_datetime(event["scheduled_at"], identifier + ".scheduled_at")
                local = instant.astimezone(NEW_YORK)
                require(instant.utcoffset() == local.utcoffset(), identifier + ": scheduled_at offset disagrees with New York DST")
            require((kind == "meeting") == (set(indicators) == {"fomc"}), identifier + ": FOMC uses meeting; other indicators use release")
        for key in indicators:
            sources(event.get("sources"), identifier + ".sources", config["indicators"][key]["official_domains"])
        observations = event.get("observations", [])
        require(isinstance(observations, list), identifier + ": observations list required")
        seen = set()
        for observation in observations:
            require(isinstance(observation, dict), identifier + ": observation object required")
            key = observation.get("indicator")
            require(key in indicators and key not in seen, identifier + ": invalid/duplicate observation indicator")
            seen.add(key)
            for field in ("actual", "consensus", "previous"):
                evidence(observation.get(field), identifier + "." + key + "." + field)


def validate_outlook(document: dict, config: dict, path: Path) -> None:
    require(document.get("schema_version") == 1, f"{path}: schema_version must be 1")
    aware_datetime(document.get("updated_at"), str(path) + ".updated_at")
    period = date.fromisoformat(document.get("period", ""))
    require(period.weekday() == 6 and path.stem == period.isoformat(), f"{path}: Sunday period must match filename")
    require(document.get("week_start") == (period + timedelta(days=1)).isoformat(), f"{path}: week_start must be following Monday")
    require(document.get("week_end") == (period + timedelta(days=7)).isoformat(), f"{path}: week_end must be following Sunday")
    text(document.get("title"), str(path) + ".title")
    sections = document.get("sections")
    require(isinstance(sections, list) and bool(sections), f"{path}: sections required")
    seen = set()
    for section in sections:
        require(isinstance(section, dict), f"{path}: section object required")
        key = section.get("indicator")
        covered = section.get("indicators", [key])
        require(isinstance(covered, list) and bool(covered) and key in covered
                and all(item in INDICATORS and item not in seen for item in covered),
                f"{path}: unknown/duplicate indicators {covered}")
        seen.update(covered)
        evidence(section.get("expectation"), f"{path}.{key}.expectation")
        sources(section.get("sources"), f"{path}.{key}.sources")
        scenarios = section.get("scenarios")
        require(isinstance(scenarios, dict) and set(scenarios) == {"upside", "base", "downside"}, f"{path}.{key}: three scenarios required")
        for label, scenario in scenarios.items():
            require(isinstance(scenario, dict), f"{path}.{key}.{label}: scenario object required")
            text(scenario.get("condition"), f"{path}.{key}.{label}.condition")
            text(scenario.get("implication"), f"{path}.{key}.{label}.implication")
    require(seen == INDICATORS, f"{path}: outlook must cover every supported indicator")


def load_public_content(config_path: Path, content_root: Path) -> tuple[dict, dict, list[dict]]:
    config = load_config(config_path)
    events_path = content_root / "events.json"
    events = read_json(events_path) if events_path.exists() else {"schema_version": 1, "updated_at": datetime.now(SHANGHAI).isoformat(), "events": []}
    validate_events(events, config)
    actuals_path = content_root / 'actuals.json'
    if actuals_path.exists():
        from .actuals import merge_actuals
        events = merge_actuals(events, read_json(actuals_path), config)
    outlooks = []
    for path in sorted((content_root / "outlooks").glob("*.json")):
        outlook = read_json(path)
        validate_outlook(outlook, config, path)
        outlooks.append(outlook)
    return config, events, outlooks


def content_fingerprint(config_path: Path, content_root: Path) -> str:
    digest = hashlib.sha256()
    paths = [config_path, content_root / "events.json", *sorted((content_root / "outlooks").glob("*.json"))]
    for path in paths:
        digest.update(path.name.encode())
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def latest_due(now: datetime | None = None) -> date:
    local = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    period = local.date() - timedelta(days=(local.weekday() + 1) % 7)
    if local.date() == period and local.hour < 8:
        period -= timedelta(days=7)
    return period
