"""Demand forecasting without external state: a partially pooled Bayesian (Poisson–Gamma) model.

Each hospital/blood-group pair's daily demand is treated as Poisson, with a Gamma prior on its
rate (the conjugate Poisson–Gamma model). Rates are estimated in two pooled steps, so pairs with
thin history borrow strength from the rest of the region:

1. Pair rate. The prior mean is the hospital's total daily demand split by the region's
   blood-group mix, over the groups seen at that hospital, so a hospital's priors add up to its
   own total. The pair's own average is shrunk toward it.
2. Weekday rate. The prior mean is that pair rate times the region's weekday profile (for
   example, quieter weekends). Each weekday's own average is shrunk toward it.

How hard each step pulls is learned from the history by the method of moments: the more the
pairs disagree with the pooled pattern beyond Poisson noise, the weaker the pull. When the
pooled pattern matches a pair's own history, as it does for a hospital with a single blood
group, nothing changes. Days in the most recent four weeks count fully; older days fade with
an eight-week half-life.
"""

from datetime import date, timedelta
from math import isfinite

# Tuned on backtest seeds 101-105 (bench/forecastBacktest.py); seeds 1-10 are held out for reporting.
fullWeightDays = 28  # The most recent four weeks of history count fully...
halfLifeDays = 56    # ...and each older day loses half its weight every eight weeks.
minPriorDays = 0.5   # Bounds on the learned prior strength, measured in days of data.
maxPriorDays = 1000.0
outputDecimals = 9   # Strips floating-point noise; a billionth of a unit never matters.


def recencyWeight(ageDays: int) -> float:
    """Weight of a day that is ageDays before the latest history date."""
    if ageDays < fullWeightDays:
        return 1.0
    return 0.5 ** ((ageDays - fullWeightDays + 1) / halfLifeDays)


def learnedPriorStrength(observations: list[tuple[float, float, float]]) -> float:
    """Method-of-moments estimate of the Gamma prior's strength, in days of data.

    Each observation is (own average, prior mean, effective days behind the own average). Under
    the model an own average differs from its prior mean m by the prior's spread (variance
    m / strength) plus Poisson noise (variance about m / effective days). Deviation beyond the
    noise therefore measures how much pairs really differ from the pooled pattern.
    """
    excess = sum((own - prior) ** 2 - prior / days for own, prior, days in observations)
    scale = sum(prior for _, prior, _ in observations)
    if scale <= 0 or excess <= 0:
        return maxPriorDays
    return min(maxPriorDays, max(minPriorDays, scale / excess))


def shrink(own: float, prior: float, strength: float, effectiveDays: float) -> float:
    """Posterior mean of a Poisson rate with a Gamma prior: own data weighted against the prior."""
    return own + (prior - own) * (strength / (strength + effectiveDays))


def forecastDemand(history: list[dict], horizonDays: int = 3) -> dict:
    """Expected units per day for each hospital/group pair; today is the day after the latest history date.

    The history's first through last dates form a complete observation window: missing records
    in it count as zero, and duplicate daily records sum. Weekdays absent from the window use the
    pair's overall rate. Only pairs present in history appear in the result. The input is never
    modified, and the result doesn't depend on the order of the records.
    """
    if isinstance(horizonDays, bool) or not isinstance(horizonDays, int) or horizonDays < 0:
        raise ValueError("horizonDays must be a nonnegative integer")
    if not history:
        return {}

    records = []
    for record in history:
        units = record["units"]
        if not isfinite(units) or units < 0:
            raise ValueError("Demand units must be finite and nonnegative")
        records.append((date.fromisoformat(record["date"]), record["hospitalId"],
                        record["bloodGroup"], units))
    # A fixed order makes every floating-point sum, and so the result, independent of input order.
    records.sort()
    firstDate, lastDate = records[0][0], records[-1][0]
    dayCount = (lastDate - firstDate).days + 1

    dayWeights = [recencyWeight(dayCount - 1 - index) for index in range(dayCount)]
    exposure = sum(dayWeights)
    effectiveDays = exposure ** 2 / sum(weight ** 2 for weight in dayWeights)
    weekdayExposure, weekdaySquares = [0.0] * 7, [0.0] * 7
    for index, weight in enumerate(dayWeights):
        weekday = (firstDate + timedelta(days=index)).weekday()
        weekdayExposure[weekday] += weight
        weekdaySquares[weekday] += weight ** 2

    pairTotals, pairWeekdayTotals = {}, {}
    for recordDate, hospitalId, bloodGroup, units in records:
        weightedUnits = dayWeights[(recordDate - firstDate).days] * units
        pair = (hospitalId, bloodGroup)
        pairTotals[pair] = pairTotals.get(pair, 0.0) + weightedUnits
        pairWeekdayTotals.setdefault(pair, [0.0] * 7)[recordDate.weekday()] += weightedUnits

    pairs = sorted(pairTotals)
    hospitalTotals, groupTotals, regionWeekday = {}, {}, [0.0] * 7
    for hospitalId, bloodGroup in pairs:
        total = pairTotals[(hospitalId, bloodGroup)]
        hospitalTotals[hospitalId] = hospitalTotals.get(hospitalId, 0.0) + total
        groupTotals[bloodGroup] = groupTotals.get(bloodGroup, 0.0) + total
        for weekday in range(7):
            regionWeekday[weekday] += pairWeekdayTotals[(hospitalId, bloodGroup)][weekday]
    regionTotal = sum(hospitalTotals[hospitalId] for hospitalId in sorted(hospitalTotals))
    shareBase = {}
    for hospitalId, bloodGroup in pairs:
        shareBase[hospitalId] = shareBase.get(hospitalId, 0.0) + groupTotals[bloodGroup]

    # Step 1: pair rates, shrunk toward the hospital's total split by the region's group mix.
    ownRates, priorRates = {}, {}
    for pair in pairs:
        hospitalId, bloodGroup = pair
        ownRates[pair] = pairTotals[pair] / exposure
        priorRates[pair] = (hospitalTotals[hospitalId] * groupTotals[bloodGroup]
                            / (exposure * shareBase[hospitalId])
                            if shareBase[hospitalId] > 0 else ownRates[pair])
    pairStrength = learnedPriorStrength(
        [(ownRates[pair], priorRates[pair], effectiveDays) for pair in pairs])
    pairRates = {pair: shrink(ownRates[pair], priorRates[pair], pairStrength, effectiveDays)
                 for pair in pairs}

    # Step 2: weekday rates, shrunk toward the pair rate times the region's weekday profile.
    profile = [(regionWeekday[weekday] * exposure) / (weekdayExposure[weekday] * regionTotal)
               if weekdayExposure[weekday] > 0 and regionTotal > 0 else 1.0
               for weekday in range(7)]
    observations = []
    for pair in pairs:
        for weekday in range(7):
            if weekdayExposure[weekday] > 0:
                observations.append((pairWeekdayTotals[pair][weekday] / weekdayExposure[weekday],
                                     pairRates[pair] * profile[weekday],
                                     weekdayExposure[weekday] ** 2 / weekdaySquares[weekday]))
    weekdayStrength = learnedPriorStrength(observations)

    forecast = {}
    for pair in pairs:
        hospitalId, bloodGroup = pair
        weekdayRates = []
        for weekday in range(7):
            prior = pairRates[pair] * profile[weekday]
            if weekdayExposure[weekday] > 0:
                own = pairWeekdayTotals[pair][weekday] / weekdayExposure[weekday]
                days = weekdayExposure[weekday] ** 2 / weekdaySquares[weekday]
                weekdayRates.append(shrink(own, prior, weekdayStrength, days))
            else:
                weekdayRates.append(prior)
        forecast.setdefault(hospitalId, {})[bloodGroup] = [
            round(weekdayRates[(lastDate + timedelta(days=dayIndex + 1)).weekday()], outputDecimals)
            for dayIndex in range(horizonDays)
        ]
    return forecast
