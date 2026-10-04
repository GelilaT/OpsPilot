"""Configuration registry validation (FR-TEN-04, FR-SET-01)."""

import pytest

from app.core.errors import Unprocessable
from app.core.tenancy.config import REGISTRY


def test_every_key_has_a_valid_default():
    for spec in REGISTRY.values():
        assert spec.validate(spec.dump(spec.default)) == spec.validate(spec.default)


def test_invalid_values_are_rejected():
    with pytest.raises(Unprocessable):
        REGISTRY["invoice.price_increase_pct"].validate("lots")
    with pytest.raises(Unprocessable):
        REGISTRY["site.dayparts"].validate([{"name": "brunch", "start": "09:00", "end": "11:00"}])


def test_role_limits_round_trip():
    spec = REGISTRY["approval.invoice_limits"]
    value = spec.validate({"head_chef": 75000, "general_manager": 750000, "owner": None})
    assert value.head_chef == 75000 and value.owner is None
    assert spec.dump(value)["general_manager"] == 750000
