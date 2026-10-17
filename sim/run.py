"""
sim/run.py  --  CLI entry point for the offline simulation.

Usage:
    python -m sim.run --days 90 --seed 42

Writes results/comparison.json with the shape defined in CONTRACT section 7.
At the +1h milestone the numbers are deterministic fakes; real logic replaces
this in sim/simulate.py at +4h without changing the output shape.
"""

import argparse
import json
import pathlib
import random
from datetime import datetime, timedelta, timezone


_SIM_START = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
_RESULTS_PATH = pathlib.Path("results/comparison.json")


def _fakeSimResult(policy: str, days: int, rng: random.Random) -> dict:
    """Return a plausible but fake SimResult for the given policy."""
    hospitalsCount = 10

    # Deliveries: ~8 units/day/hospital on average
    delivered = days * hospitalsCount * rng.randint(7, 9)

    # Exchange wastes less than noSharing
    if policy == "exchange":
        wasteRate = round(rng.uniform(0.020, 0.030), 4)
        shortageEvents = rng.randint(1, 5)
        transfers = rng.randint(600, 900)
    else:
        wasteRate = round(rng.uniform(0.040, 0.055), 4)
        shortageEvents = rng.randint(8, 20)
        transfers = 0

    wasted = round(delivered * wasteRate)
    transfused = delivered - wasted - rng.randint(0, min(50, delivered - wasted))

    dailyList = []
    for i in range(days):
        date = (_SIM_START + timedelta(days=i)).strftime("%Y-%m-%d")
        dayWasted = rng.randint(0, max(1, wasted // days * 2))
        dayShortages = rng.randint(0, max(0, shortageEvents // days + 1))
        dayTransfers = rng.randint(0, max(0, transfers // days * 2)) if policy == "exchange" else 0
        dailyList.append({
            "date": date,
            "wasted": dayWasted,
            "shortages": dayShortages,
            "transfers": dayTransfers,
        })

    return {
        "policy": policy,
        "days": days,
        "unitsDelivered": delivered,
        "unitsTransfused": transfused,
        "unitsWasted": wasted,
        "wasteRate": wasteRate,
        "shortageEvents": shortageEvents,
        "transfers": transfers,
        "daily": dailyList,
    }


def run(days: int, seed: int) -> dict:
    rng = random.Random(seed)
    noSharing = _fakeSimResult("noSharing", days, rng)
    exchange = _fakeSimResult("exchange", days, rng)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "noSharing": noSharing,
        "exchange": exchange,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run platelet exchange simulation")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    result = run(args.days, args.seed)

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(result, indent=2))
    print(f"Wrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
