"""
sim/generate.py  --  Scenario generator for the platelet exchange simulation.

generateScenario() produces the raw input data for runSimulation():
  - deliveries: one or more Unit dicts per hospital per day, blood group
    sampled from the mix in assumptions.json, shelf life randomised
    within the remainingShelfLifeOnArrivalDays window.
  - demand: one DemandRecord per hospital per day per blood group that has
    non-zero expected demand, drawn from a Poisson-like distribution around
    dailyDemandMean adjusted for weekday/weekend.

All randomness goes through a seeded random.Random instance so the same
seed always produces the same scenario.
"""

import random
from datetime import datetime, timedelta, timezone


_SIM_START = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
_SHELF_LIFE_DAYS = 7


def _isoUtc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _isWeekend(dt: datetime) -> bool:
    return dt.weekday() >= 5  # Saturday=5, Sunday=6


def _sampleBloodGroup(bloodGroupMix: dict, rng: random.Random) -> str:
    """Pick a blood group weighted by the mix fractions."""
    groups = list(bloodGroupMix.keys())
    weights = [bloodGroupMix[g] for g in groups]
    # manual weighted choice -- no random.choices to stay explicit
    r = rng.random()
    cumulative = 0.0
    for group, weight in zip(groups, weights):
        cumulative += weight
        if r < cumulative:
            return group
    return groups[-1]  # fallback for floating-point edge


def _poissonApprox(mean: float, rng: random.Random) -> int:
    """
    Approximate a Poisson draw using the inversion method.
    Safe for small means (< 30), which covers all our hospital sizes.
    """
    if mean <= 0:
        return 0
    L = 2.718281828 ** (-mean)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


def generateScenario(assumptions: dict, hospitals: list[dict], seed: int) -> dict:
    """
    Returns {"deliveries": [Unit...], "demand": [DemandRecord...]} for simDays.

    Unit shape (CONTRACT §5):
        unitId, bloodGroup, collectedAt, expiresAt, hospitalId, status

    DemandRecord shape (CONTRACT §5):
        date, hospitalId, bloodGroup, units
    """
    rng = random.Random(seed)

    simDays: int = assumptions["simDays"]
    demandMean: dict = assumptions["dailyDemandMean"]   # {"small": 1, "medium": 3, "large": 8}
    weekendFactor: float = assumptions["weekendDemandFactor"]
    bloodGroupMix: dict = assumptions["bloodGroupMix"]
    shelfLeft: dict = assumptions["remainingShelfLifeOnArrivalDays"]  # {"min": 1, "max": 4}

    deliveries: list[dict] = []
    demand: list[dict] = []

    unitCounter = 0

    for dayIndex in range(simDays):
        dayStart = _SIM_START + timedelta(days=dayIndex)
        isWeekend = _isWeekend(dayStart)
        dateStr = dayStart.strftime("%Y-%m-%d")

        for hospital in hospitals:
            hospitalId: str = hospital["hospitalId"]
            size: str = hospital["sizeCategory"]
            baseMean: float = float(demandMean[size])
            effectiveMean: float = baseMean * (weekendFactor if isWeekend else 1.0)

            # --- deliveries ---
            # Number of units delivered today ≈ expected daily demand
            # (supply is calibrated to demand in the real world)
            numDelivered = max(1, _poissonApprox(effectiveMean, rng))

            for _ in range(numDelivered):
                unitCounter += 1
                unitId = f"U{unitCounter:06d}"
                bloodGroup = _sampleBloodGroup(bloodGroupMix, rng)

                # remainingShelfLife is how many days left when it arrives
                remainingDays = rng.randint(shelfLeft["min"], shelfLeft["max"])
                # collectedAt is in the past so that expiresAt = collectedAt + 7 days
                # and remainingDays = expiresAt - deliveredAt in whole days
                collectedAt = dayStart - timedelta(days=_SHELF_LIFE_DAYS - remainingDays)
                expiresAt = collectedAt + timedelta(days=_SHELF_LIFE_DAYS)

                deliveries.append({
                    "unitId": unitId,
                    "bloodGroup": bloodGroup,
                    "collectedAt": _isoUtc(collectedAt),
                    "expiresAt": _isoUtc(expiresAt),
                    "hospitalId": hospitalId,
                    "status": "available",
                })

            # --- demand ---
            # Draw per-blood-group demand; only emit records where units > 0
            for bloodGroup, mixFraction in bloodGroupMix.items():
                groupMean = effectiveMean * mixFraction
                units = _poissonApprox(groupMean, rng)
                if units > 0:
                    demand.append({
                        "date": dateStr,
                        "hospitalId": hospitalId,
                        "bloodGroup": bloodGroup,
                        "units": units,
                    })

    return {"deliveries": deliveries, "demand": demand}
