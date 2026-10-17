"""Tests for sim/generate.py"""

import sys
import pathlib
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.generate import _SHELF_LIFE_DAYS, generateScenario

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
            self.assertEqual((expires - collected).days, _SHELF_LIFE_DAYS,
                             f"Unit {unit['unitId']}: shelf life != {_SHELF_LIFE_DAYS}")

    def test_remaining_shelf_life_on_arrival(self):
        from datetime import timedelta
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        simStart = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
        minLeft = ASSUMPTIONS["remainingShelfLifeOnArrivalDays"]["min"]
        earliest_possible_collected = simStart - timedelta(days=_SHELF_LIFE_DAYS - minLeft)
        for unit in scenario["deliveries"]:
            collected = datetime.strptime(unit["collectedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            self.assertGreaterEqual(collected, earliest_possible_collected,
                                    f"Unit {unit['unitId']} collected too early")

    def test_demand_follows_blood_group_mix(self):
        """Demand reflects the population mix. Deliveries do not: they follow each
        hospital's ordering policy, which over-supplies rare groups it must keep
        a minimum of and under-supplies common ones it turns over quickly."""
        big = generateScenario({**ASSUMPTIONS, "simDays": 90}, HOSPITALS, SEED)
        totals: dict = {}
        for record in big["demand"]:
            totals[record["bloodGroup"]] = totals.get(record["bloodGroup"], 0) + record["units"]
        grand = sum(totals.values())
        for bg, expectedFraction in ASSUMPTIONS["bloodGroupMix"].items():
            actualFraction = totals.get(bg, 0) / grand
            self.assertLess(abs(actualFraction - expectedFraction), 0.05,
                            f"{bg}: expected {expectedFraction:.3f}, got {actualFraction:.3f}")

    def test_deliveries_track_target_stock(self):
        """A hospital should not be sent more of a group than its target cover
        plus what it actually used -- that was the old blind-shipment behavior."""
        big = generateScenario({**ASSUMPTIONS, "simDays": 90}, HOSPITALS, SEED)
        delivered: dict = {}
        for unit in big["deliveries"]:
            key = (unit["hospitalId"], unit["bloodGroup"])
            delivered[key] = delivered.get(key, 0) + 1
        used: dict = {}
        for record in big["demand"]:
            key = (record["hospitalId"], record["bloodGroup"])
            used[key] = used.get(key, 0) + record["units"]
        sizes = {x["hospitalId"]: x["sizeCategory"] for x in HOSPITALS}
        for (hospitalId, bloodGroup), count in delivered.items():
            cover = (ASSUMPTIONS["targetStockDays"][sizes[hospitalId]]
                     * ASSUMPTIONS["dailyDemandMean"][sizes[hospitalId]]
                     * ASSUMPTIONS["bloodGroupMix"][bloodGroup])
            # Cap: everything consumed, plus one shelf-full restocked each day it could expire.
            ceiling = used.get((hospitalId, bloodGroup), 0) + max(1, round(cover)) * 90
            self.assertLessEqual(count, ceiling,
                                 f"{hospitalId}/{bloodGroup}: {count} delivered exceeds plausible ceiling")

    def test_demand_keys(self):
        scenario = generateScenario(ASSUMPTIONS, HOSPITALS, SEED)
        required = {"date", "hospitalId", "bloodGroup", "units"}
        for record in scenario["demand"]:
            self.assertEqual(required, set(record.keys()))
            self.assertGreater(record["units"], 0)
            self.assertIn(record["bloodGroup"], ASSUMPTIONS["bloodGroupMix"])


if __name__ == "__main__":
    unittest.main()
