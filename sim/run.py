"""
sim/run.py  --  CLI entry point for the offline simulation (CONTRACT §7).

Usage:
    python -m sim.run [--seed 42] [--seeds 1,2,3,...,10] [--days 90]

Loads shared/assumptions.json and shared/hospitals.json, runs 10 seeds plus
stress scenarios, and writes results/comparison.json in the +16h shape.
Falls back to built-in defaults if shared files are not yet committed.
"""

import argparse
import json
import pathlib
from datetime import datetime, timezone

from sim.generate import generateScenario
from sim.simulate import runSimulation
from sim.multirun import runMultiSeed, runStressScenarios

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

_DEFAULT_SEEDS = list(range(1, 11))  # seeds 1–10


def _loadJson(relPath: str, default):
    p = _REPO_ROOT / relPath
    if p.exists():
        return json.loads(p.read_text())
    print(f"[sim.run] {relPath} not found, using defaults")
    return default


def run(seeds: list[int]) -> dict:
    assumptions = _loadJson("shared/assumptions.json", _DEFAULT_ASSUMPTIONS)
    hospitals = _loadJson("shared/hospitals.json", _DEFAULT_HOSPITALS)

    print(f"[sim.run] Running {len(seeds)} seeds: {seeds}")
    multiResult = runMultiSeed(assumptions, hospitals, seeds)

    print("[sim.run] Running stress scenarios (seed=42)...")
    stressResult = runStressScenarios(assumptions, hospitals, seed=42)

    # Strip internal _rawResults before writing (too large for comparison.json)
    statistics = multiResult["statistics"]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "seeds": multiResult["seeds"],
        "statistics": statistics,
        "stressScenarios": stressResult,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run platelet exchange simulation")
    parser.add_argument("--seed", type=int, default=None,
                        help="Single seed (overrides --seeds)")
    parser.add_argument("--seeds", type=str, default=None,
                        help="Comma-separated list of seeds (default: 1-10)")
    parser.add_argument("--days", type=int, default=None,
                        help="Override simDays from assumptions.json")
    args = parser.parse_args()

    if args.days is not None:
        _DEFAULT_ASSUMPTIONS["simDays"] = args.days

    if args.seed is not None:
        seeds = [args.seed]
    elif args.seeds is not None:
        seeds = [int(s.strip()) for s in args.seeds.split(",")]
    else:
        seeds = _DEFAULT_SEEDS

    result = run(seeds)

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(result, indent=2))
    print(f"[sim.run] Wrote {_RESULTS_PATH}")

    ns = result["statistics"]["noSharing"]
    ex = result["statistics"]["exchange"]
    print(f"[sim.run] noSharing wasteRate: mean={ns['wasteRate']['mean']:.4f}  stdDev={ns['wasteRate']['stdDev']:.4f}")
    print(f"[sim.run] exchange  wasteRate: mean={ex['wasteRate']['mean']:.4f}  stdDev={ex['wasteRate']['stdDev']:.4f}")


if __name__ == "__main__":
    main()
