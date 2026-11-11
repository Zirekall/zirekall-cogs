"""Czysta logika grafiku i okien snu (bez zaleznosci od discord/redbot)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Dict, List, NamedTuple, Optional

# Kody zmian z grafiku zakladowego.
SHIFT_CODES: Dict[str, str] = {
    "i": "06:00",
    "1": "06:00",
    "ii": "14:00",
    "2": "14:00",
    "iii": "22:00",
    "3": "22:00",
}
OFF_CODES = {"-", "x", "w", "0", "wolne", "wolny", "brak", "off"}
CODE_BY_TIME = {"06:00": "I", "14:00": "II", "22:00": "III"}


class SleepWindow(NamedTuple):
    shift_start: datetime
    start: datetime
    end: datetime


def parse_hhmm(value: Optional[str]) -> Optional[time]:
    """Zamienia 'HH:MM' na time, albo zwraca None gdy format jest zly."""
    if not value:
        return None
    try:
        hours_txt, minutes_txt = value.strip().split(":")
        hours, minutes = int(hours_txt), int(minutes_txt)
    except ValueError:
        return None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return time(hour=hours, minute=minutes)


class BadToken(ValueError):
    pass


def parse_shift(token: str) -> Optional[str]:
    """'I'/'II'/'III'/'HH:MM' -> 'HH:MM', kod wolnego -> None, inaczej BadToken."""
    tok = token.strip().lower()
    if tok in SHIFT_CODES:
        return SHIFT_CODES[tok]
    if tok in OFF_CODES:
        return None
    parsed = parse_hhmm(tok)
    if parsed is None:
        raise BadToken(token)
    return parsed.strftime("%H:%M")


def parse_date(text: str) -> Optional[date]:
    """Przyjmuje 'YYYY-MM-DD' albo 'DD.MM.YYYY'."""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_month(year: int, month: int, tokens: List[str]) -> Dict[str, Optional[str]]:
    """Zamienia liste kodow (po jednym na dzien miesiaca) na {data_iso: 'HH:MM' | None}."""
    days = calendar.monthrange(year, month)[1]
    if len(tokens) != days:
        raise ValueError(f"Miesiac {year}-{month:02d} ma {days} dni, podano {len(tokens)} pozycji.")
    return {date(year, month, i + 1).isoformat(): parse_shift(tok) for i, tok in enumerate(tokens)}


def sleep_windows(
    shifts: Dict[str, str],
    around: datetime,
    tz: tzinfo,
    sleep_hours: float,
    buffer_minutes: int,
    days_before: int = 1,
    days_after: int = 1,
) -> List[SleepWindow]:
    """Zwraca okna snu dla zmian z dni [around - days_before, around + days_after].

    shifts: {"YYYY-MM-DD": "HH:MM"} - start zmiany danego dnia (brak klucza = wolne).
    Okno konczy sie `buffer_minutes` przed startem zmiany i trwa `sleep_hours`.
    Odejmowanie liczone w UTC, wiec zmiana czasu (DST) nie psuje dlugosci snu.
    """
    base: date = around.astimezone(tz).date()
    sleep = timedelta(hours=sleep_hours)
    buffer = timedelta(minutes=buffer_minutes)

    result: List[SleepWindow] = []
    for offset in range(-days_before, days_after + 1):
        day = base + timedelta(days=offset)
        shift_time = parse_hhmm(shifts.get(day.isoformat()))
        if shift_time is None:
            continue
        shift_start = datetime.combine(day, shift_time, tzinfo=tz)
        shift_utc = shift_start.astimezone(timezone.utc)
        end = (shift_utc - buffer).astimezone(tz)
        start = (shift_utc - buffer - sleep).astimezone(tz)
        result.append(SleepWindow(shift_start, start, end))

    result.sort(key=lambda w: w.start)
    return result


def current_window(
    shifts: Dict[str, str],
    now: datetime,
    tz: tzinfo,
    sleep_hours: float,
    buffer_minutes: int,
) -> Optional[SleepWindow]:
    """Zwraca okno snu trwajace w chwili `now`, albo None."""
    # Okno moze zaczac sie do ~2 dob przed startem zmiany (maks. 16h snu + 10h bufora),
    # wiec sprawdzamy zmiany z dzisiaj i 2 kolejnych dni.
    for window in sleep_windows(shifts, now, tz, sleep_hours, buffer_minutes, days_before=1, days_after=2):
        if window.start <= now < window.end:
            return window
    return None
