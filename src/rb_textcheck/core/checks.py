"""
Детерминированные проверки текста по профилю качества.

Перенос из antagor (utils/quality_checks.py, коммит 9a5e4d8). Отличия:
- нет второго контура (LLM снимал срабатывания запретов): textcheck работает
  без сети и моделей, поэтому каждое срабатывание regex - находка;
- правила называются латинскими id (RULES), сообщения - как в antagor;
- находка без фрагмента относится ко всей статье и в md (antagor ставил ей
  paragraph).

Всё считается **по тексту без разметки**: до 2026-09-23 длина мерилась по HTML
вместе с тегами, из-за чего 78 статей из 104 ложно вылетали за верхнюю границу.
Исключение - проверки самой разметки (запрещённые теги, формат), им нужен
исходный HTML.

Предметных знаний (сколько символов, какие слова нельзя) здесь нет - всё
приходит из профиля, см. core/profile.py.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import html5lib
from bs4 import BeautifulSoup

from .humanizer_lint import lint as humanizer_lint
from .humanizer_lint import verdict as humanizer_verdict
from .profile import QualityProfile, load_profile
from .text_blocks import Block, locate_quote, parse_blocks

logger = logging.getLogger(__name__)

FORMATS = ("html", "md")

# Правила: id (машиночитаемый, в находке - rule), что ловит, в каких форматах
# работает. Порядок - порядок проверок в run_all. В скобках - имя правила в
# отчётах antagor.
RULES: list[dict[str, Any]] = [
    {
        "id": "format",
        "formats": ["html", "md"],
        "description": "Формат не тот, что просили: обёртка ```, markdown в HTML или HTML в markdown (формат)",
    },
    {
        "id": "tags",
        "formats": ["html", "md"],
        "description": "Запрещённые и обязательные теги из профиля, tags.forbidden/required (теги)",
    },
    {
        "id": "markup",
        "formats": ["html"],
        "description": "Вёрстка: незакрытые и перепутанные теги (html5lib), пункт вне списка, пропуск уровня заголовка, пустые блоки (вёрстка)",
    },
    {
        "id": "length",
        "formats": ["html", "md"],
        "description": "Длина чистого текста по профилю с допуском; выше максимума - к сведению (длина)",
    },
    {
        "id": "headings",
        "formats": ["html", "md"],
        "description": "Число разделов h2, обязательные разделы h2, двоеточие и штампы в заголовках h2-h6 (заголовки)",
    },
    {"id": "cliche", "formats": ["html", "md"], "description": "Клише из профиля, cliches (клише)"},
    {"id": "forbid", "formats": ["html", "md"], "description": "Regex-запреты профиля и пайплайна, forbid (запрет)"},
    {
        "id": "language",
        "formats": ["html", "md"],
        "description": "Текст не на целевом языке: доля букв алфавита ниже порога, language (язык)",
    },
    {
        "id": "corruption",
        "formats": ["html", "md"],
        "description": "Порча генерации: латиница внутри русского слова, чужая письменность (порча)",
    },
    {
        "id": "placeholder",
        "formats": ["html", "md"],
        "description": "Остался плейсхолдер вместо данных: [вставить, {{var}}, TODO (плейсхолдер)",
    },
    {
        "id": "self_reference",
        "formats": ["html", "md"],
        "description": "Модель рассказывает о генерации: «вот текст», «как видно из контекста» (служебное)",
    },
    {"id": "truncation", "formats": ["html"], "description": "Абзац или пункт списка обрывается на полуслове (обрыв)"},
    {
        "id": "humanizer",
        "formats": ["html", "md"],
        "description": "Линтер AI-слопа humanizer-ru: ERROR - гейт, WARN - сводкой и порогом max_warnings (humanizer)",
    },
]

# Остатки шаблона вместо реальных данных - непредметная проверка, верна для
# любого проекта, поэтому живёт в коде, а не в профиле
PLACEHOLDER_PATTERNS = [
    re.compile(r"\[вставить", re.IGNORECASE),
    re.compile(r"\[название компании\]", re.IGNORECASE),
    re.compile(r"\{\{[a-z_]+\}\}", re.IGNORECASE),
    re.compile(r"\bTODO\b"),
]

# Модель рассказывает о процессе генерации вместо того, чтобы писать статью
SELF_REFERENCE_PATTERNS = [
    re.compile(r"вот текст", re.IGNORECASE),
    re.compile(r"как видно из контекста", re.IGNORECASE),
    re.compile(r"далее раскроем", re.IGNORECASE),
]

# Латиница внутри русского слова («на seriю», «profиля», «fixируем») - всегда
# сбой генерации, а не стиль: осмысленных слов такого вида не бывает ни в
# одной нише. Поймано на правках 2026-09-23: дешёвый редактор подменял
# кириллические буквы латинскими, а рамки правки этого не видели - тег на
# месте, длина в норме, новых цифр нет.
MIXED_ALPHABET_RE = re.compile(r"\b(?:[а-яё]+[a-z]{2,}[а-яё]*|[a-z]{2,}[а-яё]+)\b", re.IGNORECASE)

# Чем может законно кончаться абзац или пункт списка. Всё остальное - обрыв:
# генерация упёрлась в лимит токенов или сорвалась, и предложение не дописано.
# Проверка непредметная: так выглядит сбой в любой нише и на любую тему.
SENTENCE_END = tuple(".!?…:;»\"')")

# Элементы, которые считаются прозой и обязаны кончаться знаком препинания.
# Заголовки, ячейки таблиц, подписи и термины списков сюда не входят - у них
# отсутствие точки нормально.
PROSE_TAGS = ["p", "li"]

# Длина, начиная с которой абзац без знака конца считается оборванным:
# заголовок, оформленный абзацем, столько не занимает.
LONG_PROSE_CHARS = 120

# Вопрос FAQ: частица «ли» или вопросительное слово в начале. Такой блок без
# знака - недописанный «?», а не обрыв (check_truncation).
QUESTION = re.compile(
    r"\bли\b|^(как|что|где|когда|можно|нужно|нужна|нужен|зачем|почему|сколько|кто|какие|какой|какая|каким|чем|куда|откуда)\b",
    re.IGNORECASE,
)

CODE_FENCE_RE = re.compile(r"^\s*```")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
HTML_TAG_RE = re.compile(r"<(?:p|div|h[1-6]|ul|ol|li|table|section)\b", re.IGNORECASE)


@dataclass
class Issue:
    """
    Одно замечание: чем поймано, что именно нашли и в каком месте текста.

    address - адрес блока по utils/text_blocks (номер плюс якорь). Заполняется
    для находок с фрагментом: по нему правщик находит тот же блок, даже если
    статью между проверкой и правкой успели тронуть. Находки про статью
    целиком (длина, число разделов) адреса не имеют и точечной правке не
    подлежат - у них unit="article".
    """

    rule: str
    message: str
    excerpt: str = ""
    gate: bool = True  # False - замечание копится, но само по себе статью не валит
    unit: str = "paragraph"
    address: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.message}{f': «{self.excerpt}»' if self.excerpt else ''}"

    def as_dict(self) -> dict[str, Any]:
        """Строка находки в отчёте: адрес есть - блок переписывается, нет - нужен человек."""
        return {
            "rule": self.rule,
            "message": self.message,
            "excerpt": self.excerpt,
            "gate": self.gate,
            "unit": self.unit,
            "address": self.address,
            "action": "rewrite_block" if self.address else "manual",
        }


def html_to_text(html: str) -> str:
    """Чистовой текст из HTML - то, что читает человек, без тегов и атрибутов."""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def headings(html: str, levels: tuple = ("h2",)) -> list[str]:
    """Тексты заголовков указанных уровней в порядке появления."""
    soup = BeautifulSoup(html, "html.parser")
    return [h.get_text(" ", strip=True) for h in soup.find_all(list(levels))]


def _excerpt(text: str, match: re.Match, width: int = 45) -> str:
    """Фрагмент вокруг срабатывания - без него замечание невозможно проверить глазами."""
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def check_format(raw: str, expected_format: str) -> list[Issue]:
    """Формат отдан тот, который просили: html без markdown-обёртки и наоборот."""
    issues: list[Issue] = []

    if CODE_FENCE_RE.search(raw):
        issues.append(Issue("format", "Ответ модели обёрнут в ``` - разметка кода в статье"))

    if expected_format == "html":
        if MARKDOWN_HEADING_RE.search(raw):
            issues.append(Issue("format", "Ждали HTML, а в тексте markdown-заголовки (#)"))
        if not HTML_TAG_RE.search(raw):
            issues.append(Issue("format", "Ждали HTML, но блочных тегов в тексте нет"))
    elif expected_format == "md":
        if HTML_TAG_RE.search(raw):
            issues.append(Issue("format", "Ждали markdown, а в тексте HTML-теги"))

    return issues


def check_markup(raw: str, profile: QualityProfile) -> list[Issue]:
    """Теги: чёрный и белый списки из профиля."""
    issues: list[Issue] = []
    soup = BeautifulSoup(raw, "html.parser")

    for tag in profile.tags.get("forbidden") or []:
        found = soup.find_all(tag)
        if found:
            issues.append(Issue("tags", f"Запрещённый тег <{tag}>: {len(found)} шт."))

    for tag in profile.tags.get("required") or []:
        if not soup.find(tag):
            issues.append(Issue("tags", f"Нет обязательного тега <{tag}>"))

    return issues


# Ошибки разбора html5lib (спецификация WHATWG) -> понятное сообщение
PARSE_ERRORS = {
    "unexpected-end-tag": "Лишний закрывающий тег </{name}> - открывающего нет или он уже закрыт",
    "end-tag-too-early": "Тег </{name}> закрыт раньше вложенных - теги перепутаны",
    "expected-closing-tag-but-got-eof": "Текст кончился внутри незакрытого тега",
    "unexpected-start-tag-implies-end-tag": "Тег <{name}> внутри тега, который так вкладывать нельзя",
}
BLOCK_TEXT_TAGS = ("p", "li", "h2", "h3", "h4", "h5", "h6")


def _context(raw: str, position) -> str:
    """Текст около места ошибки разбора - для адреса блока и для человека."""
    line, col = position if isinstance(position, tuple) else (1, 0)
    lines = raw.splitlines() or [""]
    source = lines[min(max(line, 1), len(lines)) - 1]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", source[max(0, col - 120) : col + 80])).strip()[:160]


def check_structure(raw: str) -> list[Issue]:
    """
    Вёрстка целиком: закрыто ли всё и правильна ли иерархия.

    Закрытость и вложенность тегов - готовым парсером html5lib (WHATWG): он
    ловит незакрытые и перепутанные теги, лишние закрывающие, обрыв внутри
    тега (выбран 2026-09-29 из html5lib / HTML Tidy / vnu - чистый Python,
    ставится и на сервер). Чего стандарт ошибкой разбора не считает, но для
    статьи это поломка - своими правилами:
    - пункт списка вне <ul>/<ol> и не-пункт внутри списка (ost 357: правка
      вставила <li> после заголовка, судья читает текст и этого не видит, а
      конвертер в Gutenberg оставил кусок сырым HTML-блоком);
    - заголовки без пропуска уровня (h2 -> h4) и без h3 до первого h2;
    - пустые абзацы, пункты и заголовки.
    """
    issues: list[Issue] = []
    parser = html5lib.HTMLParser(strict=False, namespaceHTMLElements=False)
    parser.parseFragment(raw)
    for position, code, datavars in parser.errors[:MAX_HITS_PER_RULE]:
        template = PARSE_ERRORS.get(code, f"Ошибка разметки ({code})")
        issues.append(
            Issue("markup", template.format(name=(datavars or {}).get("name", "?")), excerpt=_context(raw, position))
        )

    soup = BeautifulSoup(raw, "html.parser")
    for li in soup.find_all("li"):
        if li.parent is None or li.parent.name not in ("ul", "ol"):
            issues.append(
                Issue(
                    "markup",
                    "Пункт списка вне списка <ul>/<ol> - вставлен не на место",
                    excerpt=li.get_text(" ", strip=True)[:160],
                )
            )
    for lst in soup.find_all(("ul", "ol")):
        for child in lst.children:
            name = getattr(child, "name", None)
            if name and name != "li":
                issues.append(
                    Issue(
                        "markup",
                        f"Внутри списка <{lst.name}> тег <{name}> - там допустимы только <li>",
                        excerpt=child.get_text(" ", strip=True)[:160],
                    )
                )

    previous = 1
    for heading in soup.find_all(re.compile(r"^h[2-6]$")):
        level = int(heading.name[1])
        text = heading.get_text(" ", strip=True)
        if level > previous + 1:
            where = f"до первого <h{level - 1}>" if previous == 1 else f"после <h{previous}>"
            issues.append(Issue("markup", f"Пропущен уровень заголовка: <h{level}> {where}", excerpt=text[:160]))
        previous = level

    for tag in soup.find_all(BLOCK_TEXT_TAGS):
        if not tag.get_text(strip=True) and not tag.find(("img", "iframe", "video")):
            issues.append(Issue("markup", f"Пустой <{tag.name}>", unit="article"))
    return issues


def check_length(text: str, profile: QualityProfile) -> list[Issue]:
    """
    Длина по чистовому тексту с допуском из профиля.

    gate: false в профиле переводит длину в разряд замечаний к сведению:
    статья из-за неё не падает. Так и надо, когда диапазон в профиле - это
    ориентир для генерации, а не контракт на результат: на замере 2026-09-23
    51 статья из 104 писалась длиннее нормы при медиане 7320 против потолка
    6600, и валить их все смысла нет.
    """
    low, high = profile.length_bounds()
    length = len(text)
    gate = bool(profile.length.get("gate", True))

    if low and length < low:
        return [Issue("length", f"Длина {length} символов текста < минимума {low}", gate=gate)]
    # Превышение максимума - к сведению, а не FAIL: размер не мера качества
    # (решение пользователя 2026-09-28, «размер неважен»), а правка блоков
    # длину не лечит - ost 364 с 22 140 при 18 400 и чистым судьёй получал FAIL.
    # Минимум остаётся жёстким: короткий текст - признак поломки (ost 359 -
    # чистка потеряла 94% текста, первым сигналом было «< минимума»).
    if high and length > high:
        return [Issue("length", f"Длина {length} символов текста > максимума {high}", gate=False)]
    return []


# Штампы переводной SEO-статьи в заголовках - общие для заголовков статей и
# метатегов seo-meta (title, H1). В заголовке они однозначны, поэтому ловятся
# кодом без модели решений; «ё» и «е» не различаются.
HEADING_STAMPS = ("простыми словами", "что это такое", "всё, что нужно знать", "полное руководство", "подробный разбор")


def heading_stamp(text: str) -> str | None:
    """Первый штамп из HEADING_STAMPS в заголовке или None."""
    normalized = text.lower().replace("ё", "е")
    return next((s for s in HEADING_STAMPS if s.replace("ё", "е") in normalized), None)


def _heading_key(text: str) -> str:
    """Заголовок для сравнения: без регистра, ё/е, лишних пробелов и знака в конце."""
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip().rstrip(".:!?…").strip()


def missing_sections(h2: list[str], required: list[Any]) -> list[str]:
    """
    Обязательные разделы (headings.required), которых нет среди <h2>.

    Строка - заголовок целиком (без регистра, ё/е, пробелов и .:!? в конце),
    {name, regex} - паттерн по тексту h2 без учёта регистра.
    """
    keys = {_heading_key(h) for h in h2}
    missing = []
    for item in required:
        if isinstance(item, dict):
            if not any(re.search(item["regex"], h, re.IGNORECASE) for h in h2):
                missing.append(str(item["name"]))
        elif _heading_key(str(item)) not in keys:
            missing.append(str(item))
    return missing


def check_headings(raw: str, profile: QualityProfile) -> list[Issue]:
    """Число разделов и качество самих заголовков."""
    issues: list[Issue] = []
    h2 = headings(raw, ("h2",))
    rules = profile.headings

    h2_min, h2_max = rules.get("h2_min"), rules.get("h2_max")
    if h2_min and len(h2) < h2_min:
        issues.append(Issue("headings", f"Разделов <h2>: {len(h2)}, минимум {h2_min}"))
    if h2_max and len(h2) > h2_max:
        issues.append(Issue("headings", f"Разделов <h2>: {len(h2)}, максимум {h2_max}"))
    for name in missing_sections(h2, rules.get("required") or []):
        issues.append(Issue("headings", f"Нет обязательного раздела <h2> «{name}»"))

    # Все заголовки статьи, не только разделы: правило про «тема: пояснение»
    # и штампы касается любого заголовка (решение пользователя 2026-09-30)
    all_headings = headings(raw, ("h2", "h3", "h4", "h5", "h6"))
    if rules.get("forbid_colon"):
        # Двоеточие в заголовке - маркер нейросетевого текста: заголовок должен
        # прямо описывать раздел, а не объяснять сам себя через «тема: пояснение».
        # По-русски двоеточие ставят перед перечнем в строке, а не в заголовке.
        for h in all_headings:
            if ":" in h:
                issues.append(Issue("headings", "Двоеточие в заголовке", excerpt=h))
    for h in all_headings:
        stamp = heading_stamp(h)
        if stamp:
            issues.append(Issue("headings", f"Штамп в заголовке «{stamp}»", excerpt=h))

    return issues


# Сколько вхождений одного нарушения показывать. Раньше показывалось ровно
# одно: правка снимала его, следующая проверка находила второе, и статья
# ходила по кругу, каждый раз платя за вызов модели (поймано 2026-09-24 на
# 3433 - «под ключ» в двух блоках). Предел нужен, чтобы статья, где запрет
# нарушен везде, не рожала полсотни находок: столько правок всё равно не
# делают, такую статью перегенерируют.
MAX_HITS_PER_RULE = 5


def check_profile_bans(text: str, profile: QualityProfile) -> list[Issue]:
    """
    Предметные запреты профиля: клише и произвольные regex-правила.

    Каждое вхождение - отдельная находка со своим адресом: иначе правка
    снимает одно, а остальные доживают до следующего прогона.
    """
    issues: list[Issue] = []
    lowered = text.lower()

    for phrase in profile.cliches:
        needle = phrase.lower()
        # Фрагментом идёт сама фраза: без него находка остаётся без адреса и
        # content-fix её не видит.
        hits = 0
        start = lowered.find(needle)
        while start != -1 and hits < MAX_HITS_PER_RULE:
            excerpt = text[max(0, start - 45) : start + len(phrase) + 45]
            issues.append(Issue("cliche", f"Запрещённое клише «{phrase}»", excerpt=excerpt))
            hits += 1
            start = lowered.find(needle, start + len(needle))

    for rule in profile.forbid:
        if rule.regex is None:
            continue
        for hits, match in enumerate(rule.regex.finditer(text)):
            if hits >= MAX_HITS_PER_RULE:
                break
            issues.append(Issue("forbid", f"Нарушен запрет «{rule.name}»", excerpt=_excerpt(text, match)))

    return issues


@lru_cache(maxsize=1)
def _morph():
    """Морфологический анализатор - создаётся один раз, инициализация не бесплатна."""
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=4096)
def is_known_word(word: str) -> bool:
    """
    Знает ли словарь такое слово.

    Сам по себе этот признак для поиска порчи не годится: 2026-09-23 проверено,
    что несловарными оказываются отраслевые термины («селлеры», «блэкаут»,
    «жаккард»), и доля таких слов ничего не доказывает. Но в паре с «блок
    кончается без знака препинания» он работает: заголовок кончается обычным
    словом, а обрыв - обрубком.
    """
    parsed = _morph().parse(word)
    # is_known - слово реально есть в словаре. Проверять тег бесполезно:
    # pymorphy угадывает разбор для любого набора букв и «конта» с «истираем»
    # возвращает как обычные слова (проверено 2026-09-23).
    return bool(parsed) and parsed[0].is_known


def check_truncation(raw: str) -> list[Issue]:
    """
    Обрывы предложений: абзац или пункт списка кончается на полуслове.

    Заголовки не проверяются - им точка не нужна. Проверяется именно конец
    блока: текст, оборванный посреди предложения, встречается ровно там, где
    генерация упёрлась в лимит или сорвалась (поймано на статье 3494: раздел
    заканчивался словами «результат отдельного теста поверхности на истираем»).

    Такой обрыв - жёсткая поломка: читателю видно сразу, а автоматическая
    правка его не чинит, нужна перегенерация раздела.
    """
    issues: list[Issue] = []
    soup = BeautifulSoup(raw, "html.parser")

    # Проверяем только прозу. У остальных элементов отсутствие точки - норма,
    # а не обрыв: у заголовков (h1-h6) по определению, у ячеек таблиц, подписей
    # и терминов списка определений - по типографике. Поэтому здесь белый
    # список элементов, а не чёрный: неизвестный тег лучше пропустить, чем
    # завалить статью ложным замечанием.
    for tag in soup.find_all(PROSE_TAGS):
        text = tag.get_text(" ", strip=True)
        if len(text) < 25:
            continue
        if text.endswith(SENTENCE_END):
            continue
        # Отсутствия точки мало: заголовок, оформленный абзацем, её и не
        # требует («Импорт лодок из Китая: руководство»). Обрыв отличается тем,
        # что последнее слово не дописано, то есть его нет в словаре. Порознь
        # оба признака дают ложные срабатывания, вместе - нет.
        # Два независимых признака, каждого по отдельности мало:
        # - последнее слово не из словаря: обрубок вроде «конта», «истираем»
        #   тут не поможет - это реальная словоформа, поэтому нужен второй;
        # - длинный абзац без знака конца: заголовок, оформленный абзацем,
        #   короткий, а проза такой длины всегда завершается точкой.
        last_word = re.search(r"([а-яё]{3,})$", text.lower())
        cut_word = bool(last_word) and not is_known_word(last_word.group(1))
        # Аббревиатура в конце («БАД», «СИЗ») - не обрубок, её просто нет в
        # словаре. И короткий вопрос без знака - вопрос FAQ, где модель не
        # поставила «?», а не обрыв: ost 358 (2026-09-28) ушла на
        # перегенерацию из-за «Подлежат ли маркировке БАД» и «Обязательна ли
        # маркировка для маркетплейсов».
        if cut_word and re.search(r"\b[А-ЯЁ]{2,}$", text):
            cut_word = False
        long_prose = len(text) > LONG_PROSE_CHARS
        if not long_prose and QUESTION.search(text):
            continue

        if cut_word or long_prose:
            issues.append(Issue("truncation", "Блок обрывается на полуслове", excerpt=text[-70:], unit="section"))

    return issues


def check_language(text: str, profile: QualityProfile) -> list[Issue]:
    """
    Статья написана на целевом языке, а не на чужом.

    Ловится не отдельный термин и не латинское название - они нормальны, - а
    случай, когда модель уехала на другой язык целиком или большей частью.
    Считается доля букв целевого алфавита среди всех букв: вкрапления терминов
    её почти не двигают, смена языка обрушивает сразу.

    Порог и алфавит берутся из профиля - проект может вестись и не на русском.
    """
    settings = profile.language or {}
    if not settings.get("enabled", True):
        return []

    letters = [c for c in text if c.isalpha()]
    if len(letters) < 200:
        return []

    script = str(settings.get("script") or "cyrillic").lower()
    in_script = (
        sum(1 for c in letters if ("а" <= c.lower() <= "я" or c.lower() == "ё"))
        if script == "cyrillic"
        else sum(1 for c in letters if "a" <= c.lower() <= "z")
    )
    share = in_script / len(letters)

    min_share = float(settings.get("min_share", 0.6))
    if share < min_share:
        return [
            Issue(
                "language",
                f"Текст не на целевом языке: букв целевого алфавита {share:.0%} при минимуме {min_share:.0%}",
                unit="article",
            )
        ]
    return []


# Письменности, которых в русской статье быть не может ни как термин, ни как
# название: CJK, японская кана, хангыль, арабская, иврит, деванагари, тайская.
# Латиница сюда не входит - она нормальна для терминов и брендов.
FOREIGN_SCRIPT = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af\u0600-\u06ff\u0590-\u05ff\u0900-\u097f\u0e00-\u0e7f]+"
)


def check_foreign_script(text: str, profile: QualityProfile) -> list[Issue]:
    """
    Вкрапление чужой письменности в кириллический текст - порча генерации.

    check_language считает долю алфавита по всей статье, и одно китайское
    слово вместо числительного её не сдвигает: на ost 363 (2026-09-28) такое
    слово поймал только судья. Здесь ловится каждое вхождение, с адресом
    блока - правка чинит его точечно.
    """
    settings = profile.language or {}
    if not settings.get("enabled", True) or str(settings.get("script") or "cyrillic").lower() != "cyrillic":
        return []
    issues: list[Issue] = []
    for m in FOREIGN_SCRIPT.finditer(text):
        excerpt = text[max(0, m.start() - 40) : m.end() + 40]
        issues.append(
            Issue("corruption", f"Чужая письменность в тексте: «{m.group(0)}»", excerpt=excerpt, unit="paragraph")
        )
    return issues


def check_leftovers(text: str) -> list[Issue]:
    """Непредметное: порча слов, остатки плейсхолдеров, рассказ о процессе генерации."""
    issues: list[Issue] = []

    for match in list(MIXED_ALPHABET_RE.finditer(text))[:3]:
        issues.append(Issue("corruption", "Латиница внутри русского слова", excerpt=_excerpt(text, match)))

    for pattern in PLACEHOLDER_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(Issue("placeholder", "Остался плейсхолдер вместо данных", excerpt=_excerpt(text, match)))
            break

    for pattern in SELF_REFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(
                Issue("self_reference", "Обращение к себе/пояснение процесса генерации", excerpt=_excerpt(text, match))
            )
            break

    return issues


def check_humanizer(text: str, profile: QualityProfile) -> tuple[list[Issue], dict[str, Any] | None]:
    """
    Линт AI-слопа (core/humanizer_lint) по чистовому тексту.

    ERROR валит статью, WARN копится и валит только при превышении порога
    max_warnings из профиля. Правила из mute не считаются вовсе - часть из них
    заточена под живой блог и в коммерческой статье срабатывает всегда.

    Returns:
        (замечания, {"score", "verdict"}) - verdict: clean | review | rewrite;
        None, если линтер выключен профилем.
    """
    settings = profile.humanizer
    if not settings.get("enabled", True):
        return [], None

    muted = [m.lower() for m in (settings.get("mute") or [])]
    findings = [f for f in humanizer_lint(text) if not any(m in f[2].lower() for m in muted)]

    errors = [f for f in findings if f[0] == "ERROR"]
    warnings = [f for f in findings if f[0] == "WARN"]
    score, verdict_text = humanizer_verdict(len(errors), len(warnings))

    issues: list[Issue] = []
    gate = bool(settings.get("error_is_gate", True))
    for _, _, rule, excerpt in errors:
        issues.append(Issue("humanizer", f"Запрещённый приём: {rule}", excerpt=excerpt, gate=gate))

    max_warnings = settings.get("max_warnings")
    if max_warnings is not None and len(warnings) > max_warnings:
        rules = ", ".join(sorted({f[2] for f in warnings})[:5])
        issues.append(Issue("humanizer", f"Предупреждений линтера {len(warnings)} > порога {max_warnings} ({rules})"))
    elif warnings:
        rules = ", ".join(sorted({f[2] for f in warnings})[:5])
        issues.append(Issue("humanizer", f"Предупреждений линтера: {len(warnings)} ({rules})", gate=False))

    return issues, {"score": score, "verdict": verdict_text.split()[0]}


def attach_addresses(issues: list[Issue], blocks: list[Block]) -> None:
    """
    Проставляет находкам адрес блока по их фрагменту.

    Делается одним проходом в конце, а не внутри каждой проверки: разбор
    статьи на блоки стоит денег, а фрагмент у всех находок устроен одинаково.
    Находка без фрагмента относится ко всей статье - у неё unit="article" и
    адреса нет.
    """
    for issue in issues:
        if not issue.excerpt:
            continue
        block = locate_quote(blocks, issue.excerpt)
        if block is None:
            logger.debug(f"Находка «{issue.rule}»: фрагмент не нашёлся ни в одном блоке")
            continue
        issue.address = block.address(quote=issue.excerpt)
        issue.unit = "phrase" if block.tag in {"h2", "h3", "h4"} else "paragraph"


def run_all(
    raw: str, profile: QualityProfile, expected_format: str = "html"
) -> tuple[list[Issue], dict[str, Any] | None]:
    """
    Весь детерминированный слой разом.

    Returns:
        (замечания, итог humanizer). Замечания с gate=False - к сведению,
        текст сами по себе не валят. Каждой находке с фрагментом в html
        проставляется адрес блока (core/text_blocks) - по нему её чинит правщик.
    """
    text = html_to_text(raw) if expected_format == "html" else raw

    issues: list[Issue] = []
    issues += check_format(raw, expected_format)
    issues += check_markup(raw, profile)
    if expected_format == "html":
        issues += check_structure(raw)
    issues += check_length(text, profile)
    issues += check_headings(raw, profile)
    issues += check_profile_bans(text, profile)
    issues += check_language(text, profile)
    issues += check_foreign_script(text, profile)
    issues += check_leftovers(text)
    if expected_format == "html":
        issues += check_truncation(raw)

    humanizer_issues, humanizer = check_humanizer(text, profile)
    issues += humanizer_issues

    # Находка без фрагмента - про статью целиком (длина, число разделов),
    # точечной правке не подлежит - в любом формате
    for issue in issues:
        if not issue.excerpt:
            issue.unit = "article"
    if expected_format == "html":
        attach_addresses(issues, parse_blocks(raw))

    return issues, humanizer


@dataclass
class Result:
    """Итог проверки: находки, итог humanizer и провален ли гейт."""

    issues: list[Issue]
    humanizer: dict[str, Any] | None

    @property
    def gate_failed(self) -> bool:
        """Гейт не пройден, если есть хоть одна находка с gate; остальные - к сведению."""
        return any(issue.gate for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.as_dict() for issue in self.issues],
            "humanizer": self.humanizer,
            "gate_failed": self.gate_failed,
        }


def check(
    text: str, profile: str | Path | dict[str, Any] | QualityProfile | None = None, format: str = "html"
) -> Result:
    """
    Проверяет текст по профилю: путь к quality.yml, словарь, QualityProfile или None (дефолты).

    Raises:
        ProfileError: профиль не разбирается.
        ValueError: формат не html и не md.
    """
    if format not in FORMATS:
        raise ValueError(f"формат {format!r} не поддерживается: {', '.join(FORMATS)}")
    issues, humanizer = run_all(text, load_profile(profile).require_article(), format)
    return Result(issues=issues, humanizer=humanizer)
