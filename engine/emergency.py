"""Emergency ranking without external state."""

from datetime import timedelta

from ._common import availableUnits, donorPenalties, parseTime, routeLookup


def rankEmergencySources(request: dict, stock: list[dict], travelTimes: list[dict],
                         compatibility: dict, now: str) -> list[dict]:
    """Rank all compatible sources by penalty, travel time, then shelf life.

    Return alternatives beyond unitsNeeded, so a caller can retry a reservation.
    Emergency trips must arrive before expiry; routine transfer limits do not
    restrict emergency sourcing.
    """
    if request["unitsNeeded"] <= 0:
        return []
    nowTime = parseTime(now)
    routes = routeLookup(travelTimes)
    penalties = donorPenalties(compatibility).get(request["bloodGroup"], {})
    sources = []
    for unit in availableUnits(stock, nowTime):
        hospitalId = unit["hospitalId"]
        if hospitalId == request["hospitalId"] or unit["bloodGroup"] not in penalties:
            continue
        minutes = routes.get((hospitalId, request["hospitalId"]))
        expiryTime = parseTime(unit["expiresAt"])
        if minutes is None or nowTime + timedelta(minutes=minutes) >= expiryTime:
            continue
        sources.append({
            "unitId": unit["unitId"],
            "hospitalId": hospitalId,
            "bloodGroup": unit["bloodGroup"],
            "hoursToExpiry": (expiryTime - nowTime).total_seconds() / 3600,
            "travelMinutes": minutes,
            "penalty": penalties[unit["bloodGroup"]],
        })
    sources.sort(key=lambda source: (
        source["penalty"], source["travelMinutes"], source["hoursToExpiry"],
        source["hospitalId"], source["unitId"],
    ))
    for rank, source in enumerate(sources, 1):
        source["rank"] = rank
    return sources
