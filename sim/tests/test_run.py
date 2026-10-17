"""Tests for sim/run.py -- checks comparison.json output shape (+16h shape)."""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.run import run

_SMALL_SEEDS = [1, 2, 3]  # keep tests fast


def test_top_level_keys():
    result = run(seeds=_SMALL_SEEDS)
    assert set(result.keys()) == {"generatedAt", "seeds", "statistics", "stressScenarios"}
    assert result["seeds"] == _SMALL_SEEDS
    assert isinstance(result["generatedAt"], str)


def test_statistics_shape():
    result = run(seeds=_SMALL_SEEDS)
    stat_keys = {"mean", "stdDev", "min", "max"}
    for policy in ("noSharing", "exchange"):
        ps = result["statistics"][policy]
        assert set(ps["wasteRate"].keys()) == stat_keys
        assert set(ps["shortageEvents"].keys()) == stat_keys


def test_stress_scenarios_shape():
    result = run(seeds=_SMALL_SEEDS)
    ss = result["stressScenarios"]
    assert set(ss.keys()) == {"demandSurge", "supplyDip"}
    for scenario in ss.values():
        assert "description" in scenario
        for policy in ("noSharing", "exchange"):
            sr = scenario[policy]
            assert sr["unitsDelivered"] >= sr["unitsTransfused"] + sr["unitsWasted"]


def test_deterministic():
    r1 = run(seeds=[7, 8])
    r2 = run(seeds=[7, 8])
    assert r1["statistics"]["noSharing"]["wasteRate"]["mean"] == \
           r2["statistics"]["noSharing"]["wasteRate"]["mean"]


if __name__ == "__main__":
    test_top_level_keys()
    test_statistics_shape()
    test_stress_scenarios_shape()
    test_deterministic()
    print("All tests passed.")
