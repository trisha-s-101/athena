"""
sim/multirun.py  --  Multi-seed runs and stress scenarios (+16h milestone).

Exports:
    runMultiSeed(assumptions, hospitals, seeds) -> dict  (statistics block)
    runStressScenarios(assumptions, hospitals, seed) -> dict  (stressScenarios block)
"""

import math
import copy
from datetime import timedelta

from sim.generate import generateScenario, _SIM_START, _isoUtc
from sim.simulate import runSimulation


# ---------------------------------------------------------------------------
# Statistics helpers (no numpy/scipy -- standard library only)
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdDev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _stats(values: list[float]) -> dict:
    return {
        "mean": round(_mean(values), 4),
        "stdDev": round(_stdDev(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


# ---------------------------------------------------------------------------
# Multi-seed runner
# ---------------------------------------------------------------------------

def runMultiSeed(assumptions: dict, hospitals: list[dict], seeds: list[int]) -> dict:
    """
    Run both policies for each seed and return aggregate statistics.

    Returns a dict with shape:
        {
          "seeds": [...],
          "statistics": {
            "noSharing": { "wasteRate": {mean,stdDev,min,max}, "shortageEvents": {...}, "transfers": 0 },
            "exchange":  { "wasteRate": {...}, "shortageEvents": {...}, "transfers": {...} }
          }
        }
    """
    noSharingResults: list[dict] = []
    exchangeResults: list[dict] = []

    for seed in seeds:
        scenario = generateScenario(assumptions, hospitals, seed)
        noSharingResults.append(runSimulation(scenario, "noSharing", seed))
        exchangeResults.append(runSimulation(scenario, "exchange", seed))

    def _policyStats(results: list[dict], policy: str) -> dict:
        wasteRates = [r["wasteRate"] for r in results]
        shortages = [float(r["shortageEvents"]) for r in results]
        transfers = [float(r["transfers"]) for r in results]
        out: dict = {
            "wasteRate": _stats(wasteRates),
            "shortageEvents": _stats(shortages),
        }
        if policy == "exchange":
            out["transfers"] = _stats(transfers)
        else:
            out["transfers"] = 0
        return out

    return {
        "seeds": seeds,
        "statistics": {
            "noSharing": _policyStats(noSharingResults, "noSharing"),
            "exchange": _policyStats(exchangeResults, "exchange"),
        },
        "_rawResults": {
            "noSharing": noSharingResults,
            "exchange": exchangeResults,
        },
    }


# ---------------------------------------------------------------------------
# Stress scenario helpers
# ---------------------------------------------------------------------------

def _demandSurgeScenario(assumptions: dict, hospitals: list[dict], seed: int,
                          surgeHospitalId: str = "H01",
                          surgeFactor: float = 3.0,
                          surgeStartDay: int = 30,
                          surgeDurationDays: int = 7) -> dict:
    """
    Base scenario with H01 demand multiplied by surgeFactor for surgeDurationDays
    starting at surgeStartDay.
    """
    scenario = generateScenario(assumptions, hospitals, seed)

    surgeStart = _SIM_START + timedelta(days=surgeStartDay)
    surgeEnd = surgeStart + timedelta(days=surgeDurationDays)

    # Multiply demand records for the surge hospital/window
    surgedDemand = []
    for rec in scenario["demand"]:
        from datetime import datetime, timezone
        recDate = datetime.strptime(rec["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if rec["hospitalId"] == surgeHospitalId and surgeStart <= recDate < surgeEnd:
            surgedRec = dict(rec)
            surgedRec["units"] = max(1, round(rec["units"] * surgeFactor))
            surgedDemand.append(surgedRec)
        else:
            surgedDemand.append(rec)

    return {
        "deliveries": scenario["deliveries"],
        "demand": surgedDemand,
    }


def _supplyDipScenario(assumptions: dict, hospitals: list[dict], seed: int,
                        dipStartDay: int = 45,
                        dipDurationDays: int = 3) -> dict:
    """
    Base scenario with all deliveries removed for dipDurationDays starting at dipStartDay.
    """
    scenario = generateScenario(assumptions, hospitals, seed)

    dipStart = _SIM_START + timedelta(days=dipStartDay)
    dipEnd = dipStart + timedelta(days=dipDurationDays)

    filteredDeliveries = []
    for unit in scenario["deliveries"]:
        from datetime import datetime, timezone
        delivDate = datetime.strptime(unit["deliveredAt"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if dipStart <= delivDate < dipEnd:
            continue  # suppress this delivery
        filteredDeliveries.append(unit)

    return {
        "deliveries": filteredDeliveries,
        "demand": scenario["demand"],
    }


def runStressScenarios(assumptions: dict, hospitals: list[dict], seed: int = 42) -> dict:
    """
    Run both stress scenarios (demand surge, supply dip) under both policies.
    Returns the stressScenarios block of comparison.json.
    """
    surgeHospitalId = hospitals[0]["hospitalId"] if hospitals else "H01"
    surgeStartDay = assumptions["simDays"] // 3      # ~day 30 of 90
    surgeDurationDays = 7
    dipStartDay = assumptions["simDays"] // 2        # ~day 45 of 90
    dipDurationDays = 3

    surgeScenario = _demandSurgeScenario(
        assumptions, hospitals, seed,
        surgeHospitalId=surgeHospitalId,
        surgeFactor=3.0,
        surgeStartDay=surgeStartDay,
        surgeDurationDays=surgeDurationDays,
    )
    dipScenario = _supplyDipScenario(
        assumptions, hospitals, seed,
        dipStartDay=dipStartDay,
        dipDurationDays=dipDurationDays,
    )

    surgeNoSharing = runSimulation(surgeScenario, "noSharing", seed)
    surgeExchange = runSimulation(surgeScenario, "exchange", seed)
    dipNoSharing = runSimulation(dipScenario, "noSharing", seed)
    dipExchange = runSimulation(dipScenario, "exchange", seed)

    surgeStart = (_SIM_START + timedelta(days=surgeStartDay)).strftime("%Y-%m-%d")
    surgeEnd = (_SIM_START + timedelta(days=surgeStartDay + surgeDurationDays)).strftime("%Y-%m-%d")
    dipStart = (_SIM_START + timedelta(days=dipStartDay)).strftime("%Y-%m-%d")
    dipEnd = (_SIM_START + timedelta(days=dipStartDay + dipDurationDays)).strftime("%Y-%m-%d")

    return {
        "demandSurge": {
            "description": (
                f"{surgeHospitalId} demand 3x for {surgeDurationDays} days "
                f"({surgeStart} to {surgeEnd})"
            ),
            "noSharing": surgeNoSharing,
            "exchange": surgeExchange,
        },
        "supplyDip": {
            "description": (
                f"No deliveries for {dipDurationDays} days "
                f"({dipStart} to {dipEnd})"
            ),
            "noSharing": dipNoSharing,
            "exchange": dipExchange,
        },
    }
