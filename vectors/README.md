# Корпус-контракт textcheck

Текст → ожидаемые находки. Это контракт инструмента: `tests/test_vectors.py`
прогоняет каждый случай через `rb_textcheck.check` и сравнивает результат
целиком. Менять ожидание можно только вместе с решением, почему поведение
меняется (строка в `source` или комментарий в файле).

## Происхождение

Входы собраны из реальных случаев antagor (коммит `9a5e4d8`): его тесты
(`tests/test_truncation.py`, `test_markup_check.py`, `test_language_rules.py`,
`test_quality_profile.py`), self-test `utils/humanizer_lint.py` и профили
`prompts/*.quality.yml` (копии — в `profiles/`). Ожидания сняты с самого
antagor: `utils/quality_checks.run_all` с отключённым вторым контуром (LLM
снимал срабатывания запретов — в textcheck его нет, находка остаётся).

Одно сознательное отличие от antagor: находка без фрагмента относится ко
всей статье (`unit: article`) и в `md`, а не только в `html` — antagor в `md`
оставлял таким находкам (длина, формат, сводка предупреждений) `paragraph`.

## Формат случая (`cases/*.yaml` — список)

```yaml
- id: real-truncation-is-caught         # уникален в файле
  source: antagor tests/...              # откуда случай
  format: html | md                      # как читать текст
  profile: profiles/x.quality.yml        # путь от vectors/, inline-словарь или нет ключа (дефолты)
  text: "<p>...</p>"
  rules: [truncation]                    # необязательно: сравнивать только находки этих правил
  expect:
    gate_failed: true                    # по всем находкам, не только по rules
    humanizer: {score: 0, verdict: clean} # или null, если линтер выключен
    issues:                              # точный список, в порядке выдачи
      - {rule, message, excerpt, gate, unit, address, action}
```

## Автозамены (`fix/*.yaml` — список, T78 A)

```yaml
- id: x1-thirty-dashes
  source: T78 X1 ...
  format: html | md
  profile: profiles/fix-typography.quality.yml   # как в cases
  text: "<p>...</p>"
  expect:
    text: "<p>...</p>"                   # текст после всех замен, байт в байт
    unchanged: false
    applied:                             # только сработавшие замены, в порядке профиля
      - {name: длинное тире, count: 30, addresses: [{block: 0}]}   # html: block; md: line
```

Ожидаемый адрес — подмножество фактического (в html есть ещё `anchor`).

## Профили

- `profiles/*.quality.yml` — образцы из antagor, должны проходить
  `textcheck profile validate`.
- `profiles-invalid/*.quality.yml` — каждый должен давать отказ (код 2,
  `INVALID_PROFILE`); `profiles-invalid/expect.yaml` — какая подстрока (путь к
  ключу или суть отказа) должна быть в сообщении.
