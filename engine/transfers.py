"""Transfer recommendations without external state."""

from datetime import timedelta
from math import isfinite

from ._common import (
    availableUnits, donorPenalties, maxTransferMinutes,
    minHoursLeftToTransfer, parseTime, routeLookup,
)

epsilon = 1e-9


def buildDemand(forecast: dict, nowTime, boundaries: set, penalties: dict) -> list[dict]:
    """Split uniform daily demand at expiry and arrival times for feasible matching."""
    midnight = nowTime.replace(hour=0, minute=0, second=0, microsecond=0)
    demand = []
    for hospitalId, groups in sorted(forecast.items()):
        for bloodGroup, dailyValues in sorted(groups.items()):
            for dayIndex, units in enumerate(dailyValues):
                if not isfinite(units) or units < 0:
                    raise ValueError("Forecast units must be finite and nonnegative")
                if units == 0:
                    continue
                dayStart = midnight + timedelta(days=dayIndex)
                start = max(nowTime, dayStart)
                end = dayStart + timedelta(days=1)
                cuts = [start, *sorted(at for at in boundaries if start < at < end), end]
                for left, right in zip(cuts, cuts[1:]):
                    demand.append({
                        "hospitalId": hospitalId, "bloodGroup": bloodGroup,
                        "start": left, "end": right,
                        "remaining": units * (right - left).total_seconds() / 86400,
                    })
    # Serve recipients with fewer compatible donor options first within a slot.
    demand.sort(key=lambda slot: (
        slot["start"], len(penalties.get(slot["bloodGroup"], {})),
        slot["hospitalId"], slot["bloodGroup"],
    ))
    return demand


def protectLocalStock(units: list[dict], demand: list[dict], penalties: dict) -> set:
    """Allocate local capacity first, protecting every unit used even fractionally."""
    capacity = {unit["unitId"]: 1.0 for unit in units}
    for slot in demand:
        recipientPenalties = penalties.get(slot["bloodGroup"], {})
        eligible = [unit for unit in units
                    if unit["hospitalId"] == slot["hospitalId"]
                    and unit["bloodGroup"] in recipientPenalties
                    and capacity[unit["unitId"]] > epsilon
                    and parseTime(unit["expiresAt"]) >= slot["end"]]
        eligible.sort(key=lambda unit: (
            parseTime(unit["collectedAt"]),
            recipientPenalties[unit["bloodGroup"]], unit["unitId"],
        ))
        for unit in eligible:
            used = min(capacity[unit["unitId"]], slot["remaining"])
            capacity[unit["unitId"]] -= used
            slot["remaining"] -= used
            if slot["remaining"] <= epsilon:
                break
    return {unitId for unitId, remaining in capacity.items() if remaining < 1 - epsilon}


def matchingDemand(unit: dict, hospitalId: str, arrivalTime, demand: list[dict],
                   penalties: dict) -> list[dict]:
    expiryTime = parseTime(unit["expiresAt"])
    eligible = [slot for slot in demand
                if slot["hospitalId"] == hospitalId and slot["remaining"] > epsilon
                and unit["bloodGroup"] in penalties.get(slot["bloodGroup"], {})
                and slot["start"] >= arrivalTime and slot["end"] <= expiryTime]
    eligible.sort(key=lambda slot: (
        penalties[slot["bloodGroup"]][unit["bloodGroup"]], slot["start"], slot["bloodGroup"],
    ))
    return eligible


def recommendTransfers(stock: list[dict], forecast: dict, travelTimes: list[dict],
                       compatibility: dict, now: str) -> list[dict]:
    """Match locally unused units to forecast shortfalls with a conservative greedy rule.

    Daily demand is uniform within UTC calendar days, index zero being today.
    Protect all stock allocated to local demand before considering donations.
    Then process the earliest expiries first, choosing destinations by preferred
    compatibility, expected use, and travel time. Consume recipient deficits
    immediately to prevent multiple donors filling the same expected demand.
    """
    nowTime = parseTime(now)
    units = availableUnits(stock, nowTime)
    routes = routeLookup(travelTimes)
    penalties = donorPenalties(compatibility)
    boundaries = {parseTime(unit["expiresAt"]) for unit in units}
    boundaries.update(nowTime + timedelta(minutes=minutes)
                      for minutes in routes.values() if minutes <= maxTransferMinutes)
    demand = buildDemand(forecast, nowTime, boundaries, penalties)
    protectedIds = protectLocalStock(units, demand, penalties)
    horizonDays = max((len(values) for groups in forecast.values()
                       for values in groups.values()), default=0)
    forecastEnd = (nowTime.replace(hour=0, minute=0, second=0, microsecond=0)
                   + timedelta(days=horizonDays))
    candidates = sorted((unit for unit in units if unit["unitId"] not in protectedIds),
                        key=lambda unit: (parseTime(unit["expiresAt"]), unit["unitId"]))
    transfers = []
    for unit in candidates:
        expiryTime = parseTime(unit["expiresAt"])
        hoursLeft = (expiryTime - nowTime).total_seconds() / 3600
        if hoursLeft < minHoursLeftToTransfer or expiryTime > forecastEnd:
            continue
        options = []
        for hospitalId in sorted(forecast):
            if hospitalId == unit["hospitalId"]:
                continue
            minutes = routes.get((unit["hospitalId"], hospitalId))
            if minutes is None or minutes > maxTransferMinutes:
                continue
            arrivalTime = nowTime + timedelta(minutes=minutes)
            if arrivalTime >= expiryTime:
                continue
            slots = matchingDemand(unit, hospitalId, arrivalTime, demand, penalties)
            if not slots:
                continue
            penalty = penalties[slots[0]["bloodGroup"]][unit["bloodGroup"]]
            expectedUse = min(1.0, sum(slot["remaining"] for slot in slots))
            options.append((penalty, -expectedUse, minutes, hospitalId, slots))
        if not options:
            continue
        penalty, negativeUse, minutes, hospitalId, slots = min(options, key=lambda option: option[:4])
        remaining = 1.0
        weightedPenalty = 0.0
        for slot in slots:
            used = min(remaining, slot["remaining"])
            slot["remaining"] -= used
            remaining -= used
            weightedPenalty += used * penalties[slot["bloodGroup"]][unit["bloodGroup"]]
            if remaining <= epsilon:
                break
        expectedUse = -negativeUse
        averagePenalty = weightedPenalty / expectedUse
        urgency = min(1.0, 24 / hoursLeft)
        score = expectedUse * urgency / (1 + averagePenalty + minutes / maxTransferMinutes)
        transfers.append({
            "unitId": unit["unitId"], "fromHospitalId": unit["hospitalId"],
            "toHospitalId": hospitalId, "travelMinutes": minutes,
            "hoursToExpiry": hoursLeft, "score": round(score, 6),
            "reason": (f"Expires in {hoursLeft:.1f}h at {unit['hospitalId']} "
                       f"(forecast use 0.0); {hospitalId} forecast unmet use "
                       f"{expectedUse:.2f} after arrival; compatibility penalty "
                       f"{averagePenalty:.2f}"),
        })
    transfers.sort(key=lambda transfer: (
        -transfer["score"], transfer["hoursToExpiry"], transfer["travelMinutes"],
        transfer["unitId"], transfer["toHospitalId"],
    ))
    return transfers
