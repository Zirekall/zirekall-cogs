"""Startowa konfiguracja SleepGuard (przepisana z papierowego grafiku zmiany C na 2026)."""

from __future__ import annotations

from typing import Dict

from .windows import parse_month

DEFAULT_GUILD_ID = 1554544870532710440
DEFAULT_USER_ID = 401759735818223617
DEFAULT_ROLE_ID = 1570187618619105422

# Jeden kod na dzien miesiaca: I = 06:00, II = 14:00, III = 22:00, "-" = wolne.
# Uwaga: dzien wolny za swieto w sobote 26.12 ma byc wyznaczony pozniej -
# trzeba go wtedy ustawic komenda `[p]sen zmiana <data> wolne`.
DEFAULT_MONTHS = {
    (2026, 11): "- II II II II II - - I I - I I - - III III III III III - - II II II II II - - I",
    (2026, 12): "I I I I - - III III III III III - - II II II II II - - I I I - - - - III III III III",
}


def default_shifts() -> Dict[str, str]:
    shifts: Dict[str, str] = {}
    for (year, month), codes in DEFAULT_MONTHS.items():
        for day, value in parse_month(year, month, codes.split()).items():
            if value is not None:
                shifts[day] = value
    return shifts
