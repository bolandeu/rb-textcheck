"""
Профиль качества (quality.yml) - контракт на текст: что проверять и с какими порогами.

Перенос из antagor (utils/quality_profile.py, коммит 9a5e4d8), формат тот же.
Профили - данные компонента prompts; здесь только чтение и проверка.

Два слоя, второй переопределяет первый **по отдельным ключам**, а не заменяет
секцию целиком:

1. встроенные дефолты - только непредметное: валидность разметки, ERROR
   humanizer как гейт, остатки плейсхолдеров и артефакты чат-бота. Ни длины в
   символах, ни пошлин, ни сроков доставки здесь быть не должно: запуск без
   профиля обязан давать честную базовую проверку («текст целый и не
   машинный»), а не чужие пороги;
2. профиль - только предметное: длина, чёрный список тегов, произвольные
   запреты, пороги.

Секции grounding, judge_model и generation входят в формат (их читает
antagor: LLM-судья и промт генерации), но textcheck их не применяет.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from re import Pattern
from typing import Any

import jsonschema
import yaml

# Встроенные дефолты. Предметного здесь нет и быть не должно - см. докстринг
# модуля. None означает «проверка выключена, пока профиль не задаст значение».
DEFAULTS: dict[str, Any] = {
    "length": {"min_chars": None, "max_chars": None, "tolerance": 0.1, "gate": True},
    "headings": {
        "h2_min": None,
        "h2_max": None,
        "forbid_colon": True,
    },  # двоеточие в заголовке - всегда нарушение (2026-09-30)
    # h1 не должен доезжать до страницы (заголовок выводит шаблон сайта),
    # script/style/iframe в теле статьи - всегда мусор от модели или копипаста
    "tags": {"forbidden": ["h1", "script", "style", "iframe"], "required": []},
    "cliches": [],
    "forbid": [],
    "humanizer": {"enabled": True, "error_is_gate": True, "max_warnings": None, "mute": []},
    # Язык проверяется по умолчанию: уехавшая на другой язык статья - поломка
    # в любой нише. Алфавит и порог переопределяются профилем - проект может
    # вестись не на русском.
    "language": {"enabled": True, "script": "cyrillic", "min_share": 0.6},
    "grounding": {"report_only": True, "min_grounded_share": None},
    "judge_model": None,
    "generation": {"constraints": ""},
}


# Запреты самого пайплайна: добавляются к запретам любого профиля и профилем
# не отменяются. Предметного здесь по-прежнему нет - это следы нашей кухни в
# тексте, то же основание, по которому h1 и script лежат в tags.forbidden.
# Читатель страницы не знает ни про какой «контекст» и «источники»: фраза
# «контекст не раскрывает данные о спросе» показывает, что текст писала и
# правила LLM. На корпусе mw 2026-09-24 такими фразами были испорчены 8 статей
# из 104.
PIPELINE_FORBID: list[dict[str, str]] = [
    {
        "name": "рассуждение о контексте в тексте статьи",
        # Обычные обороты («в контексте импорта из Китая», «научно-
        # исследовательский центр») правило намеренно не трогает: ловится
        # только разговор о полноте наших источников.
        "regex": r"(?:контекст\w*|источник\w*|в тексте)[^.!?\n]{0,40}(?:не\s+(?:раскрыв\w*|уточня\w*|подтвержда\w*|содерж\w*)|прямо\s+(?:указыв|говор))|не\s+раскры\w+[^.!?\n]{0,25}(?:в\s+)?контекст|(?:предоставленн\w+|с учетом|с учётом)\s+контекст|(?:упомина\w+|приведённ\w+|указанн\w+)\s+в\s+контекст",
        "judge": "в тексте для клиента не рассуждать о том, что раскрывают или не раскрывают контекст и источники - если факт не подтверждён, убрать сам факт, а не писать о его отсутствии",
    },
    {
        # Решение пользователя 2026-09-28: ставка НДС - 22%, и это правило
        # выше контекста. В выдаче конкурентов живут цены «с НДС 20%» (код
        # маркировки 60 копеек), и модель переносит их в статью как факт -
        # поймано на ost 356, где стояли обе ставки сразу. Суммы вида
        # «НДС 20 000 рублей» не ловятся: нужен знак процента или «процент».
        "name": "ставка НДС 20%",
        "regex": r"НДС[^.!?\n]{0,20}?\b20\s*(?:%|процент)|\b20\s*(?:%|процент\w*)[^.!?\n]{0,5}(?:НДС|налог\w* на добавленн)",
        "judge": "ставка НДС - 22%, упоминать ставку 20% нельзя: цены с НДС пересчитываются по 22% (код маркировки 50 копеек без НДС - 61 копейка с НДС)",
    },
]


class ProfileError(ValueError):
    """Профиль есть, но не разбирается: битый YAML, неизвестная секция, некомпилируемый regex."""


@dataclass
class ForbidRule:
    """
    Произвольный предметный запрет из профиля.

    regex ловит нарушение детерминированно, judge - та же мысль словами для
    промта судьи (смысловые нарушения regex не видит; textcheck judge не
    применяет). Любая половина необязательна.
    """

    name: str
    regex: Pattern | None = None
    judge: str = ""


@dataclass
class QualityProfile:
    """Слитый профиль: дефолты + файл. Источник правды для проверки."""

    path: Path | None = None
    raw: bytes = b""
    length: dict[str, Any] = field(default_factory=dict)
    headings: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, Any] = field(default_factory=dict)
    cliches: list[str] = field(default_factory=list)
    forbid: list[ForbidRule] = field(default_factory=list)
    humanizer: dict[str, Any] = field(default_factory=dict)
    language: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """
        Отпечаток версии профиля - первые 8 символов sha1 его содержимого.

        Имени мало: профиль живёт и меняется, и запись «профиль
        content-logistics.quality.yml» через неделю не отвечает на вопрос, по
        каким правилам текст был проверен. Отпечаток отвечает.
        """
        if not self.raw:
            return "defaults"
        return hashlib.sha1(self.raw).hexdigest()[:8]  # noqa: S324 - отпечаток, не защита

    def length_bounds(self) -> tuple[int | None, int | None]:
        """
        Границы длины с допуском: модели не попадают в диапазон с точностью до
        символа, поэтому заданные в профиле числа - ориентир, а не контракт.
        """
        tolerance = float(self.length.get("tolerance") or 0)
        min_chars = self.length.get("min_chars")
        max_chars = self.length.get("max_chars")
        low = int(min_chars * (1 - tolerance)) if min_chars else None
        high = int(max_chars * (1 + tolerance)) if max_chars else None
        return low, high


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    """JSON Schema формата quality.yml - лежит в пакете (data/quality-profile.schema.json)."""
    text = resources.files("rb_textcheck.data").joinpath("quality-profile.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Слияние по отдельным ключам: профиль уточняет дефолты, а не заменяет
    секцию целиком. Профиль с одним `length` не должен обнулять настройки
    humanizer и наоборот.
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_forbid(raw: list[dict[str, Any]], source: str) -> list[ForbidRule]:
    """Секция forbid -> правила со скомпилированными regex (форму уже проверила схема)."""
    rules: list[ForbidRule] = []
    for item in raw:
        name = str(item.get("name") or "").strip()
        pattern = None
        raw_regex = item.get("regex")
        if raw_regex:
            try:
                pattern = re.compile(str(raw_regex), re.IGNORECASE)
            except re.error as e:
                raise ProfileError(f"{source}: запрет «{name}» - не компилируется regex {raw_regex!r}: {e}") from e
        rules.append(ForbidRule(name=name, regex=pattern, judge=str(item.get("judge") or "").strip()))
    return rules


def _validate(raw: Any, source: str) -> None:
    if not isinstance(raw, dict):
        raise ProfileError(f"{source}: профиль должен быть словарём, получено {type(raw).__name__}")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ProfileError(
            f"{source}: неизвестные секции профиля: {', '.join(sorted(unknown))}. "
            f"Допустимые: {', '.join(sorted(DEFAULTS))}"
        )
    error = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(schema()).iter_errors(raw))
    if error is not None:
        where = "/".join(str(p) for p in error.absolute_path) or "профиль"
        raise ProfileError(f"{source}: {where}: {error.message}")


def load_profile(spec: str | Path | dict[str, Any] | QualityProfile | None = None) -> QualityProfile:
    """
    Профиль из файла quality.yml, словаря или None (одни дефолты - штатный режим).

    Raises:
        ProfileError: профиль есть, но не разбирается. Молча падать на дефолты
            нельзя: проверка пройдёт мягче, чем думает пользователь.
    """
    if isinstance(spec, QualityProfile):
        return spec

    path: Path | None = None
    raw_bytes = b""
    raw: Any = {}
    source = "встроенные дефолты"
    if isinstance(spec, dict):
        raw, source = spec, "профиль-словарь"
        raw_bytes = json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
    elif spec is not None:
        path = Path(spec)
        source = str(path)
        try:
            raw_bytes = path.read_bytes()
        except OSError as e:
            raise ProfileError(f"{source}: не читается: {e.strerror or e}") from e
        try:
            raw = yaml.safe_load(raw_bytes.decode("utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            raise ProfileError(f"{source}: не разбирается YAML: {e}") from e
        if raw is None:
            raw = {}

    _validate(raw, source)
    merged = _merge(DEFAULTS, raw)
    return QualityProfile(
        path=path,
        raw=raw_bytes,
        length=merged["length"],
        headings=merged["headings"],
        tags=merged["tags"],
        cliches=[str(c) for c in (merged["cliches"] or [])],
        # Запреты пайплайна идут первыми и профилем не отменяются: профиль
        # добавляет предметное, а не отключает общее.
        forbid=_parse_forbid(list(PIPELINE_FORBID) + list(merged["forbid"] or []), source),
        humanizer=merged["humanizer"],
        language=merged["language"],
    )
