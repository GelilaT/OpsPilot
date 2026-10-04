from app.simulation.profile import OrgProfile
from app.simulation.profiles.copper_pot import COPPER_POT
from app.simulation.profiles.northside import NORTHSIDE

PROFILES: dict[str, OrgProfile] = {p.slug: p for p in (COPPER_POT, NORTHSIDE)}

__all__ = ["COPPER_POT", "NORTHSIDE", "PROFILES"]
