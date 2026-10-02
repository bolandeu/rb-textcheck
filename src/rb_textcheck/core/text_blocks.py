"""
Адреса блоков: находка указывает на блок статьи так, чтобы правщик нашёл тот
же блок, даже если статью между проверкой и правкой успели тронуть.

Перенос из antagor (utils/text_blocks.py, коммит 9a5e4d8) - только то, что
нужно проверке: разбор на блоки, якорь и поиск блока по фрагменту. Правка
блоков (replace/insert/drop) остаётся у правщика.

Адрес = номер блока + якорь (+ цитата):

    {"block": 13, "anchor": "a3f9c2d1", "quote": "тюль + портьеры"}

Номер даёт быстрый доступ, якорь (хэш нормализованного текста блока) проверяет,
что это тот самый блок.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

# Блочные элементы - границы адресации. Заголовки входят: их тоже правят.
# td/th - иначе нарушение внутри таблицы не адресуется вовсе (antagor
# 2026-09-24, 3505: «знак вместо союза» в ячейке таблицы).
BLOCK_TAGS = ["p", "li", "h2", "h3", "h4", "blockquote", "td", "th"]


@dataclass
class Block:
    """Адресуемый участок статьи."""

    index: int
    tag: str
    text: str

    @property
    def anchor(self) -> str:
        """Хэш нормализованного текста - опознаёт блок, даже если он сместился."""
        return anchor_for(self.text)

    def address(self, quote: str = "") -> dict[str, Any]:
        """Адрес этого блока - то, что кладётся в находку."""
        address: dict[str, Any] = {"block": self.index, "anchor": self.anchor}
        if quote:
            address["quote"] = quote
        return address


def normalize(text: str) -> str:
    """Текст без разницы в пробелах и регистре - основа якоря и поиска цитат."""
    return re.sub(r"\s+", " ", text).strip().lower()


def anchor_for(text: str) -> str:
    """
    Якорь блока - первые 8 символов md5 от нормализованного текста.

    Берётся весь текст блока, а не префикс: префикс совпадает у однотипных
    пунктов списка, и адрес указывал бы на соседа.
    """
    return hashlib.md5(normalize(text).encode("utf-8")).hexdigest()[:8]  # noqa: S324 - якорь, не защита


def parse_blocks(html: str) -> list[Block]:
    """Разбирает статью на адресуемые блоки в порядке появления."""
    soup = BeautifulSoup(html, "html.parser")
    return [
        Block(index=i, tag=tag.name, text=tag.get_text(" ", strip=True))
        for i, tag in enumerate(soup.find_all(BLOCK_TAGS))
    ]


def locate_quote(blocks: list[Block], quote: str) -> Block | None:
    """Блок, содержащий цитату - для находок, у которых есть только фрагмент."""
    needle = normalize(quote)
    if not needle:
        return None

    for block in blocks:
        if needle in normalize(block.text):
            return block

    # Дальше - поиск по частям. Фрагмент из проверки берётся как ±45 символов
    # вокруг совпадения по плоскому тексту ВСЕЙ статьи, поэтому он начинается
    # обрывком слова и может лечь через границу блоков. Целиком такой фрагмент
    # не найдётся нигде, но какая-то его словесная середина лежит внутри одного
    # блока. Ищем самую длинную последовательность целых слов фрагмента,
    # которая целиком лежит в каком-то блоке: чем она длиннее, тем меньше шанс
    # попасть в чужой абзац с похожей формулировкой.
    words = needle.split()
    for span in range(len(words), 2, -1):
        for start in range(len(words) - span + 1):
            candidate = " ".join(words[start : start + span])
            if len(candidate) < 12:
                continue
            for block in blocks:
                if candidate in normalize(block.text):
                    return block

    return None
