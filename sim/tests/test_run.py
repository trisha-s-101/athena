"""Tests for sim/run.py -- checks comparison.json output shape."""

import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.run import run

_SMALL_SEEDS = [1, 2, 3]  # keep tests fast


class TestRunOutput(unittest.TestCase):

    def setUp(self):
        self.result = run(seeds=_SMALL_SEEDS)

    def test_top_level_keys(self):
        expected = {"generatedAt", "seed", "noSharing", "exchange",
                    "seeds", "statistics", "stressScenarios"}
        self.assertEqual(set(self.result.keys()), expected)
        self.assertEqual(self.result["seeds"], _SMALL_SEEDS)
        self.assertIsInstance(self.result["generatedAt"], str)

    def test_canonical_sim_results(self):
        """Old CONTRACT §7 keys: seed, noSharing, exchange must be present."""
        self.assertEqual(self.result["seed"], 42)
        simResultKeys = {"policy", "days", "unitsDelivered", "unitsTransfused",
                         "unitsWasted", "wasteRate", "shortageEvents", "transfers", "daily"}
        for policy in ("noSharing", "exchange"):
            self.assertEqual(set(self.result[policy].keys()), simResultKeys)

    def test_statistics_shape(self):
        statKeys = {"mean", "stdDev", "min", "max"}
        for policy in ("noSharing", "exchange"):
            ps = self.result["statistics"][policy]
            self.assertEqual(set(ps["wasteRate"].keys()), statKeys)
            self.assertEqual(set(ps["shortageEvents"].keys()), statKeys)

    def test_stress_scenarios_shape(self):
        ss = self.result["stressScenarios"]
        self.assertEqual(set(ss.keys()), {"demandSurge", "supplyDip"})
        for scenario in ss.values():
            self.assertIn("description", scenario)
            for policy in ("noSharing", "exchange"):
                sr = scenario[policy]
                self.assertGreaterEqual(sr["unitsDelivered"],
                                        sr["unitsTransfused"] + sr["unitsWasted"])

    def test_deterministic(self):
        r2 = run(seeds=[1, 2])
        r3 = run(seeds=[1, 2])
        self.assertEqual(r2["statistics"]["noSharing"]["wasteRate"]["mean"],
                         r3["statistics"]["noSharing"]["wasteRate"]["mean"])


if __name__ == "__main__":
    unittest.main()
