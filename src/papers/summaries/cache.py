"""Checksummed private cache for validated paper summaries."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

from .extraction import EXTRACTION_VERSION
from .models import PaperSummary
from .paths import private_path
from .prompts import PROMPT_VERSION, TRANSPORT_VERSION


CACHE_VERSION = 1


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def cache_key(source_sha256: str, model: str) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "source_sha256": source_sha256,
                "extraction_version": EXTRACTION_VERSION,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "transport_version": TRANSPORT_VERSION,
            }
        )
    ).hexdigest()


class PaperSummaryCache:
    def path_for(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("invalid paper summary cache key")
        return private_path("cache", key[:2], f"{key}.json")

    def load(self, key: str) -> PaperSummary | None:
        try:
            raw = self.path_for(key).read_bytes()
        except OSError:
            return None
        if len(raw) > 64 * 1024:
            return None
        try:
            envelope = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(envelope, dict) or set(envelope) != {"version", "key", "result", "checksum"}:
            return None
        if raw != _canonical(envelope) + b"\n":
            return None
        body = {"version": envelope["version"], "key": envelope["key"], "result": envelope["result"]}
        checksum = hashlib.sha256(_canonical(body)).hexdigest()
        if envelope["version"] != CACHE_VERSION or envelope["key"] != key or not hmac.compare_digest(str(envelope["checksum"]), checksum):
            return None
        result = envelope["result"]
        if (
            not isinstance(result, dict)
            or set(result) != {"one_sentence", "problem", "contributions"}
            or not isinstance(result["contributions"], list)
        ):
            return None
        try:
            return PaperSummary(
                one_sentence=result["one_sentence"],
                problem=result["problem"],
                contributions=tuple(result["contributions"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def store(self, key: str, result: PaperSummary) -> Path:
        body = {
            "version": CACHE_VERSION,
            "key": key,
            "result": {
                "one_sentence": result.one_sentence,
                "problem": result.problem,
                "contributions": list(result.contributions),
            },
        }
        envelope = {**body, "checksum": hashlib.sha256(_canonical(body)).hexdigest()}
        data = _canonical(envelope) + b"\n"
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        try:
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return path
