"""Tests for sim/generate.py"""

import sys
import pathlib
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.generate import generateScenario

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
    {"hospitalId": f"H{i:02d}", "name": f"Hospital {i}",
     "lat": 53.4 + i * 0.01, "lng": -2.2, "sizeCategory": size, "hasHaematology": True}
    for i, size in enumerate(
        ["large", "large", "large", "medium", "medium",
         "medium", "small", "small", "small", "small"], start=1
    )
]

SEED = 42


class TestGenerateScenario(unittest.TestCase):

    def test_reproducible(self):
        s1 = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        s2 = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        self.assertEqual(s1["deliveries"], s2["deliveries"])
        self.assertEqual(s1["demand"], s2["demand"])

    def test_different_seeds_differ(self):
        s1 = generateScenario(ASSUMPTIONS, HOSPITALS, seed=1)
        s2 = generateScenario(ASSUMPTIONS, HOSPITALS, seed=2)
        self.assertNotEqual(s1["deliveries"], s2["deliveries"])

    def test_delivery_count(self):
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        self.assertGreater(len(scenario["deliveries"]), 0)

    def test_unit_keys(self):
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        required = {"unitId", "bloodGroup", "collectedAt", "expiresAt", "hospitalId", "status", "deliveredAt"}
        for unit in scenario["deliveries"]:
            self.assertEqual(required, set(unit.keys()), f"Bad keys: {set(unit.keys())}")
            self.assertEqual(unit["status"], "available")
            self.assertIn(unit["bloodGroup"], ASSUMPTIONS["bloodGroupMix"])

    def test_shelf_life_math(self):
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        for unit in scenario["deliveries"]:
            collected = datetime.strptime(unit["collectedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            expires = datetime.strptime(unit["expiresAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            self.assertEqual((expires - collected).days, 7, f"Unit {unit['unitId']}: shelf life != 7")

    def test_remaining_shelf_life_on_arrival(self):
        from datetime import timedelta
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        simStart = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
        minLeft = ASSUMPTIONS["remainingShelfLifeOnArrivalDays"]["min"]
        earliest_possible_collected = simStart - timedelta(days=7 - minLeft)
        for unit in scenario["deliveries"]:
            collected = datetime.strptime(unit["collectedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            self.assertGreaterEqual(collected, earliest_possible_collected,
                                    f"Unit {unit['unitId']} collected too early")

    def test_blood_group_distribution(self):
        big = generateScenario({**ASSUMPTIONS, "simDays": 90}, HOSPITALS, SEED)
        totals: dict = {}
        for unit in big["deliveries"]:
            bg = unit["bloodGroup"]
            totals[bg] = totals.get(bg, 0) + 1
        grand = sum(totals.values())
        for bg, expected_frac in ASSUMPTIONS["bloodGroupMix"].items():
            actual_frac = totals.get(bg, 0) / grand
            self.assertLess(abs(actual_frac - expected_frac), 0.05,
                            f"{bg}: expected {expected_frac:.3f}, got {actual_frac:.3f}")

    def test_demand_keys(self):
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        required = {"date", "hospitalId", "bloodGroup", "units"}
        for record in scenario["demand"]:
            self.assertEqual(required, set(record.keys()))
            self.assertGreater(record["units"], 0)
            self.assertIn(record["bloodGroup"], ASSUMPTIONS["bloodGroupMix"])


if __name__ == "__main__":
    unittest.main()
