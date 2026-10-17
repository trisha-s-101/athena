"""Tests for sim/multirun.py (+16h milestone)."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.generate import generateScenario
from sim.multirun import runMultiSeed, runStressScenarios

ASSUMPTIONS = {
    "simDays": 10,  # short for test speed
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

HOSPITALS = [
    {"hospitalId": f"H{i:02d}", "name": f"H{i}", "lat": 53.4 + i * 0.01,
     "lng": -2.2, "sizeCategory": size, "hasHaematology": True}
    for i, size in enumerate(
        ["large", "large", "large", "medium", "medium",
         "medium", "small", "small", "small", "small"], start=1
    )
]

SEEDS = list(range(1, 11))


# ---------------------------------------------------------------------------
# Multi-seed tests
# ---------------------------------------------------------------------------

def test_all_seeds_valid():
    """All 10 seeds produce valid SimResults for both policies."""
    result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
    assert result["seeds"] == SEEDS
    for policy in ("noSharing", "exchange"):
        rawResults = result["_rawResults"][policy]
        assert len(rawResults) == len(SEEDS)
        required = {"policy", "days", "unitsDelivered", "unitsTransfused",
                    "unitsWasted", "wasteRate", "shortageEvents", "transfers", "daily"}
        for sr in rawResults:
            assert required == set(sr.keys()), f"Missing keys in {policy} result"
            assert sr["unitsDelivered"] >= sr["unitsTransfused"] + sr["unitsWasted"]


def test_statistics_shape():
    result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
    stats = result["statistics"]
    statKeys = {"mean", "stdDev", "min", "max"}
    for policy in ("noSharing", "exchange"):
        ps = stats[policy]
        assert set(ps.keys()) >= {"wasteRate", "shortageEvents", "transfers"}
        assert set(ps["wasteRate"].keys()) == statKeys
        assert set(ps["shortageEvents"].keys()) == statKeys
        if policy == "exchange":
            assert set(ps["transfers"].keys()) == statKeys
        else:
            assert ps["transfers"] == 0


def test_statistics_mean_within_min_max():
    result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
    stats = result["statistics"]
    for policy in ("noSharing", "exchange"):
        for metric in ("wasteRate", "shortageEvents"):
            s = stats[policy][metric]
            assert s["min"] <= s["mean"] <= s["max"], \
                f"{policy}.{metric}: mean {s['mean']} not in [{s['min']}, {s['max']}]"


def test_no_sharing_zero_transfers_stat():
    result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
    assert result["statistics"]["noSharing"]["transfers"] == 0


def test_deterministic_across_runs():
    r1 = runMultiSeed(ASSUMPTIONS, HOSPITALS, [1, 2, 3])
    r2 = runMultiSeed(ASSUMPTIONS, HOSPITALS, [1, 2, 3])
    assert r1["statistics"]["noSharing"]["wasteRate"] == r2["statistics"]["noSharing"]["wasteRate"]


# ---------------------------------------------------------------------------
# Stress scenario tests
# ---------------------------------------------------------------------------

def test_stress_scenario_shape():
    stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
    assert set(stress.keys()) == {"demandSurge", "supplyDip"}
    for scenario in stress.values():
        assert "description" in scenario
        assert isinstance(scenario["description"], str)
        for policy in ("noSharing", "exchange"):
            sr = scenario[policy]
            assert "policy" in sr
            assert "unitsDelivered" in sr
            assert sr["unitsDelivered"] >= sr["unitsTransfused"] + sr["unitsWasted"]


def test_demand_surge_increases_shortages():
    """Demand surge should cause more shortages than baseline."""
    from sim.simulate import runSimulation
    baseline_sc = generateScenario(ASSUMPTIONS, HOSPITALS, 42)
    baseline = runSimulation(baseline_sc, "noSharing", 42)

    stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
    surge_noSharing = stress["demandSurge"]["noSharing"]

    # Surge scenario should have more shortages than baseline
    assert surge_noSharing["shortageEvents"] >= baseline["shortageEvents"], \
        f"Surge should not reduce shortages: surge={surge_noSharing['shortageEvents']}, baseline={baseline['shortageEvents']}"


def test_supply_dip_increases_shortages():
    """Supply dip should cause more shortages than baseline."""
    from sim.simulate import runSimulation
    baseline_sc = generateScenario(ASSUMPTIONS, HOSPITALS, 42)
    baseline = runSimulation(baseline_sc, "noSharing", 42)

    stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
    dip_noSharing = stress["supplyDip"]["noSharing"]

    assert dip_noSharing["shortageEvents"] >= baseline["shortageEvents"], \
        f"Supply dip should not reduce shortages: dip={dip_noSharing['shortageEvents']}, baseline={baseline['shortageEvents']}"


def test_exchange_not_worse_than_no_sharing_in_stress():
    """Exchange should not significantly exceed noSharing waste in stress scenarios."""
    stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
    for name, scenario in stress.items():
        ns_waste = scenario["noSharing"]["wasteRate"]
        ex_waste = scenario["exchange"]["wasteRate"]
        assert ex_waste <= ns_waste + 0.02, \
            f"{name}: exchange wasteRate ({ex_waste:.4f}) significantly worse than noSharing ({ns_waste:.4f})"


if __name__ == "__main__":
    test_all_seeds_valid()
    test_statistics_shape()
    test_statistics_mean_within_min_max()
    test_no_sharing_zero_transfers_stat()
    test_deterministic_across_runs()
    test_stress_scenario_shape()
    test_demand_surge_increases_shortages()
    test_supply_dip_increases_shortages()
    test_exchange_not_worse_than_no_sharing_in_stress()
    print("All tests passed.")
