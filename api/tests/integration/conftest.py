"""Shared fixtures for the Copper Pot demo flows (Steps 4-6)."""

import pytest

from app.simulation.profiles import COPPER_POT
from tests.conftest import auth
from tests.integration.test_step4_flow2 import demo_token, site_id


@pytest.fixture
async def copper(client, seeded):
    """Signed-in Copper Pot users at CP1 (owner, GM, head chef, shift manager)."""
    cp1 = site_id(COPPER_POT, "CP1")
    out = {"site": cp1}
    for role, email in (("owner", "owner@copperpot.example"), ("gm", "gm@copperpot.example"),
                        ("chef", "chef@copperpot.example"), ("shift", "shift@copperpot.example")):
        out[role] = auth(await demo_token(client, COPPER_POT, email), cp1)
    return out
