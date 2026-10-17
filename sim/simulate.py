"""
sim/simulate.py  --  Core simulation engine (CONTRACT §7).

runSimulation(scenario, policyName, seed) -> SimResult

The sim clock ticks in 6-hour steps. Each tick:
  1. Deliver units whose day matches the current date.
  2. Arrive any in-transit units whose travel time has elapsed.
  3. Expire units whose expiresAt <= now.
  4. exchange only: call engine.forecastDemand + engine.recommendTransfers
     and dispatch recommended transfers.
  5. At midnight (step 0 of each day): issue FIFO demand and record daily stats.

FIFO issuing: oldest unit (by collectedAt) is transfused first.
"""

import copy
import json
import pathlib
from datetime import datetime, timedelta, timezone

_REPO_ROOT = pathlib.Path(__file__).parents[1]
_SIM_START = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
_STEP_HOURS = 6
_STEPS_PER_DAY = 24 // _STEP_HOURS  # 4


# ---------------------------------------------------------------------------
# Shared-file helpers (safe defaults when files not yet committed)
# ---------------------------------------------------------------------------

def _loadJson(relPath: str, default):
    p = _REPO_ROOT / relPath
    if p.exists():
        return json.loads(p.read_text())
    return default


def _loadTravelTimes() -> list[dict]:
    return _loadJson("shared/travelTimes.json", [])


def _loadCompatibility() -> dict:
    return _loadJson("shared/compatibility.json", {})


# ---------------------------------------------------------------------------
# Engine import with graceful fallback stub
# ---------------------------------------------------------------------------

def _stubForecast(history: list[dict], horizonDays: int = 3) -> dict:
    """Naive forecast: repeat yesterday's demand for each hospital/group."""
    latest: dict = {}
    for rec in history:
        key = (rec["hospitalId"], rec["bloodGroup"])
        latest[key] = rec["units"]
    result: dict = {}
    for (hId, bg), units in latest.items():
        result.setdefault(hId, {})[bg] = [float(units)] * horizonDays
    return result


def _stubRecommendTransfers(*args, **kwargs) -> list[dict]:
    return []


try:
    import engine as _engine
    _forecastDemand = _engine.forecastDemand
    _recommendTransfers = _engine.recommendTransfers
except Exception:
    _forecastDemand = _stubForecast
    _recommendTransfers = _stubRecommendTransfers


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parseUtc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _isoUtc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _buildDemandIndex(demand: list[dict]) -> dict:
    """demand[date][hospitalId][bloodGroup] = units"""
    idx: dict = {}
    for rec in demand:
        idx.setdefault(rec["date"], {}).setdefault(rec["hospitalId"], {})[rec["bloodGroup"]] = rec["units"]
    return idx


def _buildDeliveryIndex(deliveries: list[dict]) -> dict:
    """deliveries[date][hospitalId] = [unit, ...]"""
    idx: dict = {}
    for unit in deliveries:
        if "deliveredAt" in unit:
            dateStr = unit["deliveredAt"][:10]
        else:
            # Fallback for units from external sources without deliveredAt:
            # clamp collectedAt to simStart as best-effort delivery date.
            dt = _parseUtc(unit["collectedAt"])
            dateStr = max(dt.date(), _SIM_START.date()).strftime("%Y-%m-%d")
        idx.setdefault(dateStr, {}).setdefault(unit["hospitalId"], []).append(dict(unit))
    return idx


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def runSimulation(scenario: dict, policyName: str, seed: int) -> dict:
    """
    Simulate platelet exchange over the scenario's time horizon.
    policyName: "noSharing" | "exchange"
    Returns a SimResult (CONTRACT §5).
    """
    if policyName not in ("noSharing", "exchange"):
        raise ValueError(f"Unknown policy: {policyName}")

    deliveries: list[dict] = scenario["deliveries"]
    demand: list[dict] = scenario["demand"]

    # Infer simDays from deliveredAt dates (added by generate.py)
    allDates = set()
    for unit in deliveries:
        if "deliveredAt" in unit:
            allDates.add(unit["deliveredAt"][:10])
    if allDates:
        from datetime import date
        maxDate = max(date.fromisoformat(d) for d in allDates)
        simDays = (maxDate - _SIM_START.date()).days + 1
    else:
        simDays = 90

    travelTimes = _loadTravelTimes()
    compatibility = _loadCompatibility()

    demandIdx = _buildDemandIndex(demand)
    deliveryIdx = _buildDeliveryIndex(deliveries)

    # inventory[hospitalId] = list of unit dicts (mutable copies)
    inventory: dict[str, list[dict]] = {}

    # in-transit: list of {"arrivalTime": datetime, "unit": dict}
    inTransit: list[dict] = []

    # accumulators
    totalDelivered = 0
    totalTransfused = 0
    totalWasted = 0
    totalShortages = 0
    totalTransfers = 0

    daily: list[dict] = []

    # history of demand records seen so far (for engine forecasts)
    demandHistory: list[dict] = []

    for dayIndex in range(simDays):
        dayStart = _SIM_START + timedelta(days=dayIndex)
        dateStr = dayStart.strftime("%Y-%m-%d")

        dayWasted = 0
        dayShortages = 0
        dayTransfers = 0

        for stepIndex in range(_STEPS_PER_DAY):
            now = dayStart + timedelta(hours=stepIndex * _STEP_HOURS)
            nowIso = _isoUtc(now)

            # 1. Deliver units (only at midnight, step 0)
            if stepIndex == 0:
                for hospitalId, units in deliveryIdx.get(dateStr, {}).items():
                    inventory.setdefault(hospitalId, [])
                    for unit in units:
                        u = dict(unit)
                        u["status"] = "available"
                        inventory[hospitalId].append(u)
                        totalDelivered += 1

            # 2. Arrive in-transit units
            arrived = [t for t in inTransit if t["arrivalTime"] <= now]
            for arrival in arrived:
                unit = arrival["unit"]
                unit["status"] = "available"
                inventory.setdefault(unit["hospitalId"], []).append(unit)
            inTransit = [t for t in inTransit if t["arrivalTime"] > now]

            # 3. Expire units
            for hospitalId, units in inventory.items():
                for unit in units:
                    if unit["status"] == "available":
                        expiresAt = _parseUtc(unit["expiresAt"])
                        if now >= expiresAt:
                            unit["status"] = "expired"
                            dayWasted += 1
                            totalWasted += 1

            # 4. Exchange only: run engine every 6h
            if policyName == "exchange":
                availableStock = [
                    u for units in inventory.values()
                    for u in units if u["status"] == "available"
                ]
                forecast = _forecastDemand(demandHistory, horizonDays=3)
                transfers = _recommendTransfers(
                    availableStock, forecast, travelTimes, compatibility, nowIso
                )
                for transfer in transfers:
                    unitId = transfer["unitId"]
                    fromHId = transfer["fromHospitalId"]
                    toHId = transfer["toHospitalId"]
                    travelMin = transfer.get("travelMinutes", 0)

                    # Find and mark the unit
                    fromInv = inventory.get(fromHId, [])
                    for unit in fromInv:
                        if unit["unitId"] == unitId and unit["status"] == "available":
                            unit["status"] = "inTransit"
                            transitUnit = dict(unit)
                            transitUnit["hospitalId"] = toHId
                            arrivalTime = now + timedelta(minutes=travelMin)
                            inTransit.append({"arrivalTime": arrivalTime, "unit": transitUnit})
                            dayTransfers += 1
                            totalTransfers += 1
                            break

        # 5. Issue FIFO demand at end of day
        dayDemand = demandIdx.get(dateStr, {})
        for hospitalId, bgDemand in dayDemand.items():
            inv = inventory.get(hospitalId, [])
            # Collect demand records for engine history
            for bloodGroup, unitsNeeded in bgDemand.items():
                demandHistory.append({
                    "date": dateStr,
                    "hospitalId": hospitalId,
                    "bloodGroup": bloodGroup,
                    "units": unitsNeeded,
                })

                # FIFO: sort available units by collectedAt (oldest first)
                available = sorted(
                    [u for u in inv if u["status"] == "available" and u["bloodGroup"] == bloodGroup],
                    key=lambda u: u["collectedAt"],
                )
                toTransfuse = min(unitsNeeded, len(available))
                shortage = unitsNeeded - toTransfuse

                for unit in available[:toTransfuse]:
                    unit["status"] = "transfused"
                    totalTransfused += 1

                if shortage > 0:
                    dayShortages += shortage
                    totalShortages += shortage

        daily.append({
            "date": dateStr,
            "wasted": dayWasted,
            "shortages": dayShortages,
            "transfers": dayTransfers,
        })
        totalWasted += 0  # already accumulated inside step loop

    wasteRate = round(totalWasted / totalDelivered, 4) if totalDelivered > 0 else 0.0

    return {
        "policy": policyName,
        "days": simDays,
        "unitsDelivered": totalDelivered,
        "unitsTransfused": totalTransfused,
        "unitsWasted": totalWasted,
        "wasteRate": wasteRate,
        "shortageEvents": totalShortages,
        "transfers": totalTransfers,
        "daily": daily,
    }
