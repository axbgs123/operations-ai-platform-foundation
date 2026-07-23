from dataclasses import dataclass
import re


_CHAPTER = re.compile(r"^(第[一二三四五六七八九十百千0-9]+章)(?:\s+|$)")
_CLAUSE = re.compile(r"^(第[一二三四五六七八九十百千0-9]+条)(?:\s+|$)")


@dataclass(frozen=True)
class RiskChunkDraft:
    chunk_index: int
    source_location: str
    text: str


def chunk_document(
    text: str,
    *,
    max_chars: int = 1200,
) -> list[RiskChunkDraft]:
    if max_chars < 16:
        raise ValueError("max_chars must be at least 16")

    blocks: list[tuple[str, str]] = []
    chapter: str | None = None
    clause: str | None = None
    lines: list[str] = []
    preamble_index = 0

    def flush() -> None:
        nonlocal lines, preamble_index
        if not lines:
            return
        if clause is not None:
            location = f"{chapter} > {clause}" if chapter else clause
        elif chapter is not None:
            preamble_index += 1
            location = f"{chapter} > preamble-{preamble_index}"
        else:
            preamble_index += 1
            location = f"document > preamble-{preamble_index}"
        blocks.append((location, "\n".join(lines)))
        lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            clause = None
            continue
        chapter_match = _CHAPTER.match(line)
        if chapter_match is not None:
            flush()
            chapter = line
            clause = None
            continue
        clause_match = _CLAUSE.match(line)
        if clause_match is not None:
            flush()
            clause = clause_match.group(1)
            lines = [line]
            continue
        lines.append(line)
    flush()

    drafts: list[RiskChunkDraft] = []
    for location, block in blocks:
        parts = [
            block[offset : offset + max_chars]
            for offset in range(0, len(block), max_chars)
        ]
        for part_index, part in enumerate(parts, start=1):
            part_location = (
                location
                if len(parts) == 1
                else f"{location}#part-{part_index}"
            )
            drafts.append(
                RiskChunkDraft(
                    chunk_index=len(drafts),
                    source_location=part_location,
                    text=part,
                )
            )
    return drafts
