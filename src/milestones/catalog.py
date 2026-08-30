"""Load and render the public Milestone Models catalog."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import yaml


CATALOG_VERSION = 1
RELEASE_STATUSES = {"released", "early-access", "announced"}
PAGE_STATUSES = {"ready", "planned"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}$")
SYNTHETIC_ID_PATTERN = re.compile(r"^\d{4}\.\d{2}XXX$")


class MilestoneCatalogError(ValueError):
    """Raised when the tracked milestone catalog is invalid."""


def _required_string(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MilestoneCatalogError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _validate_slug(value: str, context: str) -> None:
    if not SLUG_PATTERN.fullmatch(value):
        raise MilestoneCatalogError(f"{context} has invalid slug: {value}")


def _validate_source(source: Any, context: str) -> None:
    if not isinstance(source, dict):
        raise MilestoneCatalogError(f"{context} must be a mapping")
    _required_string(source, "type", context)
    url = _required_string(source, "url", context)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise MilestoneCatalogError(f"{context}.url must be an absolute HTTPS URL")


def _validate_release(release: Any, context: str) -> None:
    if not isinstance(release, dict):
        raise MilestoneCatalogError(f"{context} must be a mapping")
    slug = _required_string(release, "slug", context)
    _validate_slug(slug, context)
    _required_string(release, "name", context)
    date_value = release.get("release_date")
    if isinstance(date_value, dt.date):
        release["release_date"] = date_value.isoformat()
    elif isinstance(date_value, str):
        try:
            release["release_date"] = dt.date.fromisoformat(date_value).isoformat()
        except ValueError as error:
            raise MilestoneCatalogError(f"{context}.release_date is invalid") from error
    else:
        raise MilestoneCatalogError(f"{context}.release_date must be an ISO date")

    status = _required_string(release, "status", context)
    if status not in RELEASE_STATUSES:
        raise MilestoneCatalogError(f"{context}.status must be one of {sorted(RELEASE_STATUSES)}")
    note_id = _required_string(release, "note_id", context)
    if not (ARXIV_ID_PATTERN.fullmatch(note_id) or SYNTHETIC_ID_PATTERN.fullmatch(note_id)):
        raise MilestoneCatalogError(f"{context}.note_id is not arXiv-like: {note_id}")
    if SYNTHETIC_ID_PATTERN.fullmatch(note_id):
        release_day = dt.date.fromisoformat(release["release_date"])
        if note_id != release_day.strftime("%y%m.%dXXX"):
            raise MilestoneCatalogError(
                f"{context}.note_id must encode release_date as YYMM.DDXXX"
            )

    variants = release.get("variants")
    if not isinstance(variants, list) or not variants:
        raise MilestoneCatalogError(f"{context}.variants must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in variants):
        raise MilestoneCatalogError(f"{context}.variants contains an invalid value")
    sources = release.get("sources")
    if not isinstance(sources, list) or not sources:
        raise MilestoneCatalogError(f"{context}.sources must be a non-empty list")
    for source_index, source in enumerate(sources):
        _validate_source(source, f"{context}.sources[{source_index}]")


def load_milestone_catalog(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate the tracked catalog."""
    catalog_path = Path(path)
    try:
        payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise MilestoneCatalogError(f"Unable to load milestone catalog: {error}") from error
    if not isinstance(payload, dict) or payload.get("version") != CATALOG_VERSION:
        raise MilestoneCatalogError(f"Unsupported milestone catalog: {catalog_path}")
    topics = payload.get("topics")
    if not isinstance(topics, list) or not topics:
        raise MilestoneCatalogError("topics must be a non-empty list")

    topic_names: set[str] = set()
    family_slugs: set[str] = set()
    ready_count = 0
    for topic_index, topic in enumerate(topics):
        context = f"topics[{topic_index}]"
        if not isinstance(topic, dict):
            raise MilestoneCatalogError(f"{context} must be a mapping")
        name = _required_string(topic, "name", context)
        if name in topic_names:
            raise MilestoneCatalogError(f"Duplicate milestone topic: {name}")
        topic_names.add(name)
        families = topic.get("families")
        if not isinstance(families, list) or not families:
            raise MilestoneCatalogError(f"{context}.families must be a non-empty list")
        for family_index, family in enumerate(families):
            family_context = f"{context}.families[{family_index}]"
            if not isinstance(family, dict):
                raise MilestoneCatalogError(f"{family_context} must be a mapping")
            slug = _required_string(family, "slug", family_context)
            _validate_slug(slug, family_context)
            if slug in family_slugs:
                raise MilestoneCatalogError(f"Duplicate family slug: {slug}")
            family_slugs.add(slug)
            _required_string(family, "name", family_context)
            _required_string(family, "organization", family_context)
            page_status = _required_string(family, "page_status", family_context)
            if page_status not in PAGE_STATUSES:
                raise MilestoneCatalogError(
                    f"{family_context}.page_status must be one of {sorted(PAGE_STATUSES)}"
                )
            releases = family.get("releases")
            if not isinstance(releases, list):
                raise MilestoneCatalogError(f"{family_context}.releases must be a list")
            comparison_groups = family.get("comparison_groups", [])
            if not isinstance(comparison_groups, list):
                raise MilestoneCatalogError(
                    f"{family_context}.comparison_groups must be a list"
                )
            if page_status == "ready":
                ready_count += 1
                if not releases:
                    raise MilestoneCatalogError(f"{family_context} is ready without releases")
                if not comparison_groups:
                    raise MilestoneCatalogError(
                        f"{family_context} is ready without comparison_groups"
                    )
            elif releases:
                raise MilestoneCatalogError(f"{family_context} is planned but has releases")
            elif comparison_groups:
                raise MilestoneCatalogError(
                    f"{family_context} is planned but has comparison_groups"
                )
            group_slugs: set[str] = set()
            for group_index, group in enumerate(comparison_groups):
                group_context = f"{family_context}.comparison_groups[{group_index}]"
                if not isinstance(group, dict):
                    raise MilestoneCatalogError(f"{group_context} must be a mapping")
                group_slug = _required_string(group, "slug", group_context)
                _validate_slug(group_slug, group_context)
                if group_slug in group_slugs:
                    raise MilestoneCatalogError(f"Duplicate comparison group: {group_slug}")
                group_slugs.add(group_slug)
                _required_string(group, "name", group_context)
                _required_string(group, "baseline_release", group_context)
            release_slugs: set[str] = set()
            release_groups: dict[str, str] = {}
            previous_date: str | None = None
            for release_index, release in enumerate(releases):
                release_context = f"{family_context}.releases[{release_index}]"
                _validate_release(release, release_context)
                if release["slug"] in release_slugs:
                    raise MilestoneCatalogError(
                        f"Duplicate release slug in {slug}: {release['slug']}"
                    )
                release_slugs.add(release["slug"])
                comparison_group = _required_string(
                    release, "comparison_group", release_context
                )
                if comparison_group not in group_slugs:
                    raise MilestoneCatalogError(
                        f"{release_context}.comparison_group is unknown: {comparison_group}"
                    )
                release_groups[release["slug"]] = comparison_group
                if previous_date and release["release_date"] < previous_date:
                    raise MilestoneCatalogError(f"{family_context}.releases must be chronological")
                previous_date = release["release_date"]
            for group in comparison_groups:
                baseline = group["baseline_release"]
                if baseline not in release_slugs:
                    raise MilestoneCatalogError(
                        f"Comparison group {group['slug']} has unknown baseline: {baseline}"
                    )
                if release_groups[baseline] != group["slug"]:
                    raise MilestoneCatalogError(
                        f"Comparison group {group['slug']} baseline belongs to another group"
                    )
    if ready_count == 0:
        raise MilestoneCatalogError("At least one milestone family must be ready")
    return payload


def iter_families(catalog: dict[str, Any]):
    for topic in catalog["topics"]:
        for family in topic["families"]:
            yield topic, family


def find_family(catalog: dict[str, Any], slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for topic, family in iter_families(catalog):
        if family["slug"] == slug:
            return topic, family
    raise MilestoneCatalogError(f"Unknown milestone family: {slug}")


def first_ready_family(catalog: dict[str, Any]) -> dict[str, Any]:
    for _, family in iter_families(catalog):
        if family["page_status"] == "ready":
            return family
    raise MilestoneCatalogError("No ready milestone family")


def render_milestone_navigation(
    catalog: dict[str, Any], active_family: str
) -> str:
    """Render model-family navigation without duplicating the shared shell."""
    output = ['      <div class="milestone-nav">']
    for topic in catalog["topics"]:
        contains_active = any(family["slug"] == active_family for family in topic["families"])
        open_attribute = " open" if contains_active else ""
        output.append(f'      <details class="nav-theme"{open_attribute}>')
        output.append(f'        <summary><span>{html.escape(topic["name"])}</span></summary>')
        output.append('        <ul class="milestone-family-list">')
        for family in topic["families"]:
            label = html.escape(family["name"])
            if family["page_status"] == "ready":
                active_class = " is-active" if family["slug"] == active_family else ""
                current = ' aria-current="page"' if family["slug"] == active_family else ""
                output.append(
                    f'          <li><a class="milestone-family-link{active_class}" '
                    f'href="{html.escape(family["slug"], quote=True)}.html"{current}>'
                    f'<span>{label}</span><span class="nav-count">跟踪中</span></a></li>'
                )
            else:
                output.append(
                    '          <li><span class="milestone-family-link is-planned" '
                    f'aria-disabled="true"><span>{label}</span>'
                    '<span class="nav-count">规划中</span></span></li>'
                )
        output.extend(["        </ul>", "      </details>"])
    output.append("      </div>")
    return "\n".join(output)
