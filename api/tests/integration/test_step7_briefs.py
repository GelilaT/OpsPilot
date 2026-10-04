"""Morning brief and weekly recap emails (runs last: it advances the shared demo clock by a day)."""

from tests.integration.scenario import simulate_day
from tests.integration.test_foundations import run_worker_until_idle


async def test_send_brief_now_records_a_delivery(client, copper):
    for kind in ("daily", "weekly"):
        r = await client.post("/api/v1/notifications/briefs/send", headers=copper["gm"], json={"kind": kind})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending" and r.json()["kind"] == f"{kind}_brief".replace("weekly_brief", "weekly_recap")
        await run_worker_until_idle()
    log = (await client.get("/api/v1/notifications/deliveries", headers=copper["gm"])).json()
    by_kind = {d["kind"]: d for d in log}
    assert by_kind["daily_brief"]["status"] in ("logged", "sent", "accepted")
    assert by_kind["weekly_recap"]["status"] in ("logged", "sent", "accepted")
    assert by_kind["daily_brief"]["subject"].startswith("Morning brief")


async def test_brief_is_forbidden_below_general_manager(client, copper):
    r = await client.post("/api/v1/notifications/briefs/send", headers=copper["shift"], json={"kind": "daily"})
    assert r.status_code == 403


async def test_simulated_day_sends_the_morning_brief(client, copper):
    before = len((await client.get("/api/v1/notifications/deliveries", headers=copper["gm"])).json())
    await simulate_day(client, copper)
    log = (await client.get("/api/v1/notifications/deliveries", headers=copper["gm"], params={"limit": 50})).json()
    assert len(log) > before and any(d["kind"] == "daily_brief" and ":manual:" not in d["subject"] for d in log)
