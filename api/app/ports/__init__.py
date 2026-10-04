"""Ports: the only way core logic reaches external systems (FR-INT-01).

Each port is a typing.Protocol exchanging canonical domain types; adapters in app.adapters implement
them for one provider and are selected per organisation/site by IntegrationConnection (FR-INT-03).
"""

from enum import StrEnum


class IntegrationKind(StrEnum):
    pos = "pos"
    accounting = "accounting"
    ai = "ai"
    mail = "mail"
    weather = "weather"
    calendar = "calendar"
    storage = "storage"
