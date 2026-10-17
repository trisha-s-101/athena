import copy
import inspect
import json
import random
import unittest
from datetime import datetime, timedelta, timezone

import engine
from engine import forecastDemand, rankEmergencySources, recommendTransfers


now = "2026-01-05T00:00:00Z"
nowTime = datetime(2026, 1, 5, tzinfo=timezone.utc)
compatibility = {
    "A+": [{"donor": "A+", "penalty": 0}, {"donor": "O+", "penalty": 3}],
    "O+": [{"donor": "O+", "penalty": 0}],
    "O-": [{"donor": "O-", "penalty": 0}],
}


def makeUnit(unitId, hospitalId="H01", bloodGroup="A+", hoursLeft=24,
             status="available"):
    expiryTime = nowTime + timedelta(hours=hoursLeft)
    return {
        "unitId": unitId, "hospitalId": hospitalId, "bloodGroup": bloodGroup,
        "collectedAt": (expiryTime - timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "expiresAt": expiryTime.isoformat().replace("+00:00", "Z"), "status": status,
    }


def makeRoute(fromId="H01", toId="H02", minutes=30):
    return {"fromHospitalId": fromId, "toHospitalId": toId, "minutes": minutes}


def makeRecord(recordDate, units, hospitalId="H01", bloodGroup="A+"):
    return {"date": recordDate, "hospitalId": hospitalId,
            "bloodGroup": bloodGroup, "units": units}


class InterfaceTests(unittest.TestCase):
    def testPublicContractSignatures(self):
        self.assertEqual(engine.__all__, [
            "forecastDemand", "recommendTransfers", "rankEmergencySources",
        ])
        self.assertEqual(list(inspect.signature(forecastDemand).parameters),
                         ["history", "horizonDays"])
        self.assertEqual(list(inspect.signature(recommendTransfers).parameters),
                         ["stock", "forecast", "travelTimes", "compatibility", "now"])
        self.assertEqual(list(inspect.signature(rankEmergencySources).parameters),
                         ["request", "stock", "travelTimes", "compatibility", "now"])


class ForecastTests(unittest.TestCase):
    def testWeekdayAverageAndIndependentPairs(self):
        history = [makeRecord("2025-12-22", 2), makeRecord("2025-12-29", 6),
                   makeRecord("2026-01-04", 0),
                   makeRecord("2025-12-22", 10, "H02", "O+")]
        result = forecastDemand(history)
        self.assertEqual(result["H01"]["A+"], [4.0, 0.0, 0.0])
        self.assertEqual(result["H02"]["O+"], [5.0, 0.0, 0.0])

    def testMissingWeekdayFallsBackToDailyMean(self):
        self.assertEqual(forecastDemand([makeRecord("2026-01-04", 2)]),
                         {"H01": {"A+": [2.0, 2.0, 2.0]}})

    def testSparseDatesCountAsZeroAndDuplicatesSum(self):
        history = [makeRecord("2026-01-01", 2), makeRecord("2026-01-01", 4),
                   makeRecord("2026-01-03", 0)]
        self.assertEqual(forecastDemand(history, 1), {"H01": {"A+": [2.0]}})

    def testEmptyHistoryAndZeroHorizon(self):
        self.assertEqual(forecastDemand([]), {})
        self.assertEqual(forecastDemand([makeRecord("2026-01-04", 1)], 0),
                         {"H01": {"A+": []}})

    def testInvalidHorizonAndDemand(self):
        for value in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                forecastDemand([], value)
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                forecastDemand([makeRecord("2026-01-04", value)])

    def testUnsortedInputIsNotMutated(self):
        history = [makeRecord("2026-01-04", 2), makeRecord("2025-12-29", 4)]
        original = copy.deepcopy(history)
        self.assertEqual(forecastDemand(history), forecastDemand(list(reversed(history))))
        self.assertEqual(history, original)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.forecast = {"H01": {"A+": [0, 0, 0]}, "H02": {"A+": [2, 0, 0]}}
        self.routes = [makeRoute()]

    def recommend(self, stock, forecast=None, routes=None, clock=now):
        return recommendTransfers(stock, self.forecast if forecast is None else forecast,
                                  self.routes if routes is None else routes, compatibility, clock)

    def testObviousSurplusAndContractShape(self):
        result = self.recommend([makeUnit("U000001")])
        self.assertEqual(len(result), 1)
        transfer = result[0]
        self.assertEqual(set(transfer), {"unitId", "fromHospitalId", "toHospitalId",
                                       "travelMinutes", "hoursToExpiry", "score", "reason"})
        self.assertEqual(transfer["toHospitalId"], "H02")
        self.assertEqual(transfer["fromHospitalId"], "H01")
        self.assertEqual(transfer["travelMinutes"], 30)
        self.assertEqual(transfer["hoursToExpiry"], 24)
        self.assertGreater(transfer["score"], 0)
        json.dumps(result, allow_nan=False)

    def testProtectLocalFifoStockIncludingFractionalDemand(self):
        forecast = {"H01": {"A+": [0.2, 0, 0]}, "H02": {"A+": [2, 0, 0]}}
        result = self.recommend([makeUnit("old", hoursLeft=24),
                                 makeUnit("new", hoursLeft=48)], forecast)
        self.assertEqual([item["unitId"] for item in result], ["new"])

    def testProtectCompatibleLocalUseAcrossGroups(self):
        forecast = {"H01": {"A+": [1, 0, 0]}, "H02": {"O+": [2, 0, 0]}}
        self.assertEqual(self.recommend([makeUnit("U1", bloodGroup="O+")], forecast), [])

    def testDestinationStockAlreadyCoversDemand(self):
        self.assertEqual(self.recommend([makeUnit("donor"), makeUnit("local", "H02")],
                                       {"H01": {"A+": [0]}, "H02": {"A+": [1]}}), [])

    def testNoDuplicateAndNoOverfillingFromMultipleHospitals(self):
        stock = [makeUnit("U1"), makeUnit("U1"), makeUnit("U2", "H03")]
        routes = [makeRoute(), makeRoute("H03", "H02")]
        forecast = {"H01": {"A+": [0]}, "H02": {"A+": [1]}, "H03": {"A+": [0]}}
        self.assertEqual(len(self.recommend(stock, forecast, routes)), 1)

    def testExcludeExpiredUnavailableFutureAndIncompatibleUnits(self):
        stock = [makeUnit("expired", hoursLeft=0), makeUnit("past", hoursLeft=-1),
                 makeUnit("future", hoursLeft=200), makeUnit("badGroup", bloodGroup="B+")]
        for status in ("reserved", "inTransit", "transfused", "expired"):
            stock.append(makeUnit(status, status=status))
        self.assertEqual(self.recommend(stock), [])

    def testMinimumShelfLifeBoundary(self):
        self.assertEqual(self.recommend([makeUnit("short", hoursLeft=11.99)]), [])
        self.assertEqual(len(self.recommend([makeUnit("exact", hoursLeft=12)])), 1)

    def testTravelLimitBoundaryAndDirectedMissingRoutes(self):
        self.assertEqual(len(self.recommend([makeUnit("U1")], routes=[makeRoute(minutes=240)])), 1)
        self.assertEqual(self.recommend([makeUnit("U1")], routes=[makeRoute(minutes=241)]), [])
        self.assertEqual(self.recommend([makeUnit("U1")], routes=[]), [])
        self.assertEqual(self.recommend([makeUnit("U1")],
                                       routes=[makeRoute("H02", "H01")]), [])

    def testInvalidRouteIsNotUsed(self):
        for minutes in (-1, float("nan"), float("inf")):
            self.assertEqual(self.recommend([makeUnit("U1")],
                                           routes=[makeRoute(minutes=minutes)]), [])

    def testDemandBeforeArrivalDoesNotJustifyTransfer(self):
        forecast = {"H01": {"A+": [0, 0]}, "H02": {"A+": [100, 0]}}
        self.assertEqual(self.recommend([makeUnit("U1", hoursLeft=36)], forecast,
                                       clock="2026-01-05T23:45:00Z"), [])

    def testDemandAfterExpiryDoesNotJustifyTransfer(self):
        forecast = {"H01": {"A+": [0, 0, 0]}, "H02": {"A+": [0, 0, 10]}}
        self.assertEqual(self.recommend([makeUnit("U1", hoursLeft=24)], forecast), [])

    def testOnlyUnmetDemandAfterArrivalCounts(self):
        # One local unit covers the first half-day; the shortfall follows it.
        forecast = {"H01": {"A+": [0]}, "H02": {"A+": [2]}}
        stock = [makeUnit("donor"), makeUnit("local", "H02", hoursLeft=12)]
        self.assertEqual([item["unitId"] for item in self.recommend(stock, forecast)], ["donor"])

    def testNoTransfersPastForecastHorizon(self):
        self.assertEqual(self.recommend([makeUnit("U1", hoursLeft=80)]), [])
        self.assertEqual(self.recommend([makeUnit("U1")], {}), [])

    def testPreferredDestinationWinsCompatibilityTie(self):
        forecast = {"H01": {"O+": [0]}, "H02": {"A+": [2]}, "H03": {"O+": [2]}}
        routes = [makeRoute(minutes=10), makeRoute("H01", "H03", 60)]
        result = self.recommend([makeUnit("U1", bloodGroup="O+")], forecast, routes)
        self.assertEqual(result[0]["toHospitalId"], "H03")

    def testNoSelfTransfers(self):
        forecast = {"H01": {"A+": [2]}}
        self.assertEqual(self.recommend([makeUnit("U1")], forecast,
                                       [makeRoute("H01", "H01", 0)]), [])

    def testDeterministicAndDoesNotMutateInputs(self):
        stock = [makeUnit("U2"), makeUnit("U1")]
        original = copy.deepcopy((stock, self.forecast, self.routes, compatibility))
        result = self.recommend(stock)
        self.assertEqual(result, self.recommend(list(reversed(stock))))
        self.assertEqual((stock, self.forecast, self.routes, compatibility), original)
        self.assertEqual([item["score"] for item in result],
                         sorted([item["score"] for item in result], reverse=True))

    def testUtcOffsetAndPartialDay(self):
        forecast = {"H01": {"A+": [0]}, "H02": {"A+": [2]}}
        result = self.recommend([makeUnit("U1")], forecast,
                                clock="2026-01-05T13:00:00+01:00")
        self.assertEqual(result[0]["hoursToExpiry"], 12)

    def testSeededStockInvariants(self):
        randomizer = random.Random(42)
        stock = [makeUnit(f"U{index}", randomizer.choice(["H01", "H02", "H03"]),
                          randomizer.choice(["A+", "O+", "O-"]),
                          randomizer.randrange(-3, 80),
                          randomizer.choice(["available", "available", "reserved"]))
                 for index in range(75)]
        forecast = {hospitalId: {group: [2, 2, 2] for group in ["A+", "O+", "O-"]}
                    for hospitalId in ["H01", "H02", "H03"]}
        routes = [makeRoute(source, target, 20) for source in forecast for target in forecast]
        result = self.recommend(stock, forecast, routes)
        self.assertEqual(len(result), len({item["unitId"] for item in result}))
        unitMap = {unit["unitId"]: unit for unit in stock}
        for transfer in result:
            unit = unitMap[transfer["unitId"]]
            self.assertEqual(unit["status"], "available")
            self.assertGreaterEqual(transfer["hoursToExpiry"], 12)
            self.assertLessEqual(transfer["travelMinutes"], 240)
            self.assertNotEqual(transfer["fromHospitalId"], transfer["toHospitalId"])
            self.assertGreaterEqual(transfer["score"], 0)
            self.assertLessEqual(transfer["score"], 1)


class EmergencyTests(unittest.TestCase):
    def setUp(self):
        self.request = {"hospitalId": "H02", "bloodGroup": "A+", "unitsNeeded": 1}

    def rank(self, stock, routes=None):
        return rankEmergencySources(self.request, stock,
                                    [makeRoute()] if routes is None else routes,
                                    compatibility, now)

    def testPenaltyThenTravelThenExpiryAndAllAlternatives(self):
        stock = [makeUnit("substitute", bloodGroup="O+", hoursLeft=12),
                 makeUnit("far", "H03", hoursLeft=12),
                 makeUnit("later", hoursLeft=48), makeUnit("earlier", hoursLeft=24)]
        result = self.rank(stock, [makeRoute(), makeRoute("H03", "H02", 40)])
        self.assertEqual([source["unitId"] for source in result],
                         ["earlier", "later", "far", "substitute"])
        self.assertEqual([source["rank"] for source in result], [1, 2, 3, 4])
        self.assertEqual(set(result[0]), {"unitId", "hospitalId", "bloodGroup",
                                          "hoursToExpiry", "travelMinutes", "penalty", "rank"})

    def testExcludeOwnUnavailableExpiredIncompatibleAndDuplicates(self):
        stock = [makeUnit("own", "H02"), makeUnit("bad", bloodGroup="B+"),
                 makeUnit("gone", hoursLeft=0), makeUnit("held", status="reserved"),
                 makeUnit("ok"), makeUnit("ok")]
        self.assertEqual([source["unitId"] for source in self.rank(stock)], ["ok"])

    def testMustArriveStrictlyBeforeExpiry(self):
        self.assertEqual(self.rank([makeUnit("late", hoursLeft=0.5)]), [])
        self.assertEqual(len(self.rank([makeUnit("ok", hoursLeft=0.51)])), 1)

    def testEmergencyAllowsShortShelfLifeAndLongTrips(self):
        self.assertEqual(len(self.rank([makeUnit("urgent", hoursLeft=6)],
                                      [makeRoute(minutes=300)])), 1)

    def testMissingRoutesAndUnknownRecipient(self):
        self.assertEqual(self.rank([makeUnit("U1")], []), [])
        self.assertEqual(self.rank([makeUnit("U1")], [makeRoute("H02", "H01")]), [])
        self.request["bloodGroup"] = "AB-"
        self.assertEqual(self.rank([makeUnit("U1")]), [])

    def testNoUnitsRequestedAndEmptyStock(self):
        self.assertEqual(self.rank([]), [])
        self.request["unitsNeeded"] = 0
        self.assertEqual(self.rank([makeUnit("U1")]), [])

    def testDeterministicAndDoesNotMutateInputs(self):
        stock = [makeUnit("U2"), makeUnit("U1")]
        routes = [makeRoute()]
        original = copy.deepcopy((self.request, stock, routes, compatibility))
        result = self.rank(stock, routes)
        self.assertEqual(result, self.rank(list(reversed(stock)), routes))
        self.assertEqual((self.request, stock, routes, compatibility), original)


if __name__ == "__main__":
    unittest.main()
