"""CalendarPort adapters: gov.uk Bank Holidays (cached 24 h) and the fixture fake."""

import time
from datetime import date
from decimal import Decimal

import httpx

from app.ports.errors import PermanentError, TransientError
from app.ports.weather import Holiday, LocalEvent

_CACHE: dict[str, tuple[float, dict]] = {}
TTL = 24 * 3600


class GovUkCalendar:
    provider = "govuk"
    url = "https://www.gov.uk/bank-holidays.json"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def _data(self) -> dict:
        cached = _CACHE.get(self.url)
        if cached and time.time() - cached[0] < TTL:
            return cached[1]
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
                resp = await client.get(self.url)
        except httpx.HTTPError as exc:
            raise TransientError(f"gov.uk connection problem: {exc}", provider=self.provider) from exc
        if resp.status_code >= 500:
            raise TransientError(f"gov.uk unavailable ({resp.status_code})", provider=self.provider)
        if resp.status_code != 200:
            raise PermanentError(f"gov.uk returned {resp.status_code}", provider=self.provider)
        data = resp.json()
        _CACHE[self.url] = (time.time(), data)
        return data

    async def holidays(self, region: str, year: int) -> list[Holiday]:
        data = await self._data()
        if region not in data:
            raise PermanentError(f"Unknown region {region!r}", provider=self.provider)
        return [Holiday(date.fromisoformat(e["date"]), e["title"], region)
                for e in data[region]["events"] if e["date"].startswith(str(year))]

    async def events(self, lat: Decimal, lng: Decimal, start: date, end: date) -> list[LocalEvent]:
        return []  # local events are not provided by gov.uk


class FixtureCalendar:
    provider = "fixture"

    async def holidays(self, region: str, year: int) -> list[Holiday]:
        from app.simulation.catalogue import holidays

        return [Holiday(d, title, region) for d, title in holidays(region) if d.year == year]

    async def events(self, lat: Decimal, lng: Decimal, start: date, end: date) -> list[LocalEvent]:
        return []
