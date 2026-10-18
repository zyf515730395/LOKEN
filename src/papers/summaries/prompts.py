"""Bounded prompts for evidence-grounded paper map-reduce."""

from __future__ import annotations

import json

from .extraction import extract_introduction
from .models import PaperDocument, PaperSummary, PaperSummaryError


PROMPT_VERSION = "paper-summary-v2"
TRANSPORT_VERSION = "loopback-chat-v1"
MAX_CHUNK_CHARS = 18_000
MAX_CHUNKS = 32


def build_chunks(document: PaperDocument, *, evidence_text: str | None = None) -> tuple[str, ...]:
    introduction = extract_introduction(document) if evidence_text is None else evidence_text
    chunks = [
        introduction[index : index + MAX_CHUNK_CHARS]
        for index in range(0, len(introduction), MAX_CHUNK_CHARS)
    ]
    if not chunks or len(chunks) > MAX_CHUNKS:
        raise PaperSummaryError(
            "paper_chunk_limit", "paper cannot fit the bounded model workflow"
        )
    return tuple(chunks)


def map_messages(title: str, chunk: str, *, evidence_basis: str = 'introduction') -> tuple[dict[str, str], ...]:
    return (
        {
            "role": "system",
            "content": (
                "你是技术论文精读助手。只依据用户提供的论文片段，用中文输出严格 JSON，"
                "字段必须且只能是 one_sentence、problem、contributions。contributions 必须是 3 到 6 条字符串。"
                "缺少证据时明确说明片段未提供，不得补充外部事实。"
            ),
        },
        {"role": "user", "content": f"论文标题：{title}\n\n材料类型：{evidence_basis}；仅依据以下实际原文，缺失部分明确保留限定。\n论文原文片段：\n{chunk}"},
    )


def reduce_messages(
    title: str, summaries: tuple[PaperSummary, ...]
) -> tuple[dict[str, str], ...]:
    payload = [
        {
            "one_sentence": value.one_sentence,
            "problem": value.problem,
            "contributions": list(value.contributions),
        }
        for value in summaries
    ]
    return (
        {
            "role": "system",
            "content": (
                "合并同一篇论文的分片结论。去重，只保留有证据的结论；保留原文未提供证据的限定，不得将未知改写成已知。"
                "输出严格 JSON，字段只能是 one_sentence、problem、contributions，创新点 3 到 6 条。"
            ),
        },
        {
            "role": "user",
            "content": f"论文标题：{title}\n\n分片结论：\n{json.dumps(payload, ensure_ascii=False)}",
        },
    )
