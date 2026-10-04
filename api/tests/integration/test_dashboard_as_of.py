"""Dashboard `as_of`: any past business day can be viewed; the default is the latest day."""

from datetime import date, timedelta

from tests.integration.scenario import business_date


async def test_dashboard_as_of(client, copper):
    today = await business_date(client, copper)
    base = (await client.get("/api/v1/dashboard", headers=copper["gm"])).json()
    assert base["business_date"] == base["latest_date"] == today.isoformat()
    assert base["earliest_date"] and date.fromisoformat(base["earliest_date"]) < today

    same = (await client.get("/api/v1/dashboard", headers=copper["gm"], params={"as_of": today.isoformat()})).json()
    assert same["kpis"] == base["kpis"]

    past = today - timedelta(days=10)
    r = await client.get("/api/v1/dashboard", headers=copper["gm"], params={"as_of": past.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business_date"] == past.isoformat() and body["latest_date"] == today.isoformat()
    assert body["kpis"] != base["kpis"]

    future = await client.get("/api/v1/dashboard", headers=copper["gm"],
                              params={"as_of": (today + timedelta(days=1)).isoformat()})
    assert future.status_code == 422
    ancient = await client.get("/api/v1/dashboard", headers=copper["gm"], params={"as_of": "2000-01-01"})
    assert ancient.status_code == 422
