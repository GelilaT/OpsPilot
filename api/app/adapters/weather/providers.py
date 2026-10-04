"""WeatherPort adapters: Open-Meteo (forecast + archive, no key) and the deterministic fixture fake."""

from datetime import date
from decimal import Decimal

import httpx

from app.ports.errors import PermanentError, RateLimitedError, TransientError
from app.ports.weather import WeatherDay

DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum"


class OpenMeteoWeather:
    provider = "open_meteo"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def _get(self, url: str, params: dict, source: str) -> list[WeatherDay]:
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise TransientError(f"Open-Meteo connection problem: {exc}", provider=self.provider) from exc
        if resp.status_code == 429:
            raise RateLimitedError("Open-Meteo rate limit", retry_after=60, provider=self.provider)
        if resp.status_code >= 500:
            raise TransientError(f"Open-Meteo unavailable ({resp.status_code})", provider=self.provider)
        if resp.status_code != 200:
            raise PermanentError(f"Open-Meteo rejected the request: {resp.text[:200]}", provider=self.provider)
        daily = resp.json().get("daily", {})
        out = []
        for d, hi, lo, rain in zip(daily.get("time", []), daily.get("temperature_2m_max", []),
                                   daily.get("temperature_2m_min", []), daily.get("precipitation_sum", []),
                                   strict=False):
            if None in (hi, lo, rain):
                continue
            out.append(WeatherDay(date.fromisoformat(d), Decimal(str(hi)), Decimal(str(lo)), Decimal(str(rain)),
                                  source))
        return out

    async def forecast(self, lat: Decimal, lng: Decimal, days: list[date], timezone: str) -> list[WeatherDay]:
        if not days:
            return []
        params = {"latitude": str(lat), "longitude": str(lng), "daily": DAILY, "timezone": timezone,
                  "start_date": min(days).isoformat(), "end_date": max(days).isoformat()}
        rows = await self._get("https://api.open-meteo.com/v1/forecast", params, "forecast")
        wanted = set(days)
        return [r for r in rows if r.day in wanted]

    async def history(self, lat: Decimal, lng: Decimal, start: date, end: date, timezone: str) -> list[WeatherDay]:
        params = {"latitude": str(lat), "longitude": str(lng), "daily": DAILY, "timezone": timezone,
                  "start_date": start.isoformat(), "end_date": end.isoformat()}
        return await self._get("https://archive-api.open-meteo.com/v1/archive", params, "archive")


class FixtureWeather:
    """Offline fake: real recorded history for the demo cities, climatology elsewhere."""

    provider = "fixture"

    def __init__(self, city: str) -> None:
        self.city = city

    def _day(self, d: date) -> WeatherDay:
        from app.simulation.catalogue import weather

        w = weather(self.city, d)
        return WeatherDay(d, w.temp_max, w.temp_min, w.precipitation, w.source)

    async def forecast(self, lat: Decimal, lng: Decimal, days: list[date], timezone: str) -> list[WeatherDay]:
        return [self._day(d) for d in days]

    async def history(self, lat: Decimal, lng: Decimal, start: date, end: date, timezone: str) -> list[WeatherDay]:
        out, d = [], start
        while d <= end:
            out.append(self._day(d))
            d = date.fromordinal(d.toordinal() + 1)
        return out
