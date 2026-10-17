"""
sim/generate.py  --  Scenario generator for the platelet exchange simulation.

generateScenario() produces the raw input data for runSimulation():
  - demand: one DemandRecord per hospital per day per blood group that has
    non-zero expected demand, drawn from a Poisson-like distribution around
    dailyDemandMean adjusted for weekday/weekend.
  - deliveries: what each hospital orders to keep targetStockDays of cover
    per blood group, given its own baseline consumption.

Hospitals order rather than receive blind shipments, which is how a blood
service actually restocks: each morning a hospital tops its shelf back up to
targetStockDays of expected use. Drawing deliveries independently of
consumption instead sends rare groups to hospitals that will never use them,
and with only remainingShelfLifeOnArrivalDays of life left they are binned.

Ordering is driven by baseline (noSharing) consumption, so both policies get
exactly the same deliveries and the comparison stays fair.

All randomness goes through a seeded random.Random instance so the same
seed always produces the same scenario.
"""

import math
import random
from datetime import datetime, timedelta, timezone


_SIM_START = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
_SHELF_LIFE_DAYS = 5

# A hospital stocks a group once it expects to use roughly half a unit of
# cover; below that it relies on ordering in or on a transfer.
_MIN_STOCK_THRESHOLD = 0.5

# Emergencies: a major haemorrhage pulls several units of one group at once
# and empties that shelf. Rate scales with hospital size via dailyDemandMean,
# so a large centre sees roughly one every two weeks.
# PLACEHOLDER VALUES -- Person 5 to source these in docs/assumptions.md.
_EMERGENCY_RATE_DIVISOR = 100.0
_EMERGENCY_UNITS_MIN = 3
_EMERGENCY_UNITS_MAX = 6


def _isoUtc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _isWeekend(dt: datetime) -> bool:
    return dt.weekday() >= 5  # Saturday=5, Sunday=6


def _sampleBloodGroup(bloodGroupMix: dict, rng: random.Random) -> str:
    """Pick a blood group weighted by the mix fractions (the patient's own group)."""
    r = rng.random()
    cumulative = 0.0
    for group, weight in bloodGroupMix.items():
        cumulative += weight
        if r < cumulative:
            return group
    return list(bloodGroupMix)[-1]  # fallback for floating-point edge


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
    targetStockDays: dict = assumptions["targetStockDays"]  # {"small": 2, "medium": 2, "large": 1.5}

    # --- demand, drawn first so ordering can be driven by it ---
    demand: list[dict] = []
    demandIndex: dict = {}
    for dayIndex in range(simDays):
        dayStart = _SIM_START + timedelta(days=dayIndex)
        isWeekend = _isWeekend(dayStart)
        dateStr = dayStart.strftime("%Y-%m-%d")

        for hospital in hospitals:
            hospitalId: str = hospital["hospitalId"]
            baseMean: float = float(demandMean[hospital["sizeCategory"]])
            effectiveMean: float = baseMean * (weekendFactor if isWeekend else 1.0)

            dayUnits: dict = {}
            for bloodGroup, mixFraction in bloodGroupMix.items():
                units = _poissonApprox(effectiveMean * mixFraction, rng)
                if units > 0:
                    dayUnits[bloodGroup] = units

            # Emergency admission: one patient, several units of their own group
            # at once. Emergencies do not wait for a weekday, so this is not
            # scaled by weekendFactor.
            if rng.random() < baseMean / _EMERGENCY_RATE_DIVISOR:
                emergencyGroup = _sampleBloodGroup(bloodGroupMix, rng)
                emergencyUnits = rng.randint(_EMERGENCY_UNITS_MIN, _EMERGENCY_UNITS_MAX)
                dayUnits[emergencyGroup] = dayUnits.get(emergencyGroup, 0) + emergencyUnits

            for bloodGroup, units in dayUnits.items():
                demand.append({
                    "date": dateStr,
                    "hospitalId": hospitalId,
                    "bloodGroup": bloodGroup,
                    "units": units,
                })
                demandIndex[(dayIndex, hospitalId, bloodGroup)] = units

    # --- deliveries: each hospital tops up to its target cover every morning ---
    deliveries: list[dict] = []
    unitCounter = 0
    shelf: dict = {}  # (hospitalId, bloodGroup) -> expiry datetimes, oldest first

    for dayIndex in range(simDays):
        dayStart = _SIM_START + timedelta(days=dayIndex)

        for hospital in hospitals:
            hospitalId = hospital["hospitalId"]
            size = hospital["sizeCategory"]
            cover = float(targetStockDays[size]) * float(demandMean[size])

            for bloodGroup, mixFraction in bloodGroupMix.items():
                onShelf = shelf.setdefault((hospitalId, bloodGroup), [])
                onShelf[:] = [e for e in onShelf if e > dayStart]

                # Round up, never down: a hospital that is one unit short has a
                # patient waiting, so it carries the spare rather than trim to fit.
                expected = cover * mixFraction
                target = math.ceil(expected) if expected >= _MIN_STOCK_THRESHOLD else 0
                # Haematology centres carry a unit of every group, including the rare
                # ones their own demand never justifies; without that nobody in the
                # region holds AB- and the exchange has nothing to move.
                if hospital["hasHaematology"]:
                    target = max(target, 1)

                for _ in range(max(0, target - len(onShelf))):
                    unitCounter += 1
                    remainingDays = rng.randint(shelfLeft["min"], shelfLeft["max"])
                    collectedAt = dayStart - timedelta(days=_SHELF_LIFE_DAYS - remainingDays)
                    expiresAt = collectedAt + timedelta(days=_SHELF_LIFE_DAYS)

                    deliveries.append({
                        "unitId": f"U{unitCounter:06d}",
                        "bloodGroup": bloodGroup,
                        "collectedAt": _isoUtc(collectedAt),
                        "expiresAt": _isoUtc(expiresAt),
                        "hospitalId": hospitalId,
                        "status": "available",
                        "deliveredAt": _isoUtc(dayStart),  # sim-internal; not in CONTRACT Unit shape
                    })
                    onShelf.append(expiresAt)

                onShelf.sort()
                used = min(demandIndex.get((dayIndex, hospitalId, bloodGroup), 0), len(onShelf))
                del onShelf[:used]

    return {"deliveries": deliveries, "demand": demand}
