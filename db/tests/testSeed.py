"""Schema and seed tests.

Validation tests always run. Database tests need a throwaway database, because they drop every table:
    TEST_DATABASE_URL=postgresql://... python -m unittest discover db/tests
Never point TEST_DATABASE_URL at the instance's real database.
"""

import copy
import json
import os
import threading
import unittest
from pathlib import Path

from db.seed import SeedError, loadSharedData, seedDatabase, validateHospitals, validateTravelTimes

fixturesDir = Path(__file__).resolve().parent / "fixtures"
testDatabaseUrl = os.environ.get("TEST_DATABASE_URL")

fixtureHospitals = json.loads((fixturesDir / "hospitals.json").read_text())
fixtureTravelTimes = json.loads((fixturesDir / "travelTimes.json").read_text())
fixtureIds = {hospital["hospitalId"] for hospital in fixtureHospitals}

fixtureUnit = ("U000001", "A+", "2026-01-05T08:00:00Z", "2026-01-12T08:00:00Z", "H01", "available")
insertUnitSql = ("INSERT INTO units (unit_id, blood_group, collected_at, expires_at, hospital_id, status) "
                 "VALUES (%s, %s, %s, %s, %s, %s)")
insertReservationSql = ("INSERT INTO reservations (unit_id, from_hospital_id, to_hospital_id, status, created_at) "
                        "VALUES (%s, 'H01', 'H02', %s, '2026-01-05T14:00:00Z') RETURNING reservation_id")


class ValidationTest(unittest.TestCase):
    def testFixturesLoadWithoutWarnings(self):
        hospitals, travelTimes, warnings = loadSharedData(fixturesDir)
        self.assertEqual((len(hospitals), len(travelTimes), warnings), (3, 6, []))

    def testMissingFileNamesTheFile(self):
        with self.assertRaisesRegex(SeedError, "hospitals.json"):
            loadSharedData(fixturesDir / "noSuchFolder")

    def testRejectsBadHospitals(self):
        badHospitals = {
            "extra key": {**fixtureHospitals[0], "beds": 900},
            "bad size": {**fixtureHospitals[0], "sizeCategory": "huge"},
            "string lat": {**fixtureHospitals[0], "lat": "53.46"},
            "string flag": {**fixtureHospitals[0], "hasHaematology": "yes"},
        }
        for label, hospital in badHospitals.items():
            with self.subTest(label), self.assertRaises(SeedError):
                validateHospitals([hospital])
        with self.assertRaisesRegex(SeedError, "Duplicate"):
            validateHospitals([fixtureHospitals[0], fixtureHospitals[0]])

    def testRejectsBadTravelTimes(self):
        route = fixtureTravelTimes[0]
        badRoutes = {
            "unknown hospital": [{**route, "toHospitalId": "H99"}],
            "negative minutes": [{**route, "minutes": -5}],
            "boolean minutes": [{**route, "minutes": True}],
            "duplicate pair": [route, route],
        }
        for label, travelTimes in badRoutes.items():
            with self.subTest(label), self.assertRaises(SeedError):
                validateTravelTimes(travelTimes, fixtureIds)

    def testWarnsAboutMissingPairs(self):
        warnings = validateTravelTimes(fixtureTravelTimes[:-1], fixtureIds)
        self.assertEqual(len(warnings), 1)
        self.assertIn("('H03', 'H02')", warnings[0])


@unittest.skipUnless(testDatabaseUrl, "set TEST_DATABASE_URL to a throwaway database to run")
class DatabaseTest(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.psycopg2 = psycopg2
        self.connection = psycopg2.connect(testDatabaseUrl)
        seedDatabase(self.connection, fixtureHospitals, fixtureTravelTimes, reset=True)

    def tearDown(self):
        self.connection.close()

    def query(self, sql, params=()):
        with self.connection, self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else cursor.rowcount

    def testSeedLoadsFixtures(self):
        self.assertEqual(self.query("SELECT count(*) FROM hospitals"), [(3,)])
        self.assertEqual(self.query("SELECT count(*) FROM travel_times"), [(6,)])
        self.assertEqual(self.query("SELECT minutes FROM travel_times WHERE from_hospital_id = 'H02' "
                                    "AND to_hospital_id = 'H01'"), [(27,)])

    def testReseedUpdatesWithoutDuplicatingOrWiping(self):
        self.query(insertUnitSql, fixtureUnit)
        renamedHospitals = copy.deepcopy(fixtureHospitals)
        renamedHospitals[0]["name"] = "Renamed Hospital"
        seedDatabase(self.connection, renamedHospitals, fixtureTravelTimes)
        self.assertEqual(self.query("SELECT name FROM hospitals WHERE hospital_id = 'H01'"), [("Renamed Hospital",)])
        self.assertEqual(self.query("SELECT count(*) FROM hospitals"), [(3,)])
        self.assertEqual(self.query("SELECT count(*) FROM units"), [(1,)])

    def testResetWipesLiveData(self):
        self.query(insertUnitSql, fixtureUnit)
        seedDatabase(self.connection, fixtureHospitals, fixtureTravelTimes, reset=True)
        self.assertEqual(self.query("SELECT count(*) FROM units"), [(0,)])

    def testFailedSeedChangesNothing(self):
        brokenTravelTimes = [*fixtureTravelTimes, {"fromHospitalId": "H01", "toHospitalId": "H99", "minutes": 5}]
        with self.assertRaises(self.psycopg2.Error):
            seedDatabase(self.connection, [{**fixtureHospitals[0], "name": "Should Roll Back"}], brokenTravelTimes)
        self.assertEqual(self.query("SELECT name FROM hospitals WHERE hospital_id = 'H01'"),
                         [(fixtureHospitals[0]["name"],)])

    def testIdsAreSequentialAndPadded(self):
        self.query(insertUnitSql, fixtureUnit)
        self.assertEqual(self.query(insertReservationSql, ("U000001", "completed")), [("R000001",)])
        self.assertEqual(self.query(insertReservationSql, ("U000001", "accepted")), [("R000002",)])
        eventIds = self.query("INSERT INTO events (type, at) VALUES ('clock', now()), ('clock', now()) "
                              "RETURNING event_id")
        self.assertEqual(eventIds, [("E000001",), ("E000002",)])

    def testOneActiveReservationPerUnit(self):
        self.query(insertUnitSql, fixtureUnit)
        self.query(insertReservationSql, ("U000001", "accepted"))
        with self.assertRaises(self.psycopg2.errors.UniqueViolation):
            self.query(insertReservationSql, ("U000001", "accepted"))

    def testRejectsValuesOutsideTheContract(self):
        badUnits = {
            "blood group": ("U000002", "C+", *fixtureUnit[2:]),
            "status": (*fixtureUnit[:5], "lost"),
            "expiry before collection": ("U000002", "A+", fixtureUnit[3], fixtureUnit[2], "H01", "available"),
            "unknown hospital": ("U000002", "A+", fixtureUnit[2], fixtureUnit[3], "H99", "available"),
        }
        for label, unit in badUnits.items():
            with self.subTest(label), self.assertRaises(self.psycopg2.IntegrityError):
                self.query(insertUnitSql, unit)

    def testConditionalUpdateLetsExactlyOneReserverWin(self):
        # The contract section 8 pattern the API will use, raced from 20 connections.
        self.query(insertUnitSql, fixtureUnit)
        results, startLine = [], threading.Barrier(20)

        def reserve():
            connection = self.psycopg2.connect(testDatabaseUrl)
            try:
                startLine.wait()
                with connection, connection.cursor() as cursor:
                    cursor.execute("UPDATE units SET status = 'reserved' "
                                   "WHERE unit_id = 'U000001' AND status = 'available'")
                    results.append(cursor.rowcount)
            finally:
                connection.close()

        threads = [threading.Thread(target=reserve) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [0] * 19 + [1])


if __name__ == "__main__":
    unittest.main()
