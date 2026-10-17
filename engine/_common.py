"""Shared, stateless helpers; limits are contract v1.1 section 4 values."""

from datetime import datetime, timezone
from math import isfinite

maxTransferMinutes = 240
minHoursLeftToTransfer = 12


def parseTime(value: str) -> datetime:
    parsedTime = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsedTime.tzinfo is None:
        raise ValueError("Times must include a UTC offset")
    return parsedTime.astimezone(timezone.utc)


def availableUnits(stock: list[dict], nowTime: datetime) -> list[dict]:
    """Filter terminal/future stock and deduplicate IDs without modifying inputs."""
    unitsById = {}
    for unit in stock:
        if (unit["status"] == "available"
                and parseTime(unit["collectedAt"]) <= nowTime
                and parseTime(unit["expiresAt"]) > nowTime):
            unitsById.setdefault(unit["unitId"], unit)
    return [unitsById[unitId] for unitId in sorted(unitsById)]


def routeLookup(travelTimes: list[dict]) -> dict:
    """Routes are directed. Missing or invalid routes cannot be used."""
    routes = {}
    for route in travelTimes:
        minutes = route["minutes"]
        if not isfinite(minutes) or minutes < 0:
            continue
        routeKey = (route["fromHospitalId"], route["toHospitalId"])
        routes[routeKey] = min(minutes, routes.get(routeKey, minutes))
    return routes


def donorPenalties(compatibility: dict) -> dict:
    """Recipient -> donor -> preference; no implied compatibility rules."""
    penalties = {}
    for recipient, donors in compatibility.items():
        penalties[recipient] = {}
        for donor in donors:
            penalty = donor["penalty"]
            if not isfinite(penalty) or penalty < 0:
                raise ValueError("Compatibility penalties must be finite and nonnegative")
            donorGroup = donor["donor"]
            penalties[recipient][donorGroup] = min(
                penalty, penalties[recipient].get(donorGroup, penalty)
            )
    return penalties
