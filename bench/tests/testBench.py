"""Benchmark tests. The race and latency runs need a throwaway database, because they write to it:
    TEST_DATABASE_URL=postgresql://... python -m unittest discover bench/tests
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from api.database import closePool
from api.tests.server import ServerTestCase
from bench.benchCommon import percentile, writeSection
from bench.latency import runLatency
from bench.reserveRace import runRace
from db.seed import loadSharedData, seedDatabase

testDatabaseUrl = os.environ.get("TEST_DATABASE_URL")
fixturesDir = Path(__file__).resolve().parents[2] / "db" / "tests" / "fixtures"


class HelperTest(unittest.TestCase):
    def testPercentileIsNearestRank(self):
        values = [float(value) for value in range(1, 101)]
        self.assertEqual((percentile(values, 0.50), percentile(values, 0.99), percentile(values, 1.0)),
                         (50.0, 99.0, 100.0))
        self.assertEqual(percentile([7.0], 0.99), 7.0)
        self.assertEqual(percentile([], 0.5), 0.0)

    def testWriteSectionKeepsTheOtherSection(self):
        with tempfile.TemporaryDirectory() as tempDir:
            outputPath = Path(tempDir) / "results" / "benchmark.json"
            writeSection(outputPath, "reserveRace", {"passed": True}, "s390x")
            writeSection(outputPath, "latency", {"concurrency": 20}, "s390x")
            results = json.loads(outputPath.read_text())
            self.assertEqual(results["reserveRace"], {"passed": True})
            self.assertEqual(results["latency"], {"concurrency": 20})
            self.assertEqual(results["arch"], "s390x")


@unittest.skipUnless(testDatabaseUrl, "set TEST_DATABASE_URL to a throwaway database to run")
class BenchAgainstApiTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.savedDatabaseUrl = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = testDatabaseUrl
        closePool()
        hospitals, travelTimes, _ = loadSharedData(fixturesDir)
        connection = psycopg2.connect(testDatabaseUrl)
        try:
            seedDatabase(connection, hospitals, travelTimes, reset=True)
        finally:
            connection.close()
        cls.startServer()
        cls.apiBase = cls.baseUrl.removesuffix("/api")

    @classmethod
    def tearDownClass(cls):
        cls.stopServer()
        closePool()
        if cls.savedDatabaseUrl is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.savedDatabaseUrl

    def testRaceGivesExactlyOneReservation(self):
        section, arch = runRace(self.apiBase, attempts=200)
        self.assertEqual((section["accepted"], section["conflicts"], section["otherErrors"]), (1, 199, 0))
        self.assertTrue(section["passed"])
        self.assertTrue(arch)

    def testLatencyCoversEveryEndpointWithoutErrors(self):
        section, _ = runLatency(self.apiBase, requestsPerEndpoint=30, concurrency=5)
        self.assertEqual(len(section["endpoints"]), 8)
        for endpoint in section["endpoints"]:
            with self.subTest(endpoint=endpoint["name"]):
                self.assertEqual((endpoint["requests"], endpoint["errors"]), (30, 0))
                self.assertGreater(endpoint["throughputPerSecond"], 0)


if __name__ == "__main__":
    unittest.main()
