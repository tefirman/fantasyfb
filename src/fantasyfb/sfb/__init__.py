"""Field-wide simulation for the Scott Fish Bowl (SFB).

The SFB plays hundreds of 12-team leagues whose playoffs run across the whole
field, so a team's odds depend on every other league. This package collects
the Sleeper leagues, simulates them together with one set of player draws, and
turns the results into qualification and round-by-round playoff odds.
"""
from .field import FieldData, FieldResult, Rules, simulate_field

__all__ = ["FieldData", "FieldResult", "Rules", "simulate_field"]
