"""
sim/run.py  --  CLI entry point for the offline simulation (CONTRACT §7).

Usage:
    python -m sim.run --days 90 --seed 42

Loads shared/assumptions.json and shared/hospitals.json, generates a scenario,
runs both policies, and writes results/comparison.json.
Falls back to built-in defaults if the shared files are not yet committed.
"""

import argparse
import json
import pathlib
from datetime import datetime, timezone

from sim.generate import generateScenario
from sim.simulate import runSimulation

_REPO_ROOT = pathlib.Path(__file__).parents[1]
_RESULTS_PATH = _REPO_ROOT / "results" / "comparison.json"

_DEFAULT_ASSUMPTIONS = {
    "simDays": 90,
    "baselineWasteRate": 0.048,
    "dailyDemandMean": {"small": 1, "medium": 3, "large": 8},
    "weekendDemandFactor": 0.6,
    "bloodGroupMix": {
        "O+": 0.35, "A+": 0.30, "B+": 0.08, "AB+": 0.02,
        "O-": 0.13, "A-": 0.08, "B-": 0.02, "AB-": 0.01,
    },
    "remainingShelfLifeOnArrivalDays": {"min": 1, "max": 4},
    "targetStockDays": {"small": 2, "medium": 2, "large": 1.5},
    "maxTransferMinutes": 240,
    "minHoursLeftToTransfer": 12,
}

_DEFAULT_HOSPITALS = [
    {"hospitalId": f"H{i:02d}", "name": f"Hospital {i}",
     "lat": 53.46 + i * 0.01, "lng": -2.23, "sizeCategory": size, "hasHaematology": True}
    for i, size in enumerate(
        ["large", "large", "large", "medium", "medium",
         "medium", "small", "small", "small", "small"], start=1
    )
]


def _loadJson(relPath: str, default):
    p = _REPO_ROOT / relPath
    if p.exists():
        return json.loads(p.read_text())
    print(f"[sim.run] {relPath} not found, using defaults")
    return default


def run(seed: int) -> dict:
    assumptions = _loadJson("shared/assumptions.json", _DEFAULT_ASSUMPTIONS)
    hospitals = _loadJson("shared/hospitals.json", _DEFAULT_HOSPITALS)

    # Override simDays only if shared file is missing; respect the file's value.
    simDays = assumptions["simDays"]

    print(f"[sim.run] Generating scenario: {simDays} days, seed={seed}, {len(hospitals)} hospitals")
    scenario = generateScenario(assumptions, hospitals, seed)
    print(f"[sim.run] {len(scenario['deliveries'])} deliveries, {len(scenario['demand'])} demand records")

    print("[sim.run] Running noSharing policy...")
    noSharing = runSimulation(scenario, "noSharing", seed)
    print(f"[sim.run]   wasteRate={noSharing['wasteRate']:.4f}  shortages={noSharing['shortageEvents']}")

    print("[sim.run] Running exchange policy...")
    exchange = runSimulation(scenario, "exchange", seed)
    print(f"[sim.run]   wasteRate={exchange['wasteRate']:.4f}  shortages={exchange['shortageEvents']}  transfers={exchange['transfers']}")

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "noSharing": noSharing,
        "exchange": exchange,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run platelet exchange simulation")
    parser.add_argument("--days", type=int, default=None,
                        help="Override simDays from assumptions.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # --days override: patch the assumptions file's value if supplied
    if args.days is not None:
        _DEFAULT_ASSUMPTIONS["simDays"] = args.days

    result = run(args.seed)

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(result, indent=2))
    print(f"[sim.run] Wrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
