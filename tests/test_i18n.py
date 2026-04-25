"""Tests for the locale-free weekday label helper."""
from __future__ import annotations

from datetime import UTC, datetime


def test_weekday_label_zh() -> None:
    from hyacine.i18n import weekday_label

    dt = datetime(2026, 4, 24, 0, 0, tzinfo=UTC)  # Friday
    assert weekday_label(dt, "zh-CN") == "星期五"
    assert weekday_label(dt, "zh-TW") == "星期五"
    assert weekday_label(dt, "ZH") == "星期五"  # case-insensitive


def test_weekday_label_ja() -> None:
    from hyacine.i18n import weekday_label

    dt = datetime(2026, 4, 24, 0, 0, tzinfo=UTC)  # Friday
    assert weekday_label(dt, "ja") == "金曜日"


def test_weekday_label_en_default() -> None:
    from hyacine.i18n import weekday_label

    dt = datetime(2026, 4, 24, 0, 0, tzinfo=UTC)  # Friday
    assert weekday_label(dt, "en") == "Friday"
    # Empty / unknown → English fallback so we never return None.
    assert weekday_label(dt, "") == "Friday"
    assert weekday_label(dt, "xx-XX") == "Friday"


def test_weekday_label_covers_full_week() -> None:
    from hyacine.i18n import weekday_label

    expected_zh = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
    # 2026-04-20 is a Monday; iterate one calendar week.
    for offset, want in enumerate(expected_zh):
        dt = datetime(2026, 4, 20 + offset, 0, 0, tzinfo=UTC)
        assert weekday_label(dt, "zh-CN") == want
