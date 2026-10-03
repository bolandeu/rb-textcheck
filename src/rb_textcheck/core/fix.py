"""
Автозамены по профилю (textcheck fix, T78 A): механика без LLM.

Что на что менять, решает профиль (секция fixes), а не код: здесь нет ни
одной замены по умолчанию. Замены идут по порядку профиля, каждая - по всему
тексту, следующая видит результат предыдущей.

Меняется только текст, который читает человек:
- HTML - только текстовые узлы; теги, атрибуты (href, alt, title) и порядок
  блоков остаются байт в байт. Текст разбирается как есть, сущности (&mdash;)
  не раскрываются: замена «—» их не трогает;
- md - строки вне блоков кода (``` и ~~~) и frontmatter;
- не трогаются никогда: <code>, <pre>, <script>, <style>, <textarea>,
  `код` в md, адреса ссылок md и голые URL.

where сужает замену: headings - заголовки (h1-h6, md: #), paragraphs -
<p> (md: строки абзацев), lists - <li> (md: пункты списков).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .profile import FixRule, QualityProfile, load_profile
from .text_blocks import BLOCK_TAGS, parse_blocks

FORMATS = ("html", "md")

# Голые URL - не текст, а адрес: тире или ё внутри пути менять нельзя
URL_RE = r"(?:https?|ftp)://[^\s<>\"']+|www\.[^\s<>\"']+"
URL = re.compile(URL_RE)

# --- HTML ------------------------------------------------------------------------

TAG = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<![^>]*>|<\?.*?>"
    r"|</?([A-Za-z][^\s/>]*)(?:[^>\"']|\"[^\"]*\"|'[^']*')*>",
    re.S,
)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
RAW_TEXT = {"script", "style", "textarea"}  # содержимое до закрывающего тега - не разметка и не текст
CODE = {"code", "pre", "kbd", "samp", *RAW_TEXT}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
WHERE_TAGS = {"headings": HEADINGS, "paragraphs": {"p"}, "lists": {"li"}}


@dataclass
class Segment:
    """Кусок исходника: текст (можно менять) или нет, где он и в каком блоке."""

    text: str
    editable: bool
    where: frozenset[str] = frozenset()
    block: int | None = None  # html: номер блока (text_blocks), md: номер строки


def _html_segments(raw: str) -> Iterator[Segment]:
    stack: list[str] = []
    blocks: list[int] = []  # номера открытых блоков, параллельно stack
    block_count = 0
    pos = 0
    while pos < len(raw):
        match = TAG.search(raw, pos)
        end = match.start() if match else len(raw)
        if end > pos:
            names = set(stack)
            where = frozenset(w for w, tags in WHERE_TAGS.items() if names & tags)
            yield Segment(raw[pos:end], editable=not (names & CODE), where=where, block=blocks[-1] if blocks else None)
        if not match:
            break
        tag = match.group(0)
        yield Segment(tag, editable=False)
        pos = match.end()
        name = (match.group(1) or "").lower()
        if not name:
            continue  # комментарий, doctype
        if tag.startswith("</"):
            if name in stack:
                while stack:
                    closed = stack.pop()
                    if (blocks and blocks[-1] < 0) or closed in BLOCK_TAGS:
                        blocks.pop()
                    if closed == name:
                        break
            continue
        if name in VOID or tag.endswith("/>"):
            continue
        if name in RAW_TEXT:
            close = re.compile(rf"</{name}\s*>", re.I).search(raw, pos)
            stop = close.start() if close else len(raw)
            yield Segment(raw[pos:stop], editable=False)
            pos = stop
            continue
        stack.append(name)
        if name in BLOCK_TAGS:
            blocks.append(block_count)
            block_count += 1


# --- markdown --------------------------------------------------------------------

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
MD_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s|$)")
MD_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
MD_TABLE = re.compile(r"^\s*\|")
# Внутри строки md не текст: `код`, картинка целиком, адрес ссылки, автоссылка, HTML-тег, URL
MD_PROTECTED = re.compile(r"(`+).+?\1|!\[[^\]]*\]\([^)]*\)|\]\([^)]*\)|<[^>\s]+>|" + URL_RE)


def _md_segments(raw: str) -> Iterator[Segment]:
    lines = raw.splitlines(keepends=True)
    fence: str | None = None
    frontmatter = bool(lines) and lines[0].strip() == "---"
    for number, line in enumerate(lines, 1):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if frontmatter:
            yield Segment(line, editable=False)
            if number > 1 and body.strip() == "---":
                frontmatter = False
            continue
        opened = FENCE.match(body)
        if fence is not None or opened:
            yield Segment(line, editable=False)
            if fence is None and opened:
                fence = opened.group(1)[0] * 3
            elif fence is not None and body.strip().startswith(fence):
                fence = None
            continue
        if MD_HEADING.match(body):
            where = frozenset({"headings"})
        elif MD_LIST.match(body):
            where = frozenset({"lists"})
        elif body.strip() and not MD_TABLE.match(body):
            where = frozenset({"paragraphs"})
        else:
            where = frozenset()
        pos = 0
        for match in MD_PROTECTED.finditer(body):
            if match.start() > pos:
                yield Segment(body[pos : match.start()], editable=True, where=where, block=number)
            yield Segment(match.group(0), editable=False)
            pos = match.end()
        if pos < len(body):
            yield Segment(body[pos:], editable=True, where=where, block=number)
        if ending:
            yield Segment(ending, editable=False)


# --- замены ----------------------------------------------------------------------


@dataclass
class Applied:
    """Сработавшая замена: сколько раз и в каких блоках (html) или строках (md)."""

    name: str
    count: int
    addresses: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "count": self.count, "addresses": self.addresses}


@dataclass
class FixResult:
    """Итог fix: текст после всех замен, сработавшие замены, изменился ли текст."""

    text: str
    applied: list[Applied]
    unchanged: bool

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "applied": [a.as_dict() for a in self.applied], "unchanged": self.unchanged}


def _apply(raw: str, rule: FixRule, segments: Callable[[str], Iterator[Segment]]) -> tuple[str, int, list[int]]:
    """Одна замена по всему тексту: (текст, число замен, затронутые блоки/строки по порядку)."""
    out: list[str] = []
    count = 0
    touched: list[int] = []
    for segment in segments(raw):
        if not segment.editable or (rule.where != "text" and rule.where not in segment.where):
            out.append(segment.text)
            continue
        # URL внутри текста остаётся как есть: заменяется только то, что между ними
        pieces = URL.split(segment.text)
        urls = URL.findall(segment.text)
        for i, piece in enumerate(pieces):
            replaced, n = rule.apply(piece)
            out.append(replaced)
            count += n
            if n and segment.block is not None and segment.block not in touched:
                touched.append(segment.block)
            if i < len(urls):
                out.append(urls[i])
    return "".join(out), count, touched


def fix(
    text: str, profile: str | Path | dict[str, Any] | QualityProfile | None = None, format: str = "html"
) -> FixResult:
    """
    Применяет замены профиля (fixes) по порядку.

    Raises:
        ProfileError: профиль не разбирается (в том числе битый regex или шаблон замены).
        ValueError: формат не html и не md.
    """
    if format not in FORMATS:
        raise ValueError(f"формат {format!r} не поддерживается: {', '.join(FORMATS)}")
    rules = load_profile(profile).require_article().fixes
    segments = _html_segments if format == "html" else _md_segments
    result = text
    touched_by_rule: list[tuple[str, int, list[int]]] = []
    for rule in rules:
        result, count, touched = _apply(result, rule, segments)
        if count:
            touched_by_rule.append((rule.name, count, touched))

    # Адреса - по итоговому тексту: блок с номером и якорем после всех замен
    blocks = parse_blocks(result) if format == "html" else []
    applied = []
    for name, count, touched in touched_by_rule:
        if format == "html":
            addresses = [blocks[i].address() for i in touched if i < len(blocks)]
        else:
            addresses = [{"line": line} for line in touched]
        applied.append(Applied(name=name, count=count, addresses=addresses))
    return FixResult(text=result, applied=applied, unchanged=result == text)
