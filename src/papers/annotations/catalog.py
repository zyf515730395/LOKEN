"""Label configuration and the public annotation catalog."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace
import re
import unicodedata

import yaml

from papers.candidate_ledger import atomic_write_json, normalize_arxiv_id

from .models import LabelDefinition, PaperAnnotation, PaperAnnotationError


CATALOG_VERSION = 2
ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}$")
ARCHIVE_TITLE = re.compile(r"^\|\*\*[^*]+\*\*\|\*\*(?P<title>.*?)\*\*\|")


def label_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def parse_label_definitions(raw: object) -> tuple[LabelDefinition, ...]:
    if not isinstance(raw, list) or not raw:
        raise PaperAnnotationError("invalid_label_config", "paper_labels must be a non-empty list")
    labels: list[LabelDefinition] = []
    names: set[str] = set()
    slugs: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or not {"name", "description"} <= set(item) or set(item) - {"name", "description", "aliases"}:
            raise PaperAnnotationError("invalid_label_config", "each paper label needs name and description")
        name = item["name"]
        description = item["description"]
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or not isinstance(description, str)
            or not 1 <= len(description.strip()) <= 800
            or any(character in name for character in "<>\r\n")
            or any(character in description for character in "<>\r")
        ):
            raise PaperAnnotationError("invalid_label_config", "paper label text is invalid")
        name = " ".join(name.split())
        description = " ".join(description.split())
        slug = label_slug(name)
        if not slug or name in names or slug in slugs:
            raise PaperAnnotationError("invalid_label_config", "paper label names and slugs must be unique")
        names.add(name)
        slugs.add(slug)
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() for a in aliases):
            raise PaperAnnotationError("invalid_label_config", "topic aliases must be strings")
        labels.append(LabelDefinition(name, description, slug, aliases=tuple(aliases)))
    return tuple(labels)


def load_label_definitions(config_path: str | Path) -> tuple[LabelDefinition, ...]:
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise PaperAnnotationError("invalid_label_config", "site configuration cannot be read") from None
    if not isinstance(payload, dict):
        raise PaperAnnotationError("invalid_label_config", "site configuration must be a mapping")
    return parse_label_definitions(payload.get("paper_labels"))


def load_annotation_definitions(config_path: str | Path) -> tuple[LabelDefinition, ...]:
    topics = load_label_definitions(config_path)
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    groups = payload.get("paper_tag_groups", {})
    if not isinstance(groups, dict) or set(groups) - {"method", "task", "representation"}:
        raise PaperAnnotationError("invalid_label_config", "invalid tag groups")
    details = tuple(replace(label, group=group) for group, raw in groups.items()
                    for label in parse_label_definitions(raw))
    # A task may intentionally share a topic name (Depth Estimation/Relighting).
    if len({x.name for x in details}) != len(details) or len({x.slug for x in details}) != len(details):
        raise PaperAnnotationError("invalid_label_config", "duplicate detail tags")
    alias_owners = {}
    for topic in topics:
        for name in (topic.name, *topic.aliases):
            if name in alias_owners and alias_owners[name] != topic.name:
                raise PaperAnnotationError("invalid_label_config", "ambiguous topic alias")
            alias_owners[name] = topic.name
    return (*topics, *details)


def migrate_annotation(value: dict, labels: tuple[LabelDefinition, ...]) -> dict:
    aliases = {alias: x.name for x in labels if x.group == "topic" for alias in (x.name, *x.aliases)}
    return {"topics": list(dict.fromkeys(aliases[t] for t in value["tags"] if t in aliases)),
            "tags": [], "paper_type": value["paper_type"], "institutions": []}


def annotation_value(value: PaperAnnotation) -> dict:
    return {"topics": list(value.topics), "tags": list(value.tags),
            "paper_type": value.paper_type, "institutions": list(value.institutions)}


def annotation_from_value(
    paper_id: str,
    value: object,
    labels: tuple[LabelDefinition, ...],
) -> PaperAnnotation:
    def fail():
        raise PaperAnnotationError("invalid_annotation_catalog", f"invalid annotation: {paper_id}")
    if not isinstance(value, dict) or set(value) != {"topics", "tags", "paper_type", "institutions"}:
        fail()
    for field, allowed in (("topics", {x.name for x in labels if x.group == "topic"}),
                           ("tags", {x.name for x in labels if x.group != "topic"})):
        values = value[field]
        if not isinstance(values, list) or any(not isinstance(t, str) or t not in allowed for t in values) or len(values) != len(set(values)):
            fail()
    if value["paper_type"] not in ("paper", "survey"):
        fail()
    institutions = value["institutions"]
    if not isinstance(institutions, list) or len(institutions) > 30 or any(
        not isinstance(x, str) or not 1 <= len(x.strip()) <= 400 or x != " ".join(x.split())
        or any(c in x for c in "<>\r\n") for x in institutions
    ) or len(institutions) != len(set(institutions)):
        fail()
    topics = tuple(x.name for x in labels if x.group == "topic" and x.name in value["topics"])
    tags = tuple(x.name for x in labels if x.group != "topic" and x.name in value["tags"])
    return PaperAnnotation(topics, tags, value["paper_type"], tuple(institutions))


def load_annotation_catalog(
    path: str | Path,
    labels: tuple[LabelDefinition, ...],
) -> dict[str, PaperAnnotation]:
    source = Path(path)
    if not source.exists():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise PaperAnnotationError("invalid_annotation_catalog", "annotation catalog cannot be read") from None
    if not isinstance(payload, dict) or set(payload) != {"version", "papers"} or payload["version"] not in (1, CATALOG_VERSION) or not isinstance(payload["papers"], dict):
        raise PaperAnnotationError("invalid_annotation_catalog", "annotation catalog schema is invalid")
    result: dict[str, PaperAnnotation] = {}
    for paper_id, value in payload["papers"].items():
        if normalize_arxiv_id(paper_id) != paper_id or not ARXIV_ID.fullmatch(paper_id):
            raise PaperAnnotationError("invalid_annotation_catalog", f"invalid arXiv ID: {paper_id}")
        if payload["version"] == 1:
            if not isinstance(value, dict) or set(value) != {"tags", "paper_type"} or not isinstance(value["tags"], list) or any(not isinstance(t, str) for t in value["tags"]):
                raise PaperAnnotationError("invalid_annotation_catalog", f"invalid legacy annotation: {paper_id}")
            value = migrate_annotation(value, labels)
        result[paper_id] = annotation_from_value(paper_id, value, labels)
    return result


def write_annotation_catalog(path: str | Path, annotations: dict[str, PaperAnnotation]) -> None:
    atomic_write_json(
        path,
        {
            "version": CATALOG_VERSION,
            "papers": {
                paper_id: annotation_value(value)
                for paper_id, value in sorted(annotations.items())
            },
        },
    )


def archive_paper_ids(archive: dict[str, dict[str, object]]) -> set[str]:
    return {normalize_arxiv_id(paper_id) for entries in archive.values() for paper_id in entries}


def annotation_coverage(
    archive: dict[str, dict[str, object]],
    annotations: dict[str, PaperAnnotation],
) -> dict[str, int]:
    paper_ids = archive_paper_ids(archive)
    annotated = len(paper_ids & annotations.keys())
    return {"total": len(paper_ids), "annotated": annotated, "pending": len(paper_ids) - annotated}


def archive_titles(archive: dict[str, dict[str, object]]) -> dict[str, tuple[str, tuple[str, ...]]]:
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    topic_sets: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    for topic, entries in archive.items():
        for raw_id, row in entries.items():
            paper_id = normalize_arxiv_id(raw_id)
            if not isinstance(row, str) or not (match := ARCHIVE_TITLE.match(row)):
                raise PaperAnnotationError("invalid_archive", f"invalid archive row: {paper_id}")
            title = " ".join(match.group("title").split())
            if paper_id in titles and titles[paper_id] != title:
                raise PaperAnnotationError("invalid_archive", f"conflicting archive title: {paper_id}")
            titles[paper_id] = title
            topic_sets.setdefault(paper_id, [])
            if topic not in topic_sets[paper_id]:
                topic_sets[paper_id].append(topic)
    for paper_id, title in titles.items():
        result[paper_id] = (title, tuple(topic_sets[paper_id]))
    return result
