"""Tests for the database-backed endpoints. They drop every table, so they need a throwaway database:
    TEST_DATABASE_URL=postgresql://... python -m unittest discover api/tests
Never point TEST_DATABASE_URL at the instance's real database.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api.database import closePool
from api.tests.server import ServerTestCase
from db.seed import loadSharedData, seedDatabase

testDatabaseUrl = os.environ.get("TEST_DATABASE_URL")
fixturesDir = Path(__file__).resolve().parents[2] / "db" / "tests" / "fixtures"


def makeUnit(unitId: str, expiresAt: str = "2026-01-12T08:00:00Z", hospitalId: str = "H01",
             bloodGroup: str = "A+", collectedAt: str = "2026-01-05T08:00:00Z") -> dict:
    return {"unitId": unitId, "bloodGroup": bloodGroup, "collectedAt": collectedAt,
            "expiresAt": expiresAt, "hospitalId": hospitalId, "status": "available"}


@unittest.skipUnless(testDatabaseUrl, "set TEST_DATABASE_URL to a throwaway database to run")
class DatabaseApiTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.psycopg2 = psycopg2
        cls.savedDatabaseUrl = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = testDatabaseUrl
        closePool()
        cls.hospitals, cls.travelTimes, _ = loadSharedData(fixturesDir)
        cls.startServer()

    @classmethod
    def tearDownClass(cls):
        cls.stopServer()
        closePool()
        if cls.savedDatabaseUrl is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.savedDatabaseUrl

    def setUp(self):
        connection = self.psycopg2.connect(testDatabaseUrl)
        try:
            seedDatabase(connection, self.hospitals, self.travelTimes, reset=True)
        finally:
            connection.close()

    def feed(self, event: dict):
        return self.request("POST", "/feed/events", event)

    def deliver(self, unit: dict):
        self.assertEqual(self.feed({"type": "delivery", "unit": unit}), (202, {"accepted": True}))

    def reserve(self, unitId: str, toHospitalId: str = "H02"):
        return self.request("POST", "/reservations", {"unitId": unitId, "toHospitalId": toHospitalId})

    def query(self, sql: str, params=()):
        connection = self.psycopg2.connect(testDatabaseUrl)
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
        finally:
            connection.close()

    def testHealthReportsDatabaseUp(self):
        self.assertIs(self.request("GET", "/health")[1]["dbOk"], True)

    def testHospitalsCountAvailableAndExpiringBySimTime(self):
        self.feed({"type": "clock", "simTime": "2026-01-05T12:00:00Z"})
        self.deliver(makeUnit("U000001", expiresAt="2026-01-06T08:00:00Z"))  # 20h left
        self.deliver(makeUnit("U000002"))
        self.deliver(makeUnit("U000003"))
        self.feed({"type": "transfusion", "unitId": "U000003"})
        status, hospitals = self.request("GET", "/hospitals")
        self.assertEqual(status, 200)
        self.assertEqual([hospital["hospitalId"] for hospital in hospitals], ["H01", "H02", "H03"])
        self.assertEqual(hospitals[0]["stockSummary"], {"available": 2, "expiringIn24h": 1})
        self.assertEqual(hospitals[1]["stockSummary"], {"available": 0, "expiringIn24h": 0})
        self.assertEqual(set(hospitals[0]), {"hospitalId", "name", "lat", "lng", "sizeCategory",
                                             "hasHaematology", "stockSummary"})

    def testStockShowsActiveUnitsSoonestExpiryFirst(self):
        self.deliver(makeUnit("U000001"))
        self.deliver(makeUnit("U000002", expiresAt="2026-01-07T08:00:00Z", hospitalId="H02"))
        self.deliver(makeUnit("U000003"))
        self.feed({"type": "expiry", "unitId": "U000003"})
        self.assertEqual(self.request("GET", "/stock"), (200, [
            makeUnit("U000002", expiresAt="2026-01-07T08:00:00Z", hospitalId="H02"), makeUnit("U000001"),
        ]))
        self.assertEqual([unit["unitId"] for unit in self.request("GET", "/stock?hospitalId=H01")[1]], ["U000001"])

    def testFeedRejectsBadEvents(self):
        self.deliver(makeUnit("U000001"))
        self.feed({"type": "transfusion", "unitId": "U000001"})
        cases = [
            ({"type": "delivery", "unit": makeUnit("U000001")}, (409, {"error": "unitAlreadyExists"})),
            ({"type": "delivery", "unit": makeUnit("U000009", hospitalId="H99")}, (400, {"error": "unknownHospital"})),
            ({"type": "delivery", "unit": makeUnit("U000009", expiresAt="2026-01-01T00:00:00Z")},
             (400, {"error": "invalidRequest"})),
            ({"type": "transfusion", "unitId": "U000001"}, (409, {"error": "unitNotAvailable"})),
            ({"type": "expiry", "unitId": "U999999"}, (404, {"error": "unitNotFound"})),
            ({"type": "demandUnmet", "hospitalId": "H99", "bloodGroup": "A+", "units": 1},
             (400, {"error": "unknownHospital"})),
            ({"type": "clock", "simTime": "not a time"}, (400, {"error": "invalidRequest"})),
        ]
        for event, expected in cases:
            with self.subTest(event=event):
                self.assertEqual(self.feed(event), expected)

    def testFeedLogsEventsAtSimTime(self):
        self.feed({"type": "clock", "simTime": "2026-01-05T06:00:00Z"})
        self.deliver(makeUnit("U000001"))
        self.feed({"type": "demandUnmet", "hospitalId": "H02", "bloodGroup": "O-", "units": 2})
        rows = self.query("SELECT event_id, type, unit_id, hospital_id, blood_group, units, "
                          "to_char(at AT TIME ZONE 'UTC', 'HH24:MI') FROM events ORDER BY event_number")
        self.assertEqual(rows, [
            ("E000001", "clock", None, None, None, None, "06:00"),
            ("E000002", "delivery", "U000001", "H01", "A+", 1, "06:00"),
            ("E000003", "demandUnmet", None, "H02", "O-", 2, "06:00"),
        ])

    def testReserveThenComplete(self):
        self.feed({"type": "clock", "simTime": "2026-01-05T14:00:00Z"})
        self.deliver(makeUnit("U000001"))
        status, reservation = self.reserve("U000001")
        self.assertEqual(status, 201)
        self.assertEqual(reservation, {"reservationId": "R000001", "unitId": "U000001", "fromHospitalId": "H01",
                                       "toHospitalId": "H02", "status": "accepted",
                                       "createdAt": "2026-01-05T14:00:00Z"})
        self.assertEqual(self.request("GET", "/stock")[1][0]["status"], "reserved")
        self.assertEqual(self.reserve("U000001"), (409, {"error": "unitNotAvailable"}))

        status, completed = self.request("POST", "/reservations/R000001/complete")
        self.assertEqual((status, completed), (200, {**reservation, "status": "completed"}))
        self.assertEqual(self.request("GET", "/stock?hospitalId=H02")[1], [makeUnit("U000001", hospitalId="H02")])
        self.assertEqual(self.request("POST", "/reservations/R000001/complete"), (200, completed))

    def testReservationErrorsLeaveUnitAvailable(self):
        self.deliver(makeUnit("U000001"))
        self.assertEqual(self.reserve("U000001", "H01"), (400, {"error": "sameHospital"}))
        self.assertEqual(self.reserve("U000001", "H99"), (400, {"error": "unknownHospital"}))
        self.assertEqual(self.reserve("U999999"), (409, {"error": "unitNotAvailable"}))
        self.assertEqual(self.request("GET", "/stock")[1][0]["status"], "available")
        self.assertEqual(self.request("POST", "/reservations/R999999/complete"),
                         (404, {"error": "reservationNotFound"}))

    def testCompleteFailsIfUnitWasTransfusedWhileReserved(self):
        self.deliver(makeUnit("U000001"))
        self.reserve("U000001")
        self.assertEqual(self.feed({"type": "transfusion", "unitId": "U000001"}), (202, {"accepted": True}))
        self.assertEqual(self.request("POST", "/reservations/R000001/complete"),
                         (409, {"error": "unitNotAvailable"}))

    def testMetricsBeforeAnyEvents(self):
        self.assertEqual(self.request("GET", "/metrics"), (200, {
            "simTime": "2026-01-05T00:00:00Z", "unitsAvailable": 0, "expiringIn24h": 0, "wastedToday": 0,
            "shortagesToday": 0, "transfersToday": 0, "wasteRate": 0.0,
        }))

    def testMetricsCountTheSimDay(self):
        self.feed({"type": "clock", "simTime": "2026-01-05T20:00:00Z"})
        for index in range(1, 5):
            self.deliver(makeUnit(f"U00000{index}", expiresAt="2026-01-06T08:00:00Z" if index == 1 else
                                  "2026-01-12T08:00:00Z"))
        self.feed({"type": "expiry", "unitId": "U000004"})
        self.reserve("U000003")
        self.request("POST", "/reservations/R000001/complete")
        self.feed({"type": "demandUnmet", "hospitalId": "H02", "bloodGroup": "O-", "units": 1})
        self.assertEqual(self.request("GET", "/metrics")[1], {
            "simTime": "2026-01-05T20:00:00Z", "unitsAvailable": 3, "expiringIn24h": 1, "wastedToday": 1,
            "shortagesToday": 1, "transfersToday": 1, "wasteRate": 0.25,
        })
        # The next sim day starts the daily counts again; totals and stock carry over.
        self.feed({"type": "clock", "simTime": "2026-01-06T01:00:00Z"})
        self.assertEqual(self.request("GET", "/metrics")[1], {
            "simTime": "2026-01-06T01:00:00Z", "unitsAvailable": 3, "expiringIn24h": 1, "wastedToday": 0,
            "shortagesToday": 0, "transfersToday": 0, "wasteRate": 0.25,
        })

    def transfuseAt(self, simTime: str, unitIds: list[str], hospitalId: str = "H01"):
        self.feed({"type": "clock", "simTime": simTime})
        for unitId in unitIds:
            self.deliver(makeUnit(unitId, hospitalId=hospitalId, collectedAt=simTime))
            self.feed({"type": "transfusion", "unitId": unitId})

    def testRecommendationsMoveSurplusToForecastShortfall(self):
        # H01 used 2 A+ units on each of Mon 5 and Tue 6 Jan, so the engine forecasts 2 a day there.
        self.transfuseAt("2026-01-05T10:00:00Z", ["U000001", "U000002"])
        self.transfuseAt("2026-01-06T10:00:00Z", ["U000003", "U000004"])
        self.feed({"type": "clock", "simTime": "2026-01-07T06:00:00Z"})
        # H03 has no demand and a unit expiring in 36h.
        self.deliver(makeUnit("U000005", hospitalId="H03", collectedAt="2026-01-01T18:00:00Z",
                              expiresAt="2026-01-08T18:00:00Z"))
        status, transfers = self.request("GET", "/recommendations")
        self.assertEqual(status, 200)
        self.assertEqual(len(transfers), 1)
        self.assertEqual({key: transfers[0][key] for key in ("unitId", "fromHospitalId", "toHospitalId",
                                                              "travelMinutes", "hoursToExpiry")},
                         {"unitId": "U000005", "fromHospitalId": "H03", "toHospitalId": "H01",
                          "travelMinutes": 42, "hoursToExpiry": 36.0})
        self.assertEqual(set(transfers[0]), {"unitId", "fromHospitalId", "toHospitalId", "travelMinutes",
                                             "hoursToExpiry", "score", "reason"})
        # A reserved unit is no longer offered.
        self.reserve("U000005", "H01")
        self.assertEqual(self.request("GET", "/recommendations"), (200, []))

    def testRecommendationsEmptyWithoutHistory(self):
        self.deliver(makeUnit("U000001", hospitalId="H03"))
        self.assertEqual(self.request("GET", "/recommendations"), (200, []))

    def testEmergencyRanksCompatibleSourcesElsewhere(self):
        self.feed({"type": "clock", "simTime": "2026-01-05T12:00:00Z"})
        self.deliver(makeUnit("U000001", bloodGroup="O-", hospitalId="H02"))
        self.deliver(makeUnit("U000002", bloodGroup="A-", hospitalId="H03", expiresAt="2026-01-06T12:00:00Z"))
        self.deliver(makeUnit("U000003", bloodGroup="A-", hospitalId="H01"))  # the requester's own stock
        self.deliver(makeUnit("U000004", bloodGroup="A+", hospitalId="H02"))  # RhD-positive: not allowed
        status, sources = self.request("POST", "/emergency", {"hospitalId": "H01", "bloodGroup": "A-", "unitsNeeded": 1})
        self.assertEqual(status, 200)
        self.assertEqual(sources, [
            {"unitId": "U000002", "hospitalId": "H03", "bloodGroup": "A-", "hoursToExpiry": 24.0,
             "travelMinutes": 42, "penalty": 0, "rank": 1},
            {"unitId": "U000001", "hospitalId": "H02", "bloodGroup": "O-", "hoursToExpiry": 164.0,
             "travelMinutes": 27, "penalty": 3, "rank": 2},
        ])
        self.assertEqual(self.request("POST", "/emergency", {"hospitalId": "H99", "bloodGroup": "A-", "unitsNeeded": 1}),
                         (400, {"error": "unknownHospital"}))

    def testEventsNewestFirstWithoutClockTicks(self):
        self.feed({"type": "clock", "simTime": "2026-01-05T09:00:00Z"})
        self.deliver(makeUnit("U000001"))
        self.feed({"type": "clock", "simTime": "2026-01-05T10:00:00Z"})
        self.reserve("U000001")
        status, events = self.request("GET", "/events")
        self.assertEqual(status, 200)
        self.assertEqual([(event["eventId"], event["type"]) for event in events],
                         [("E000004", "reservation"), ("E000002", "delivery")])
        self.assertEqual(events[1], {"eventId": "E000002", "type": "delivery", "unitId": "U000001",
                                     "hospitalId": "H01", "at": "2026-01-05T09:00:00Z",
                                     "detail": "Unit U000001 (A+) delivered to H01"})
        self.assertEqual(len(self.request("GET", "/events?limit=1")[1]), 1)
        self.assertEqual(self.request("GET", "/events?limit=0"), (400, {"error": "invalidRequest"}))

    def testConcurrentReservationsOverHttpGiveExactlyOne201(self):
        self.deliver(makeUnit("U000001"))
        with ThreadPoolExecutor(max_workers=50) as executor:
            statuses = list(executor.map(lambda _: self.reserve("U000001")[0], range(50)))
        self.assertEqual(sorted(statuses), [201] + [409] * 49)
        self.assertEqual(self.query("SELECT count(*) FROM reservations"), [(1,)])


if __name__ == "__main__":
    unittest.main()
