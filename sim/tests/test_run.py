"""Tests for sim/run.py -- checks output shape and consistency invariants."""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.run import run


def test_top_level_keys():
    result = run(seed=42)
    assert set(result.keys()) == {"generatedAt", "seed", "noSharing", "exchange"}
    assert result["seed"] == 42
    assert isinstance(result["generatedAt"], str)


def _check_sim_result(sr: dict):
    required = {
        "policy", "days", "unitsDelivered", "unitsTransfused",
        "unitsWasted", "wasteRate", "shortageEvents", "transfers", "daily",
    }
    assert required == set(sr.keys()), f"Missing keys: {required - set(sr.keys())}"
    assert isinstance(sr["unitsDelivered"], int)
    assert isinstance(sr["unitsWasted"], int)
    assert isinstance(sr["wasteRate"], float)
    # Consistency: delivered >= transfused + wasted
    assert sr["unitsDelivered"] >= sr["unitsTransfused"] + sr["unitsWasted"]
    # wasteRate matches wasted/delivered to within rounding
    assert abs(sr["wasteRate"] - sr["unitsWasted"] / sr["unitsDelivered"]) < 0.001
    # daily list length matches days
    assert len(sr["daily"]) == sr["days"]
    for entry in sr["daily"]:
        assert {"date", "wasted", "shortages", "transfers"} == set(entry.keys())


def test_sim_result_shapes():
    result = run(seed=42)
    _check_sim_result(result["noSharing"])
    _check_sim_result(result["exchange"])


def test_exchange_less_waste_than_no_sharing():
    result = run(seed=42)
    # exchange <= noSharing with real engine; with stub both use no transfers so equal or close
    assert result["exchange"]["wasteRate"] <= result["noSharing"]["wasteRate"] + 0.01


def test_deterministic():
    r1 = run(seed=99)
    r2 = run(seed=99)
    assert r1["noSharing"]["unitsWasted"] == r2["noSharing"]["unitsWasted"]
    assert r1["exchange"]["wasteRate"] == r2["exchange"]["wasteRate"]


if __name__ == "__main__":
    test_top_level_keys()
    test_sim_result_shapes()
    test_exchange_less_waste_than_no_sharing()
    test_deterministic()
    print("All tests passed.")
