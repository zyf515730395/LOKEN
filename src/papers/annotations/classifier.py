"""Strict local-model paper classification with an independent cache."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import threading

from papers.summaries.models import AcquiredPaper
from papers.summaries.paths import private_path
from shared.loopback_chat import LoopbackChatError, LoopbackChatTransport

from .catalog import annotation_from_value
from .models import LabelDefinition, PaperAnnotation, PaperAnnotationError
from .prompts import PROMPT_VERSION, TRANSPORT_VERSION, annotation_messages


CACHE_VERSION = 1


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def parse_annotation(raw: str, labels: tuple[LabelDefinition, ...]) -> PaperAnnotation:
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return annotation_from_value("model output", value, labels)
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError, PaperAnnotationError):
        raise PaperAnnotationError("invalid_annotation", "model output violates the annotation contract") from None


def taxonomy_hash(labels: tuple[LabelDefinition, ...]) -> str:
    return hashlib.sha256(
        _canonical([{"name": label.name, "description": label.description} for label in labels])
    ).hexdigest()


def annotation_cache_key(source_sha256: str, model: str, labels: tuple[LabelDefinition, ...]) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "source_sha256": source_sha256,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "taxonomy_hash": taxonomy_hash(labels),
                "transport_version": TRANSPORT_VERSION,
            }
        )
    ).hexdigest()


class PaperAnnotationCache:
    def path_for(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("invalid annotation cache key")
        return private_path("annotation-cache", key[:2], f"{key}.json")

    def load(self, key: str, labels: tuple[LabelDefinition, ...]) -> PaperAnnotation | None:
        try:
            raw = self.path_for(key).read_bytes()
            if len(raw) > 32 * 1024:
                return None
            envelope = json.loads(raw.decode("utf-8", errors="strict"))
            if not isinstance(envelope, dict) or set(envelope) != {"version", "key", "result", "checksum"} or raw != _canonical(envelope) + b"\n":
                return None
            body = {"version": envelope["version"], "key": envelope["key"], "result": envelope["result"]}
            if envelope["version"] != CACHE_VERSION or envelope["key"] != key or not hmac.compare_digest(str(envelope["checksum"]), hashlib.sha256(_canonical(body)).hexdigest()):
                return None
            return annotation_from_value("cache", envelope["result"], labels)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, RecursionError, PaperAnnotationError):
            return None

    def store(self, key: str, annotation: PaperAnnotation) -> Path:
        result = {"tags": list(annotation.tags), "paper_type": annotation.paper_type}
        body = {"version": CACHE_VERSION, "key": key, "result": result}
        envelope = {**body, "checksum": hashlib.sha256(_canonical(body)).hexdigest()}
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            with temporary.open("wb") as stream:
                stream.write(_canonical(envelope) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return path


def classify_paper(
    paper: AcquiredPaper,
    labels: tuple[LabelDefinition, ...],
    *,
    model: str,
    base_url: str,
    timeout: float,
    refresh: bool = False,
    cache: PaperAnnotationCache | None = None,
) -> PaperAnnotation:
    annotation_cache = cache or PaperAnnotationCache()
    key = annotation_cache_key(paper.source_sha256, model, labels)
    if not refresh and (cached := annotation_cache.load(key, labels)) is not None:
        return cached
    abstract = " ".join(paper.document.abstract.split())
    if not 40 <= len(abstract) <= 16_000:
        raise PaperAnnotationError("annotation_evidence_invalid", "paper abstract is unavailable or outside limits")
    try:
        transport = LoopbackChatTransport(base_url)
        raw = transport.complete(
            annotation_messages(paper.document.title, abstract, labels),
            model=model,
            timeout=timeout,
        )
    except LoopbackChatError as error:
        raise PaperAnnotationError(error.code, error.message) from None
    annotation = parse_annotation(raw, labels)
    annotation_cache.store(key, annotation)
    return annotation
