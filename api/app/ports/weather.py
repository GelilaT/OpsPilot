"""WeatherPort and CalendarPort (FR-ING-05)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WeatherDay:
    day: date
    temp_max_c: Decimal
    temp_min_c: Decimal
    precipitation_mm: Decimal
    source: str  # archive | forecast


@runtime_checkable
class WeatherPort(Protocol):
    provider: str

    async def forecast(self, lat: Decimal, lng: Decimal, days: list[date], timezone: str) -> list[WeatherDay]: ...

    async def history(self, lat: Decimal, lng: Decimal, start: date, end: date, timezone: str) -> list[WeatherDay]: ...


@dataclass(frozen=True)
class Holiday:
    day: date
    title: str
    region: str


@dataclass(frozen=True)
class LocalEvent:
    day: date
    title: str
    expected_attendance: int | None = None


@runtime_checkable
class CalendarPort(Protocol):
    provider: str

    async def holidays(self, region: str, year: int) -> list[Holiday]: ...

    async def events(self, lat: Decimal, lng: Decimal, start: date, end: date) -> list[LocalEvent]: ...
