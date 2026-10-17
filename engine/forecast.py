"""Demand forecasting without external state."""

from datetime import date, timedelta
from math import isfinite


def forecastDemand(history: list[dict], horizonDays: int = 3) -> dict:
    """Average demand by weekday; today is the day after the latest history date.

    The history's first through last dates form a complete observation window.
    Missing records in that window count as zero; duplicate daily records sum.
    Weekdays absent from the window fall back to the pair's overall daily mean.
    Only hospital/group pairs present in history appear in the result.
    """
    if isinstance(horizonDays, bool) or not isinstance(horizonDays, int) or horizonDays < 0:
        raise ValueError("horizonDays must be a nonnegative integer")
    if not history:
        return {}

    dailyTotals = {}
    observedDates = []
    for record in history:
        recordDate = date.fromisoformat(record["date"])
        units = record["units"]
        if not isfinite(units) or units < 0:
            raise ValueError("Demand units must be finite and nonnegative")
        observedDates.append(recordDate)
        pairKey = (record["hospitalId"], record["bloodGroup"])
        pairTotals = dailyTotals.setdefault(pairKey, {})
        pairTotals[recordDate] = pairTotals.get(recordDate, 0) + units

    firstDate, lastDate = min(observedDates), max(observedDates)
    dayCount = (lastDate - firstDate).days + 1
    weekdayCounts = [0] * 7
    for dayIndex in range(dayCount):
        weekdayCounts[(firstDate + timedelta(days=dayIndex)).weekday()] += 1

    forecast = {}
    for (hospitalId, bloodGroup), pairTotals in sorted(dailyTotals.items()):
        weekdayTotals = [0.0] * 7
        for recordDate, units in pairTotals.items():
            weekdayTotals[recordDate.weekday()] += units
        fallbackMean = sum(pairTotals.values()) / dayCount
        predictions = []
        for dayIndex in range(horizonDays):
            weekday = (lastDate + timedelta(days=dayIndex + 1)).weekday()
            predictions.append(weekdayTotals[weekday] / weekdayCounts[weekday]
                               if weekdayCounts[weekday] else fallbackMean)
        forecast.setdefault(hospitalId, {})[bloodGroup] = predictions
    return forecast
