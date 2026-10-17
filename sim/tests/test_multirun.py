"""Tests for sim/multirun.py (+16h milestone)."""

import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.generate import generateScenario
from sim.multirun import runMultiSeed, runStressScenarios

ASSUMPTIONS = {
    "simDays": 10,
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


class TestRunMultiSeed(unittest.TestCase):

    def test_all_seeds_valid(self):
        result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
        self.assertEqual(result["seeds"], SEEDS)
        required = {"policy", "days", "unitsDelivered", "unitsTransfused",
                    "unitsWasted", "wasteRate", "shortageEvents", "transfers", "daily"}
        for policy in ("noSharing", "exchange"):
            rawResults = result["_rawResults"][policy]
            self.assertEqual(len(rawResults), len(SEEDS))
            for sr in rawResults:
                self.assertEqual(required, set(sr.keys()), f"Missing keys in {policy} result")
                self.assertGreaterEqual(sr["unitsDelivered"],
                                        sr["unitsTransfused"] + sr["unitsWasted"])

    def test_statistics_shape(self):
        result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
        stats = result["statistics"]
        statKeys = {"mean", "stdDev", "min", "max"}
        for policy in ("noSharing", "exchange"):
            ps = stats[policy]
            self.assertGreaterEqual(set(ps.keys()), {"wasteRate", "shortageEvents", "transfers"})
            self.assertEqual(set(ps["wasteRate"].keys()), statKeys)
            self.assertEqual(set(ps["shortageEvents"].keys()), statKeys)
            if policy == "exchange":
                self.assertEqual(set(ps["transfers"].keys()), statKeys)
            else:
                self.assertEqual(ps["transfers"], 0)

    def test_statistics_mean_within_min_max(self):
        result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
        stats = result["statistics"]
        for policy in ("noSharing", "exchange"):
            for metric in ("wasteRate", "shortageEvents"):
                s = stats[policy][metric]
                self.assertLessEqual(s["min"], s["mean"],
                                     f"{policy}.{metric}: mean below min")
                self.assertLessEqual(s["mean"], s["max"],
                                     f"{policy}.{metric}: mean above max")

    def test_no_sharing_zero_transfers_stat(self):
        result = runMultiSeed(ASSUMPTIONS, HOSPITALS, SEEDS)
        self.assertEqual(result["statistics"]["noSharing"]["transfers"], 0)

    def test_deterministic_across_runs(self):
        r1 = runMultiSeed(ASSUMPTIONS, HOSPITALS, [1, 2, 3])
        r2 = runMultiSeed(ASSUMPTIONS, HOSPITALS, [1, 2, 3])
        self.assertEqual(r1["statistics"]["noSharing"]["wasteRate"],
                         r2["statistics"]["noSharing"]["wasteRate"])


class TestRunStressScenarios(unittest.TestCase):

    def test_stress_scenario_shape(self):
        stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
        self.assertEqual(set(stress.keys()), {"demandSurge", "supplyDip"})
        for scenario in stress.values():
            self.assertIn("description", scenario)
            self.assertIsInstance(scenario["description"], str)
            for policy in ("noSharing", "exchange"):
                sr = scenario[policy]
                self.assertIn("policy", sr)
                self.assertIn("unitsDelivered", sr)
                self.assertGreaterEqual(sr["unitsDelivered"],
                                        sr["unitsTransfused"] + sr["unitsWasted"])

    def test_demand_surge_increases_shortages(self):
        from sim.simulate import runSimulation
        baseline_sc = generateScenario(ASSUMPTIONS, HOSPITALS, 42)
        baseline = runSimulation(baseline_sc, "noSharing", 42)
        stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
        surge = stress["demandSurge"]["noSharing"]
        self.assertGreaterEqual(surge["shortageEvents"], baseline["shortageEvents"],
                                f"Surge should not reduce shortages: "
                                f"surge={surge['shortageEvents']}, baseline={baseline['shortageEvents']}")

    def test_supply_dip_increases_shortages(self):
        from sim.simulate import runSimulation
        baseline_sc = generateScenario(ASSUMPTIONS, HOSPITALS, 42)
        baseline = runSimulation(baseline_sc, "noSharing", 42)
        stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
        dip = stress["supplyDip"]["noSharing"]
        self.assertGreaterEqual(dip["shortageEvents"], baseline["shortageEvents"],
                                f"Supply dip should not reduce shortages: "
                                f"dip={dip['shortageEvents']}, baseline={baseline['shortageEvents']}")

    def test_exchange_not_worse_than_no_sharing_in_stress(self):
        stress = runStressScenarios(ASSUMPTIONS, HOSPITALS, seed=42)
        for name, scenario in stress.items():
            ns_waste = scenario["noSharing"]["wasteRate"]
            ex_waste = scenario["exchange"]["wasteRate"]
            self.assertLessEqual(ex_waste, ns_waste + 0.02,
                                 f"{name}: exchange wasteRate ({ex_waste:.4f}) "
                                 f"significantly worse than noSharing ({ns_waste:.4f})")


if __name__ == "__main__":
    unittest.main()
