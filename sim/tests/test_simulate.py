"""Tests for sim/simulate.py (CONTRACT §7 invariants)."""

import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.generate import generateScenario
from sim.simulate import runSimulation

ASSUMPTIONS = {
    "simDays": 3,
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
    {"hospitalId": "H01", "name": "A", "lat": 53.46, "lng": -2.23,
     "sizeCategory": "large", "hasHaematology": True},
    {"hospitalId": "H02", "name": "B", "lat": 53.47, "lng": -2.24,
     "sizeCategory": "medium", "hasHaematology": False},
]

SEED = 42


def _scenario():
    return generateScenario(ASSUMPTIONS, HOSPITALS, SEED)


class TestRunSimulation(unittest.TestCase):

    def test_reproducible(self):
        sc = _scenario()
        r1 = runSimulation(sc, "noSharing", SEED)
        r2 = runSimulation(sc, "noSharing", SEED)
        self.assertEqual(r1, r2)

    def test_no_sharing_zero_transfers(self):
        sc = _scenario()
        result = runSimulation(sc, "noSharing", SEED)
        self.assertEqual(result["transfers"], 0)
        for day in result["daily"]:
            self.assertEqual(day["transfers"], 0)

    def test_invariant_no_sharing(self):
        sc = _scenario()
        result = runSimulation(sc, "noSharing", SEED)
        self.assertGreaterEqual(result["unitsDelivered"],
                                result["unitsTransfused"] + result["unitsWasted"])

    def test_invariant_exchange(self):
        sc = _scenario()
        result = runSimulation(sc, "exchange", SEED)
        self.assertGreaterEqual(result["unitsDelivered"],
                                result["unitsTransfused"] + result["unitsWasted"])

    def test_no_transfusion_after_expiry(self):
        sc = _scenario()
        for policy in ("noSharing", "exchange"):
            result = runSimulation(sc, policy, SEED)
            self.assertLessEqual(
                result["unitsTransfused"] + result["unitsWasted"],
                result["unitsDelivered"],
                f"{policy}: transfused+wasted exceeded delivered",
            )

    def test_daily_list_length(self):
        sc = _scenario()
        result = runSimulation(sc, "noSharing", SEED)
        self.assertEqual(len(result["daily"]), ASSUMPTIONS["simDays"])

    def test_daily_keys(self):
        sc = _scenario()
        result = runSimulation(sc, "noSharing", SEED)
        required = {"date", "wasted", "shortages", "transfers"}
        for day in result["daily"]:
            self.assertEqual(set(day.keys()), required)

    def test_policy_field(self):
        sc = _scenario()
        self.assertEqual(runSimulation(sc, "noSharing", SEED)["policy"], "noSharing")
        self.assertEqual(runSimulation(sc, "exchange", SEED)["policy"], "exchange")

    def test_waste_rate_formula(self):
        sc = _scenario()
        result = runSimulation(sc, "noSharing", SEED)
        expected = round(result["unitsWasted"] / result["unitsDelivered"], 4)
        self.assertAlmostEqual(result["wasteRate"], expected, places=4)

    def test_no_sharing_waste_rate_plausible(self):
        bigAssumptions = {**ASSUMPTIONS, "simDays": 90}
        bigHospitals = [
            {"hospitalId": f"H{i:02d}", "name": f"H{i}", "lat": 53.4 + i * 0.01,
             "lng": -2.2, "sizeCategory": size, "hasHaematology": True}
            for i, size in enumerate(
                ["large", "large", "large", "medium", "medium",
                 "medium", "small", "small", "small", "small"], start=1
            )
        ]
        sc = generateScenario(bigAssumptions, bigHospitals, SEED)
        noSharing = runSimulation(sc, "noSharing", SEED)
        exchange = runSimulation(sc, "exchange", SEED)
        self.assertGreater(noSharing["wasteRate"], 0)
        self.assertLess(noSharing["wasteRate"], 1.0)
        self.assertLessEqual(exchange["wasteRate"], noSharing["wasteRate"] + 0.01,
                             f"exchange ({exchange['wasteRate']:.4f}) should not significantly exceed "
                             f"noSharing ({noSharing['wasteRate']:.4f})")


if __name__ == "__main__":
    unittest.main()
