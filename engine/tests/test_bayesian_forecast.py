"""Tests for the Bayesian forecaster's pooling, recency weighting and robustness (engine/forecast.py)."""

import copy
import math
import random
import unittest
from datetime import date, timedelta

from engine import forecastDemand
from engine.weekdayForecast import forecastDemandWeekdayAverage

# 28 days from Monday 2025-12-08 end on Sunday 2026-01-04, so forecast day 0 is a Monday.
historyStart = date(2025, 12, 8)


def record(dayIndex, units, hospitalId="H01", bloodGroup="A+"):
    return {"date": (historyStart + timedelta(days=dayIndex)).isoformat(), "hospitalId": hospitalId,
            "bloodGroup": bloodGroup, "units": units}


def weeklyPattern(weekdayUnits, weekendUnits, hospitalId, bloodGroup, days=28):
    """Same demand every week: weekdayUnits Monday to Friday, weekendUnits at the weekend."""
    return [record(dayIndex, weekendUnits if dayIndex % 7 >= 5 else weekdayUnits, hospitalId, bloodGroup)
            for dayIndex in range(days)]


def randomHistory(seed, days=60):
    """Poisson-like demand for 3 hospitals x 4 groups, with some days missing, as plain records."""
    rng = random.Random(seed)
    history = []
    for dayIndex in range(days):
        for hospitalId, scale in [("H01", 6.0), ("H02", 3.0), ("H03", 1.0)]:
            for bloodGroup, share in [("O+", 0.4), ("A+", 0.35), ("O-", 0.15), ("AB-", 0.1)]:
                mean = scale * share * (0.6 if dayIndex % 7 >= 5 else 1.0)
                units, product = 0, rng.random()
                while product > math.exp(-mean):
                    units += 1
                    product *= rng.random()
                if units:
                    history.append(record(dayIndex, units, hospitalId, bloodGroup))
    return history


class SparseDataTests(unittest.TestCase):
    def testSparsePairBorrowsTheRegionsWeeklyShape(self):
        # Busy pairs are quieter at weekends; H01 AB- used a single unit, on the first Monday.
        history = (weeklyPattern(4, 2, "H01", "A+") + weeklyPattern(8, 4, "H02", "O+")
                   + [record(0, 1, "H01", "AB-")])
        oldRare = forecastDemandWeekdayAverage(history, 7)["H01"]["AB-"]
        newRare = forecastDemand(history, 7)["H01"]["AB-"]
        # The weekday average only ever expects AB- on Mondays.
        self.assertEqual(oldRare, [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        # Pooling spreads it over the week, following the region's quieter weekends.
        self.assertTrue(all(value > 0 for value in newRare))
        self.assertLess(max(newRare[5:]), min(newRare[:5]))
        # The total expected over the week stays close to what the pair actually used (1 in 4 weeks).
        self.assertAlmostEqual(sum(newRare), 0.25, delta=0.05)

    def testRealDifferencesAreNotPooledAway(self):
        # Mirror-image hospitals: the region mix is 50/50, but each hospital clearly isn't.
        history = (weeklyPattern(1, 1, "H01", "A+") + weeklyPattern(9, 9, "H01", "O+")
                   + weeklyPattern(9, 9, "H02", "A+") + weeklyPattern(1, 1, "H02", "O+"))
        result = forecastDemand(history, 3)
        # The learned prior is weak here, so each pair keeps close to its own steady rate.
        self.assertAlmostEqual(result["H02"]["A+"][0], 9, delta=0.25)
        self.assertAlmostEqual(result["H02"]["O+"][0], 1, delta=0.25)

    def testAllZeroHistoryForecastsZero(self):
        history = [record(dayIndex, 0, hospitalId) for dayIndex in range(14) for hospitalId in ("H01", "H02")]
        self.assertEqual(forecastDemand(history, 2), {"H01": {"A+": [0.0, 0.0]}, "H02": {"A+": [0.0, 0.0]}})


class RecencyTests(unittest.TestCase):
    def testOlderHistoryFadesButStillCounts(self):
        # Twelve weeks: 6 a day for eight weeks, then 2 a day for the last four.
        history = [record(dayIndex, 6 if dayIndex < 56 else 2) for dayIndex in range(84)]
        flatAverage = forecastDemandWeekdayAverage(history, 1)["H01"]["A+"][0]
        recencyWeighted = forecastDemand(history, 1)["H01"]["A+"][0]
        self.assertAlmostEqual(flatAverage, 14 / 3)
        self.assertLess(recencyWeighted, flatAverage - 0.2)
        self.assertGreater(recencyWeighted, 2)

    def testRecentFourWeeksCountEqually(self):
        # Within the full-weight window, the order of days doesn't matter.
        rising = [record(dayIndex, dayIndex // 7) for dayIndex in range(28)]
        falling = [record(dayIndex, 3 - dayIndex // 7) for dayIndex in range(28)]
        self.assertEqual(forecastDemand(rising, 7), forecastDemand(falling, 7))


class DeterminismAndPurityTests(unittest.TestCase):
    def testSameResultEveryTimeAndInAnyOrder(self):
        history = randomHistory(7)
        expected = forecastDemand(history, 3)
        self.assertEqual(forecastDemand(history, 3), expected)
        for shuffleSeed in range(5):
            shuffled = list(history)
            random.Random(shuffleSeed).shuffle(shuffled)
            self.assertEqual(forecastDemand(shuffled, 3), expected)

    def testInputsAreUnchanged(self):
        history = randomHistory(11)
        original = copy.deepcopy(history)
        forecastDemand(history, 3)
        self.assertEqual(history, original)

    def testSamePairsAndShapeAsBeforeWithSaneValues(self):
        history = randomHistory(3)
        old, new = forecastDemandWeekdayAverage(history, 4), forecastDemand(history, 4)
        self.assertEqual({(h, g) for h in old for g in old[h]}, {(h, g) for h in new for g in new[h]})
        for groups in new.values():
            for values in groups.values():
                self.assertEqual(len(values), 4)
                self.assertTrue(all(math.isfinite(value) and value >= 0 for value in values))


class BaselineModuleTests(unittest.TestCase):
    def testWeekdayAverageStillMatchesThePreviousForecaster(self):
        # bench/forecastBacktest.py compares against this, so it must keep the old behavior.
        history = [{"date": "2025-12-22", "hospitalId": "H01", "bloodGroup": "A+", "units": 2},
                   {"date": "2025-12-29", "hospitalId": "H01", "bloodGroup": "A+", "units": 6},
                   {"date": "2026-01-04", "hospitalId": "H01", "bloodGroup": "A+", "units": 0}]
        self.assertEqual(forecastDemandWeekdayAverage(history), {"H01": {"A+": [4.0, 0.0, 0.0]}})


if __name__ == "__main__":
    unittest.main()
