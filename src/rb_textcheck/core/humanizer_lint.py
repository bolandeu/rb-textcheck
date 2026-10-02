"""
Детерминированный линтер AI-слопа (русский текст).

Копия скрипта скилла humanizer-ru (`lint.py` v3, автор Serge Shima, MIT -
текст лицензии: rb_textcheck/data/LICENSE-humanizer-ru.txt), перенесённая
из antagor (utils/humanizer_lint.py, коммит 9a5e4d8) без изменения правил.
Класс A (артефакты чат-ботов) - порт из Vladimir-Human/humanizer-ru (MIT).
Расхождение правил со скиллом лечится переносом diff-а сюда.

Работает без зависимостей (только re) и ничего не знает о разметке: на вход -
чистовой текст. HTML сначала превратить в текст, иначе теги попадут в подсчёт
ритма и дадут ложные срабатывания.

Публичный API:
    lint(text) -> list[(kind, line_no, rule, excerpt)], kind = ERROR | WARN
    verdict(errors, warnings) -> (score, "clean" | "review ..." | "rewrite ...")

ERROR  = жёсткие запреты + артефакты копипаста из чат-ботов (гейт: текст не готов).
WARN   = маркеры паттернов и метрики ритма (оценивать кластерами).
Вердикт по severity: errors*3 + warnings -> clean (0-3) / review (4-10) / rewrite (11+).
Артефакт в бэктиках не считается: так артефакты цитируют, а не копипастят.

Self-test и запуск как скрипта остались в antagor: их случаи - в корпусе
vectors/cases/humanizer.yaml.
"""

import re

# --- класс A: артефакты копипаста из чат-ботов (мгновенный вердикт) ---
# Порт из Vladimir-Human/humanizer-ru (MIT); regex там проверены fixtures.
# Гоняются по сырому тексту (включая URL), но без code-блоков и бэктиков.
ARTIFACTS = [
    ("A oaicite-сноска", re.compile(r":contentReference\[oaicite:\d+\]|oai_citation:\d+‡|\boaicite:\d+")),
    ("A turn-метка", re.compile(r"\bturn\d+(?:search|file|fetch|image|news|video|ref)\d+|citeturn")),
    ("A utm/referrer чат-бота", re.compile(r"utm_source=(?:chatgpt|copilot)\.com|referrer=grok\.com")),
    ("A grok-карточка", re.compile(r"grok_card://|grok_render_citation_card_json|<grok-card\b")),
    (
        "A gemini-цитата",
        re.compile(r"vertexaisearch\S*grounding-api-redirect|\[cite_start\]|\[cite:\s*\d+|\[span_\d+\]"),
    ),
    ("A внутренняя сноска", re.compile(r"【\d+†[^】]*】|\]\(sandbox:/mnt/data/")),
    ("A остаток размышлений", re.compile(r"</?think>")),
    ("A perplexity-upload", re.compile(r"ppl-ai-file-upload")),
    ("A placeholder", re.compile(r"INSERT_SOURCE_URL|PASTE_\w+_URL_HERE|\bURL_HERE\b|\b20\d\d-XX-XX\b")),
    ("A PUA-метка", re.compile(r"[-]")),
]
CODE_STRIP = re.compile(r"```.*?```|`[^`\n]+`", re.S)  # цитируемые артефакты не считаем
# символы нулевой ширины - класс B (бывают от CMS и рассылок), поэтому WARN;
# ZWJ (U+200D) внутри эмодзи-последовательности - норма, ловим только вне эмодзи
EMOJI_CH = "[\U0001f000-\U0001faff☀-➿⬀-⯿️\U0001f3fb-\U0001f3ff]"
ZERO_WIDTH = re.compile(r"[​‌⁠﻿]|(?<!%s)‍|‍(?!%s)" % (EMOJI_CH, EMOJI_CH))

# --- жёсткие запреты (номера паттернов из references/patterns.md) ---
ERRORS = [
    ("23 длинное тире", re.compile(r"[—–]")),
    # Ловится знак, поставленный ВМЕСТО слова («тюль + портьеры», «Скорость >
    # идеальности»), а не математическая запись данных. Раньше правило брало
    # любой знак подряд, и на корпусе mw из 104 статей (замер 2026-09-24) это
    # давало 41 ложное срабатывание из 46: «UPF 50+» и «120+ стран» (25),
    # имена собственные вида «Arts & Crafts» (11), технические допуски «±3%»,
    # «±0,5°C» (5). Настоящих нарушений было 5, все - знак между словами.
    # Отсюда три отличия от исходного правила скилла humanizer-ru:
    #   - \d\+ убрано целиком: «50+» почти всегда характеристика, а «от 300
    #     штук» модели пишут словами;
    #   - & убрано: между словами это часть названия, а не союз;
    #   - ≈ ≥ ≤ ≠ ± убраны: это точность и допуски, то есть данные;
    #   - знаки = + > < считаются только между БУКВАМИ: «1 кВт = 1,36 л.с.» и
    #     «стоимость > 450 000 руб.» - расчёт, а не слоп.
    # Стрелки остаются жёсткими при любом окружении: это схема, а не проза.
    ("23 мат-знаки", re.compile(r"(?:[⇒←→]|(?<=[^\W\d_])\s[=+><]\s(?=[^\W\d_])|\bvs\.?\b)")),
    (
        "13 негативный параллелизм",
        re.compile(
            r"[Нн]е (?:просто|только)\b(?:[^.!?\n]{0,80}?\bно и\b)?|[Рр]ечь идёт не только|"
            r"[Нн]ет [^,.!?\n]{1,40}, нет "
        ),
    ),
    ("27 рубленый драматизм", re.compile(r"(?:Без|Ноль) [^.!?\n]{1,35}[.!] (?:Без|Ноль) ")),
]
HR_LINE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")

# --- маркеры для судейского прохода (кластеры решают, не одиночные хиты) ---
WARN_PHRASES = [
    # 3 избегание «это»
    "представляет собой",
    "выступает в роли",
    "служит основой",
    "знаменует собой",
    # 6 AI-словарь (стемы ловят словоформы)
    "ключев",
    "важнейш",
    "знаменует",
    "демонстрир",
    "способств",
    "подчёркива",
    "свидетельств",
    "неуклонно",
    # 10 размытые атрибуции
    "по мнению экспертов",
    "аналитики отмечают",
    "исследователи утверждают",
    # 11 шаблонные переходы
    "важно отметить",
    "следует подчеркнуть",
    "необходимо учитывать",
    "стоит обратить внимание",
    "нельзя не упомянуть",
    # 12 вызовы и перспективы
    "сталкивается с рядом вызовов",
    "несмотря на эти вызовы",
    # 17-18 подобострастие и артефакты чатбота
    "отличный вопрос",
    "надеюсь, это поможет",
    "надеюсь, было полезно",
    "дайте знать",
    "буду рад помочь",
    # 20 позитивные заключения
    "будущее выглядит ярким",
    "впереди захватывающие времена",
    "продолжает процветать",
    # 22 стоп-слова
    "в современном мире",
    "на сегодняшний день",
    "в настоящее время",
    "как известно",
    "не секрет, что",
    "ни для кого не секрет",
    "каждый из нас",
    # 25 псевдоглубина (+ faux-insight сетапы)
    "по сути",
    "если копнуть глубже",
    "глубинная проблема",
    "настоящий вопрос в том",
    "в конечном счёте",
    "все упускают",
    "большинство упускает",
    "никто не расскажет",
    "никто не говорит о",
    "главная ошибка большинства",
    "чего вам не расскажут",
    # 26 анонсы
    "давайте разберёмся",
    "погрузимся в",
    "вот что нужно знать",
    "без лишних слов",
    # 29 фальшивая доверительность
    "скажу прямо",
    "давайте начистоту",
    "вот в чём штука",
    "если по-честному",
    # 37 псевдо-терапевтический регистр
    "и это нормально",
    "и это окей",
    "вы не одиноки",
    "давайте признаем",
    "позвольте себе",
    # 31 резюме
    "подводя итог",
    "в заключение",
    "резюмируя",
    # 32 спекуляции
    "широко не задокументирован",
    "предположительно",
    # 34 стопка абзацев (фразы-склейки без связи)
    "кроме того",
    "более того",
    "также стоит",
    "ещё один аспект",
    "ещё одним",
]
WARN_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
# 19: три и более смягчения в одном предложении = каскад (одно-два - норма речи)
SOFTENERS = (
    "возможно",
    "вероятно",
    "по-видимому",
    "как правило",
    "в некоторых случаях",
    "скорее всего",
    "при определённых условиях",
    "обычно",
    "в зависимости от",
    "в большинстве случаев",
    "потенциально",
)
# colon reveal: «подводка: драматичное раскрытие» - только явные формы,
# чтобы не бить по спискам, меткам и обычным двоеточиям
COLON_REVEAL = re.compile(
    r"(?:[Сс]амое (?:интересное|главное|важное)|[Лл]учшая часть|[Гг]лавная деталь|"
    r"[Фф]ишка в том|[Дд]еталь, которая [^:\n]{0,35})\s*:"
)
BOLD_SPAN = re.compile(r"\*\*[^*\n]+\*\*")
INFORMAL = re.compile(r"\b(ты|вы|тебе|вам|твой|твоя|ваш|ваша|вами|тобой)\b", re.I)
# ponytail: стем-эвристика по глагольным суффиксам, морфологию не тянем;
# апгрейд до pymorphy - если станет много ложных срабатываний
VERB_SUFFIX = re.compile(r"(ует|яет|ает|еет|ит|ат|ят|ют|ал|ял|ил|ел|ся|сь|ть)$")

STRIP = re.compile(r"```.*?```|`[^`\n]+`|https?://\S+", re.S)  # код и URL не проза


def strip_frontmatter(lines):
    if lines and lines[0].strip() == "---":
        for i in range(1, min(len(lines), 40)):
            if lines[i].strip() == "---":
                return [""] * (i + 1) + lines[i + 1 :]
    return lines


def prose_sentences(lines):
    """Предложения из прозаических строк (без заголовков, таблиц, списков)."""
    prose = " ".join(line for line in lines if line.strip() and not re.match(r"^\s*(#|\||[-*+]\s|\d+\.\s|>)", line))
    prose = re.sub(r"\*\*|«|»", "", prose)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]


def verb_stems(sentence):
    stems = set()
    for w in re.findall(r"[а-яё]{5,}", sentence.lower()):
        if VERB_SUFFIX.search(w):
            stems.add(VERB_SUFFIX.sub("", w)[:6])
    return {s for s in stems if len(s) >= 4}


def lint(text):
    findings = []  # (kind, line_no, rule, excerpt)
    text = text.lstrip("﻿")  # BOM - артефакт кодировки, не текста

    # класс A: по сырому тексту (URL нужны для utm/referrer), но без бэктиков
    raw = CODE_STRIP.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for i, line in enumerate(strip_frontmatter(raw.splitlines()), 1):
        for rule, rx in ARTIFACTS:
            for m in rx.finditer(line):
                ctx = line[max(0, m.start() - 25) : m.end() + 25].strip()
                findings.append(("ERROR", i, rule, ctx))
        if ZERO_WIDTH.search(line):
            findings.append(
                (
                    "WARN",
                    i,
                    "B символ нулевой ширины",
                    "невидимый символ (CMS и рассылки тоже их ставят - проверь источник)",
                )
            )

    clean = STRIP.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = strip_frontmatter(clean.splitlines())

    for i, line in enumerate(lines, 1):
        if HR_LINE.match(line):
            findings.append(("ERROR", i, "34 разделитель в теле", line.strip()[:40]))
            continue
        scan = re.sub(r"^\s*[>+*]\s", "  ", line)  # markdown-маркеры не прозаические знаки
        for rule, rx in ERRORS:
            for m in rx.finditer(scan):
                ctx = scan[max(0, m.start() - 25) : m.end() + 25].strip()
                findings.append(("ERROR", i, rule, ctx))
        low = scan.lower()
        for phrase in WARN_PHRASES:
            if phrase in low:
                findings.append(("WARN", i, phrase, scan.strip()[:70]))
        if WARN_EMOJI.search(scan):
            findings.append(("WARN", i, "21 эмодзи", scan.strip()[:70]))
        if COLON_REVEAL.search(scan):
            findings.append(("WARN", i, "двоеточие-подводка", scan.strip()[:70]))

    sents = prose_sentences(lines)
    lengths = [len(s.split()) for s in sents]

    # 19: каскад смягчений - три и более уклончивых слова в одном предложении
    for s in sents:
        low = s.lower()
        hits = sum(low.count(w) for w in SOFTENERS)
        if hits >= 3:
            findings.append(("WARN", 0, "19 каскад смягчений", f"{hits} смягчения: {s[:60]}"))

    # 33: повтор глагольной основы в соседних предложениях
    for a, b in zip(range(len(sents) - 1), range(1, len(sents))):
        common = verb_stems(sents[a]) & verb_stems(sents[b])
        if common:
            findings.append(
                ("WARN", 0, "33 повтор глагола", f"«{sorted(common)[0]}…» в соседних предложениях: {sents[b][:50]}")
            )

    # ритм (burstiness): монотонность и отсутствие коротких предложений
    if len(lengths) >= 8:
        diffs = [abs(x - y) for x, y in zip(lengths, lengths[1:])]
        mean_diff = sum(diffs) / len(diffs)
        if mean_diff < 4:
            findings.append(
                (
                    "WARN",
                    0,
                    "ритм монотонный",
                    f"средняя разница длин соседних предложений {mean_diff:.1f} слова (живой текст: 6+)",
                )
            )
        if len(lengths) >= 10 and not any(n <= 8 for n in lengths):
            findings.append(("WARN", 0, "ритм без коротких", "ни одного предложения до 8 слов - нет пауз и акцентов"))

    # плотность жирного: максимум ~1 на 200 слов
    words_total = sum(lengths)
    bold_count = len(BOLD_SPAN.findall(text))
    if words_total >= 200 and bold_count > words_total / 200 + 1:
        findings.append(
            (
                "WARN",
                0,
                "жирный перебор",
                f"{bold_count} жирных на {words_total} слов (норма ~{max(1, words_total // 200)})",
            )
        )

    # формальное открытие: первые 3 предложения без единого неформального хода
    head = sents[:6]
    if len(head) >= 3:
        informal = (
            any(INFORMAL.search(s) for s in head)
            or any("?" in s for s in head)
            or any(len(s.split()) <= 8 for s in head)
        )
        if not informal:
            findings.append(
                ("WARN", 0, "формальное открытие", "в начале нет ни обращения, ни вопроса, ни короткой фразы")
            )

    return findings


def verdict(errors, warnings):
    score = errors * 3 + warnings
    if score <= 3:
        return score, "clean"
    if score <= 10:
        return score, "review - посмотри warnings кластерами"
    return score, "rewrite - слопа слишком много для точечных правок"
