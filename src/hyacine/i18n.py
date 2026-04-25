"""Locale-free i18n helpers.

Small, dependency-light utilities for formatting language-aware
strings (weekday names, etc.) without relying on ``LC_ALL`` or the
host's locale data — useful for minimal containers and unit tests.
"""
from __future__ import annotations

from datetime import datetime

# Weekday names in the user's chosen language. Falls back to English
# when the language code isn't one we localise.
_WEEKDAY_LABELS_EN: tuple[str, ...] = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)
_WEEKDAY_LABELS_ZH: tuple[str, ...] = (
    "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
)
_WEEKDAY_LABELS_JA: tuple[str, ...] = (
    "月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日",
)


def weekday_label(dt: datetime, language: str) -> str:
    """Return the weekday name in the user's configured language.

    ``language`` accepts the same codes as ``YamlConfig.language``
    (``en`` / ``zh-CN`` / ``zh-TW`` / ``ja``). Unknown / empty codes
    resolve to English so callers always get a real string.
    """
    idx = dt.weekday()
    table = _WEEKDAY_LABELS_EN
    if language and language.lower().startswith("zh"):
        table = _WEEKDAY_LABELS_ZH
    elif language and language.lower().startswith("ja"):
        table = _WEEKDAY_LABELS_JA
    return table[idx]


__all__ = ["weekday_label"]
