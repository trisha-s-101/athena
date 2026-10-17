"""Tests for endpoints that still return example JSON, and for behavior with no database.

Run from the repo root: python -m unittest discover api/tests
"""

import os
import unittest

from api.database import closePool
from api.tests.server import ServerTestCase


class StubApiTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        # Run with no database, even on the instance where DATABASE_URL is normally set.
        cls.savedDatabaseUrl = os.environ.pop("DATABASE_URL", None)
        closePool()
        cls.startServer()

    @classmethod
    def tearDownClass(cls):
        cls.stopServer()
        if cls.savedDatabaseUrl is not None:
            os.environ["DATABASE_URL"] = cls.savedDatabaseUrl

    def testHealthReportsDatabaseDown(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"status", "arch", "dbOk"})
        self.assertIs(body["dbOk"], False)

    def testDatabaseEndpointsReturn503WithoutDatabase(self):
        for method, path, body in [("GET", "/hospitals", None), ("GET", "/stock", None), ("GET", "/metrics", None),
                                   ("GET", "/recommendations", None), ("GET", "/events?limit=5", None),
                                   ("POST", "/emergency", {"hospitalId": "H05", "bloodGroup": "O-", "unitsNeeded": 2}),
                                   ("POST", "/reservations", {"unitId": "U000123", "toHospitalId": "H01"}),
                                   ("POST", "/feed/events", {"type": "clock", "simTime": "2026-01-05T14:00:00Z"})]:
            with self.subTest(path=path):
                self.assertEqual(self.request(method, path, body), (503, {"error": "databaseUnavailable"}))

    def testSimulationResultsNeedNoDatabase(self):
        status, body = self.request("GET", "/simulation/results")
        self.assertEqual(status, 200)
        self.assertIn("generatedAt", body)

    def testBadRequestsUseErrorShape(self):
        self.assertEqual(self.request("POST", "/feed/events", {"type": "teleport"}), (400, {"error": "invalidRequest"}))
        self.assertEqual(self.request("POST", "/emergency", {"hospitalId": "H05"}), (400, {"error": "invalidRequest"}))
        self.assertEqual(self.request("GET", "/noSuchEndpoint"), (404, {"error": "notFound"}))


if __name__ == "__main__":
    unittest.main()
