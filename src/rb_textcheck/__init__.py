"""rb_textcheck - детерминированные проверки текста по профилю качества.

Библиотечно: ``rb_textcheck.check(text, profile, format)`` -> Result
(``.issues``, ``.humanizer``, ``.gate_failed``, ``.as_dict()``);
``rb_textcheck.fix(text, profile, format)`` -> FixResult (``.text``, ``.applied``, ``.unchanged``).
"""

from __future__ import annotations

from typing import Any

__all__ = ["FixResult", "ProfileError", "QualityProfile", "Result", "check", "fix", "load_profile", "rules"]


def rules() -> list[dict[str, Any]]:
    """Правила проверки: id, description, formats - в порядке выдачи."""
    from .core.checks import RULES

    return [dict(rule) for rule in RULES]


def __getattr__(name: str) -> Any:
    # Ленивый импорт: CLI (--version, --help) не платит за bs4/html5lib
    if name in ("check", "Result"):
        from .core import checks

        return getattr(checks, name)
    if name in ("fix", "FixResult"):
        from .core import fix

        return getattr(fix, name)
    if name in ("load_profile", "ProfileError", "QualityProfile"):
        from .core import profile

        return getattr(profile, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
