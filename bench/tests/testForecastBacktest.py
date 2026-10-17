"""Tests for bench/forecastBacktest.py. No database needed."""

import unittest
from datetime import date, timedelta

from bench.forecastBacktest import addError, emptyTally, historyFor, runBacktest, summarize


class TallyTest(unittest.TestCase):
    def testSummaryOfKnownErrors(self):
        tally = emptyTally()
        for error in (1.0, -3.0, 2.0):
            addError(tally, error)
        self.assertEqual(summarize(tally), {"cells": 3, "mae": 2.0, "rmse": round((14 / 3) ** 0.5, 4), "bias": 0.0})
        self.assertEqual(summarize(emptyTally())["cells"], 0)


class HistoryTest(unittest.TestCase):
    def testApiHistoryIsTheLast28DaysWithYesterdayPadded(self):
        dates = [date(2026, 1, 5) + timedelta(days=index) for index in range(40)]
        byDay = {day: {("H01", "A+"): 1} for day in dates[:35]}
        byDay[dates[30]][("H02", "O-")] = 2
        history = historyFor("api", dates, byDay, originIndex=36)
        self.assertEqual(min(record["date"] for record in history), dates[8].isoformat())
        # Day 35 (yesterday) had no demand, so both pairs seen in the window get a zero record.
        yesterday = [record for record in history if record["date"] == dates[35].isoformat()]
        self.assertEqual(sorted((r["hospitalId"], r["bloodGroup"], r["units"]) for r in yesterday),
                         [("H01", "A+", 0), ("H02", "O-", 0)])
        self.assertEqual(len(historyFor("sim", dates, byDay, originIndex=36)), 36)


class BacktestRunTest(unittest.TestCase):
    def testBothForecastersAreScoredInEverySetting(self):
        report = runBacktest(seeds=[1], days=21, horizon=2)
        self.assertEqual(set(report["results"]),
                         {"api/stationary", "sim/stationary", "api/demandSurge", "sim/demandSurge"})
        for byForecaster in report["results"].values():
            self.assertEqual(set(byForecaster), {"weekdayAverage", "bayesian"})
            for segments in byForecaster.values():
                self.assertGreater(segments["all"]["cells"], 0)
                self.assertGreaterEqual(segments["all"]["mae"], 0)


if __name__ == "__main__":
    unittest.main()
