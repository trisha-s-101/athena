"""Backtest: forecast error of the Bayesian forecaster against the previous weekday average.

Rolls a forecast origin through simulated scenarios built by sim.generate from the same
shared/*.json as sim.run. At each origin both forecasters see only earlier demand, predict the
next --horizon days, and are scored against the demand that actually happened. Pairs missing
from a forecast count as a forecast of 0.

Two history settings mirror how the engine is called:
- api: the last 28 days, with yesterday padded with zero records (api/engineInputs.py)
- sim: all demand so far (sim/simulate.py)

Two scenarios: the stationary one, and a 3x demand surge at the first hospital for 7 days from
a third of the way in (as in sim/multirun.py's stress scenario).

Run from the repo root:
    python -m bench.forecastBacktest [--seeds 1,2,...,10] [--days 90] [--horizon 3] [--output path]
"""

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

from engine.forecast import forecastDemand
from engine.weekdayForecast import forecastDemandWeekdayAverage
from sim.generate import generateScenario

repoRoot = Path(__file__).resolve().parent.parent
forecasters = {"weekdayAverage": forecastDemandWeekdayAverage, "bayesian": forecastDemand}
apiHistoryDays = 28    # api/engineInputs.py historyDays
minHistoryDays = 7     # First origin: a week of history
surgeFactor, surgeDays = 3.0, 7
rareShareCutoff = 0.05  # Blood groups under 5% of the mix count as rare


def loadSharedInputs() -> tuple[dict, list[dict]]:
    assumptions = json.loads((repoRoot / "shared" / "assumptions.json").read_text())
    hospitals = json.loads((repoRoot / "shared" / "hospitals.json").read_text())
    return assumptions, hospitals


def buildScenarios(assumptions: dict, hospitals: list[dict], seed: int, days: int) -> dict:
    """{"stationary": demand records, "demandSurge": demand records} for one seed."""
    stationary = generateScenario({**assumptions, "simDays": days}, hospitals, seed)["demand"]
    surgeHospitalId = hospitals[0]["hospitalId"]
    startDate = min(date.fromisoformat(record["date"]) for record in stationary)
    surgeStart = startDate + timedelta(days=days // 3)
    surgeEnd = surgeStart + timedelta(days=surgeDays)
    surged = []
    for record in stationary:
        recordDate = date.fromisoformat(record["date"])
        if record["hospitalId"] == surgeHospitalId and surgeStart <= recordDate < surgeEnd:
            record = {**record, "units": max(1, round(record["units"] * surgeFactor))}
        surged.append(record)
    return {"stationary": stationary, "demandSurge": surged}


def demandByDay(records: list[dict]) -> tuple[list[date], dict]:
    """All dates in the scenario, and date -> {(hospitalId, bloodGroup): units}."""
    byDay = {}
    for record in records:
        day = byDay.setdefault(date.fromisoformat(record["date"]), {})
        pair = (record["hospitalId"], record["bloodGroup"])
        day[pair] = day.get(pair, 0) + record["units"]
    firstDate, lastDate = min(byDay), max(byDay)
    return [firstDate + timedelta(days=index) for index in range((lastDate - firstDate).days + 1)], byDay


def historyFor(setting: str, dates: list[date], byDay: dict, originIndex: int) -> list[dict]:
    startIndex = max(0, originIndex - apiHistoryDays) if setting == "api" else 0
    history = [{"date": day.isoformat(), "hospitalId": hospitalId, "bloodGroup": bloodGroup, "units": units}
               for day in dates[startIndex:originIndex]
               for (hospitalId, bloodGroup), units in sorted(byDay.get(day, {}).items())]
    if setting == "api":
        # api/engineInputs.py pads yesterday with zeros so the forecaster's "today" is right.
        yesterday = dates[originIndex - 1]
        seenYesterday = set(byDay.get(yesterday, {}))
        for hospitalId, bloodGroup in sorted({(r["hospitalId"], r["bloodGroup"]) for r in history}):
            if (hospitalId, bloodGroup) not in seenYesterday:
                history.append({"date": yesterday.isoformat(), "hospitalId": hospitalId,
                                "bloodGroup": bloodGroup, "units": 0})
    return history


def emptyTally() -> dict:
    return {"cells": 0, "absoluteError": 0.0, "squaredError": 0.0, "error": 0.0}


def addError(tally: dict, error: float) -> None:
    tally["cells"] += 1
    tally["absoluteError"] += abs(error)
    tally["squaredError"] += error * error
    tally["error"] += error


def summarize(tally: dict) -> dict:
    cells = tally["cells"]
    if not cells:
        return {"cells": 0, "mae": 0.0, "rmse": 0.0, "bias": 0.0}
    return {"cells": cells, "mae": round(tally["absoluteError"] / cells, 4),
            "rmse": round(math.sqrt(tally["squaredError"] / cells), 4), "bias": round(tally["error"] / cells, 4)}


def backtestScenario(records: list[dict], setting: str, horizon: int, rareGroups: set) -> dict:
    """Tallies per forecaster and segment: all, first4Weeks/later origins, rare/common blood groups."""
    dates, byDay = demandByDay(records)
    tallies = {name: {segment: emptyTally() for segment in ("all", "first4Weeks", "later", "rare", "common")}
               for name in forecasters}
    for originIndex in range(minHistoryDays, len(dates) - horizon + 1):
        history = historyFor(setting, dates, byDay, originIndex)
        period = "first4Weeks" if originIndex < 28 else "later"
        for name, forecaster in forecasters.items():
            forecast = forecaster(history, horizon)
            for dayIndex in range(horizon):
                actual = byDay.get(dates[originIndex + dayIndex], {})
                predictedPairs = {(hospitalId, bloodGroup) for hospitalId, groups in forecast.items()
                                  for bloodGroup in groups}
                for pair in sorted(predictedPairs | set(actual)):
                    hospitalId, bloodGroup = pair
                    predicted = forecast.get(hospitalId, {}).get(bloodGroup, [0.0] * horizon)[dayIndex]
                    error = predicted - actual.get(pair, 0)
                    for segment in ("all", period, "rare" if bloodGroup in rareGroups else "common"):
                        addError(tallies[name][segment], error)
    return tallies


def mergeTallies(target: dict, source: dict) -> None:
    for name, segments in source.items():
        for segment, tally in segments.items():
            merged = target.setdefault(name, {}).setdefault(segment, emptyTally())
            for key in merged:
                merged[key] += tally[key]


def runBacktest(seeds: list[int], days: int, horizon: int) -> dict:
    assumptions, hospitals = loadSharedInputs()
    rareGroups = {group for group, share in assumptions["bloodGroupMix"].items() if share < rareShareCutoff}
    totals = {}
    for seed in seeds:
        for scenarioName, records in buildScenarios(assumptions, hospitals, seed, days).items():
            for setting in ("api", "sim"):
                mergeTallies(totals.setdefault(f"{setting}/{scenarioName}", {}),
                             backtestScenario(records, setting, horizon, rareGroups))
    results = {}
    for combination, byForecaster in totals.items():
        results[combination] = {name: {segment: summarize(tally) for segment, tally in segments.items()}
                                for name, segments in byForecaster.items()}
    return {"seeds": seeds, "days": days, "horizon": horizon, "rareGroups": sorted(rareGroups), "results": results}


def maeChange(results: dict, combination: str, segment: str) -> float:
    """Percentage change in MAE from the weekday average to the Bayesian forecaster (negative is better)."""
    baseline = results[combination]["weekdayAverage"][segment]["mae"]
    bayesian = results[combination]["bayesian"][segment]["mae"]
    return round(100 * (bayesian - baseline) / baseline, 1) if baseline else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the demand forecasters")
    parser.add_argument("--seeds", default="1,2,3,4,5,6,7,8,9,10", help="Comma-separated scenario seeds")
    parser.add_argument("--days", type=int, default=90, help="Days per scenario")
    parser.add_argument("--horizon", type=int, default=3, help="Days forecast at each origin")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON file for the full results")
    args = parser.parse_args(argv)
    seeds = [int(seed) for seed in args.seeds.split(",") if seed.strip()]

    report = runBacktest(seeds, args.days, args.horizon)
    print(f"[bench.forecastBacktest] seeds {seeds}, {args.days} days, {args.horizon}-day horizon. "
          "MAE in units per hospital/group/day (lower is better).")
    for combination, byForecaster in report["results"].items():
        print(f"\n  {combination}")
        for segment in ("all", "first4Weeks", "later", "rare", "common"):
            baseline, bayesian = byForecaster["weekdayAverage"][segment], byForecaster["bayesian"][segment]
            print(f"    {segment:<12} weekday average {baseline['mae']:.4f}   bayesian {bayesian['mae']:.4f}   "
                  f"change {maeChange(report['results'], combination, segment):+.1f}%   "
                  f"(rmse {baseline['rmse']:.4f} -> {bayesian['rmse']:.4f})")
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\n[bench.forecastBacktest] Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
