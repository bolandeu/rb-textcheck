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

С 0.2.0 (T78 B):
- kind: article (по умолчанию) | meta - профиль метатегов antagor seo-meta,
  только валидируется: check и fix работают со статьёй;
- extends: базовый профиль, дочерний переопределяет ключи, forbid и fixes
  объединяются (базовые первыми), цикл - ошибка;
- неизвестный ключ на любом уровне - ошибка с путём к ключу;
- fixes: автозамены для textcheck fix (core/fix.py);
- headings.required: обязательные разделы h2;
- запрет «ставка НДС 20%» вынесен из кода в профили.
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
    "kind": "article",
    "length": {"min_chars": None, "max_chars": None, "tolerance": 0.1, "gate": True},
    "headings": {
        "h2_min": None,
        "h2_max": None,
        "forbid_colon": True,
        "required": [],
    },  # двоеточие в заголовке - всегда нарушение (2026-09-30)
    # h1 не должен доезжать до страницы (заголовок выводит шаблон сайта),
    # script/style/iframe в теле статьи - всегда мусор от модели или копипаста
    "tags": {"forbidden": ["h1", "script", "style", "iframe"], "required": []},
    "cliches": [],
    "forbid": [],
    "fixes": [],
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
    # «Ставка НДС 20%» (решение пользователя 2026-09-28) жила здесь до 0.2.0 -
    # правило предметное, теперь оно в профилях (vectors/profiles/vat-22.quality.yml).
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
class FixRule:
    """Автозамена из секции fixes: что, на что и где (text | headings | paragraphs | lists)."""

    name: str
    pattern: Pattern
    to: str
    regex: bool = False
    where: str = "text"
    fixes_rule: str = ""

    def apply(self, text: str) -> tuple[str, int]:
        """Замена во фрагменте текста; литеральный to вставляется как есть, без разбора \\1."""
        if self.regex:
            return self.pattern.subn(self.to, text)
        return self.pattern.subn(lambda _: self.to, text)


@dataclass
class QualityProfile:
    """Слитый профиль: дефолты + базовые (extends) + файл. Источник правды для проверки."""

    path: Path | None = None
    raw: bytes = b""
    kind: str = "article"
    length: dict[str, Any] = field(default_factory=dict)
    headings: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, Any] = field(default_factory=dict)
    cliches: list[str] = field(default_factory=list)
    forbid: list[ForbidRule] = field(default_factory=list)
    fixes: list[FixRule] = field(default_factory=list)
    humanizer: dict[str, Any] = field(default_factory=dict)
    language: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)  # kind: meta - секции как есть

    @property
    def name(self) -> str:
        return str(self.path) if self.path else "встроенные дефолты"

    @property
    def fingerprint(self) -> str:
        """
        Отпечаток версии профиля - первые 8 символов sha1 его содержимого
        (с extends - вместе с базовыми: правка базы меняет и отпечаток).

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

    def require_article(self) -> QualityProfile:
        """check и fix работают со статьёй; профиль метатегов - только для валидации."""
        if self.kind != "article":
            raise ProfileError(f"{self.name}: kind: {self.kind} - check и fix работают с профилем kind: article")
        return self


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    """JSON Schema формата quality.yml - лежит в пакете (data/quality-profile.schema.json)."""
    text = resources.files("rb_textcheck.data").joinpath("quality-profile.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


# Списки, которые при extends объединяются (базовые первыми), а не заменяются
MERGED_LISTS = ("forbid", "fixes")


def _merge(base: dict[str, Any], override: dict[str, Any], lists: tuple[str, ...] = ()) -> dict[str, Any]:
    """
    Слияние по отдельным ключам: профиль уточняет дефолты, а не заменяет
    секцию целиком. Профиль с одним `length` не должен обнулять настройки
    humanizer и наоборот. Ключи из lists объединяются.
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        elif key in lists and isinstance(value, list):
            merged[key] = list(merged.get(key) or []) + value
        else:
            merged[key] = value
    return merged


def _path(parts: Any) -> str:
    return "/".join(str(p) for p in parts)


def _validate(raw: Any, source: str) -> None:
    """Схема: на ошибке - путь к ключу (length/min_char) и что не так."""
    if not isinstance(raw, dict):
        raise ProfileError(f"{source}: профиль должен быть словарём, получено {type(raw).__name__}")
    error = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(schema()).iter_errors(raw))
    if error is None:
        return
    where = list(error.absolute_path)
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        allowed = set(error.schema.get("properties") or {})
        unknown = sorted(set(error.instance) - allowed)
        raise ProfileError(
            f"{source}: {_path([*where, unknown[0]])}: неизвестный ключ. Допустимые: {', '.join(sorted(allowed))}"
        )
    raise ProfileError(f"{source}: {_path(where) or 'профиль'}: {error.message}")


def _compile(raw: dict[str, Any], source: str) -> None:
    """Regex-ы файла компилируются до слияния - так в ошибке его собственный путь (fixes/0/from)."""

    def check(pattern: str, where: str) -> re.Pattern:
        try:
            return re.compile(pattern)
        except re.error as e:
            raise ProfileError(f"{source}: {where}: не компилируется regex {pattern!r}: {e}") from e

    for i, item in enumerate(raw.get("forbid") or []):
        if item.get("regex"):
            check(str(item["regex"]), f"forbid/{i}/regex")
    for i, item in enumerate((raw.get("headings") or {}).get("required") or []):
        if isinstance(item, dict):
            check(str(item["regex"]), f"headings/required/{i}/regex")
    for i, item in enumerate(raw.get("fixes") or []):
        if item.get("regex"):
            pattern = check(str(item["from"]), f"fixes/{i}/from")
            try:
                pattern.sub(str(item["to"]), "")  # разбор шаблона: \2 без второй группы, \q
            except (re.error, IndexError) as e:
                raise ProfileError(f"{source}: fixes/{i}/to: неверный шаблон замены {item['to']!r}: {e}") from e


def _base_path(extends: str, directory: Path) -> Path:
    """extends: имя (base -> base.quality.yml рядом) или путь от папки профиля."""
    if "/" in extends or "\\" in extends or extends.endswith((".yml", ".yaml")):
        return directory / extends
    return directory / f"{extends}{PROFILE_SUFFIX}"


PROFILE_SUFFIX = ".quality.yml"


def _read(path: Path, source: str) -> tuple[Any, bytes]:
    try:
        raw_bytes = path.read_bytes()
    except OSError as e:
        raise ProfileError(f"{source}: не читается: {e.strerror or e}") from e
    try:
        raw = yaml.safe_load(raw_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise ProfileError(f"{source}: не разбирается YAML: {e}") from e
    return ({} if raw is None else raw), raw_bytes


def _resolve(raw: Any, raw_bytes: bytes, source: str, directory: Path, chain: list[Path]) -> tuple[dict, str, bytes]:
    """Профиль с базовыми (extends): (слитые секции без extends, kind, байты всей цепочки)."""
    if not isinstance(raw, dict):
        raise ProfileError(f"{source}: профиль должен быть словарём, получено {type(raw).__name__}")
    base: dict[str, Any] = {}
    base_kind: str | None = None
    extends = raw.get("extends")
    if isinstance(extends, str) and extends:
        path = _base_path(extends, directory).resolve()
        if path in chain:
            loop = " -> ".join(p.name for p in [*chain, path])
            raise ProfileError(f"{source}: extends: цикл extends: {loop}")
        if not path.is_file():
            raise ProfileError(f"{source}: extends: базовый профиль {extends!r} не найден ({path})")
        base_raw, base_bytes = _read(path, str(path))
        base, base_kind, base_bytes = _resolve(base_raw, base_bytes, str(path), path.parent, [*chain, path])
        raw_bytes += base_bytes

    kind = raw.get("kind", base_kind or "article")
    _validate(raw if "kind" in raw else {**raw, "kind": kind}, source)
    if base_kind is not None and kind != base_kind:
        raise ProfileError(f"{source}: kind: {kind} не совпадает с kind базового профиля ({base_kind})")
    _compile(raw, source)
    own = {key: value for key, value in raw.items() if key != "extends"}
    return _merge(base, own, MERGED_LISTS), kind, raw_bytes


def _parse_forbid(raw: list[dict[str, Any]]) -> list[ForbidRule]:
    return [
        ForbidRule(
            name=str(item["name"]).strip(),
            regex=re.compile(str(item["regex"]), re.IGNORECASE) if item.get("regex") else None,
            judge=str(item.get("judge") or "").strip(),
        )
        for item in raw
    ]


def _parse_fixes(raw: list[dict[str, Any]]) -> list[FixRule]:
    return [
        FixRule(
            name=str(item["name"]),
            pattern=re.compile(str(item["from"]) if item.get("regex") else re.escape(str(item["from"]))),
            to=str(item["to"]),
            regex=bool(item.get("regex")),
            where=str(item.get("where") or "text"),
            fixes_rule=str(item.get("fixes_rule") or ""),
        )
        for item in raw
    ]


def load_profile(spec: str | Path | dict[str, Any] | QualityProfile | None = None) -> QualityProfile:
    """
    Профиль из файла quality.yml, словаря или None (одни дефолты - штатный режим).

    extends в словаре считается от текущей папки, в файле - от папки файла.

    Raises:
        ProfileError: профиль есть, но не разбирается. Молча падать на дефолты
            нельзя: проверка пройдёт мягче, чем думает пользователь.
    """
    if isinstance(spec, QualityProfile):
        return spec

    path: Path | None = None
    merged_raw: dict[str, Any] = {}
    kind = "article"
    raw_bytes = b""
    if isinstance(spec, dict):
        raw_bytes = json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
        merged_raw, kind, raw_bytes = _resolve(spec, raw_bytes, "профиль-словарь", Path.cwd(), [])
    elif spec is not None:
        path = Path(spec)
        raw, raw_bytes = _read(path, str(path))
        merged_raw, kind, raw_bytes = _resolve(raw, raw_bytes, str(path), path.parent, [path.resolve()])

    if kind == "meta":
        return QualityProfile(path=path, raw=raw_bytes, kind="meta", meta=merged_raw)

    merged = _merge(DEFAULTS, merged_raw)
    return QualityProfile(
        path=path,
        raw=raw_bytes,
        length=merged["length"],
        headings=merged["headings"],
        tags=merged["tags"],
        cliches=[str(c) for c in (merged["cliches"] or [])],
        # Запреты пайплайна идут первыми и профилем не отменяются: профиль
        # добавляет предметное, а не отключает общее.
        forbid=_parse_forbid(list(PIPELINE_FORBID) + list(merged["forbid"] or [])),
        fixes=_parse_fixes(list(merged["fixes"] or [])),
        humanizer=merged["humanizer"],
        language=merged["language"],
    )
