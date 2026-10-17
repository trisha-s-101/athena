"""Stub API tests. Standard library only (no httpx), so they also run on the Z instance.

Run from the repo root: python -m unittest discover api/tests
"""

import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request

import uvicorn

from api.main import app


def findFreePort() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class StubApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = findFreePort()
        cls.baseUrl = f"http://127.0.0.1:{port}/api"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 10
        while not cls.server.started:
            if time.time() > deadline:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.baseUrl + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def testHealth(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"status", "arch", "dbOk"})

    def testHospitalsHaveStockSummary(self):
        status, body = self.request("GET", "/hospitals")
        self.assertEqual(status, 200)
        self.assertEqual(set(body[0]["stockSummary"]), {"available", "expiringIn24h"})

    def testStockFiltersByHospital(self):
        self.assertEqual(len(self.request("GET", "/stock")[1]), 1)
        self.assertEqual(len(self.request("GET", "/stock?hospitalId=H03")[1]), 1)
        self.assertEqual(self.request("GET", "/stock?hospitalId=H01")[1], [])

    def testReservationAcceptedAndConflict(self):
        status, body = self.request("POST", "/reservations", {"unitId": "U000123", "toHospitalId": "H01"})
        self.assertEqual(status, 201)
        self.assertEqual(body["status"], "accepted")
        status, body = self.request("POST", "/reservations", {"unitId": "U999999", "toHospitalId": "H01"})
        self.assertEqual(status, 409)
        self.assertEqual(body, {"error": "unitNotAvailable"})

    def testCompleteReservation(self):
        status, body = self.request("POST", "/reservations/R000007/complete")
        self.assertEqual(status, 200)
        self.assertEqual((body["reservationId"], body["status"]), ("R000007", "completed"))

    def testEmergency(self):
        status, body = self.request("POST", "/emergency", {"hospitalId": "H05", "bloodGroup": "O-", "unitsNeeded": 2})
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["rank"], 1)

    def testGetEndpoints(self):
        for path in ["/recommendations", "/metrics", "/events?limit=5", "/simulation/results"]:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 200)

    def testFeedAcceptsEveryEventType(self):
        feedEvents = [
            {"type": "delivery", "unit": {"unitId": "U000123", "bloodGroup": "A+",
                                          "collectedAt": "2026-01-05T08:00:00Z",
                                          "expiresAt": "2026-01-12T08:00:00Z",
                                          "hospitalId": "H03", "status": "available"}},
            {"type": "transfusion", "unitId": "U000123"},
            {"type": "expiry", "unitId": "U000123"},
            {"type": "demandUnmet", "hospitalId": "H03", "bloodGroup": "A+", "units": 1},
            {"type": "clock", "simTime": "2026-01-05T14:00:00Z"},
        ]
        for event in feedEvents:
            with self.subTest(type=event["type"]):
                self.assertEqual(self.request("POST", "/feed/events", event), (202, {"accepted": True}))

    def testBadRequestsUseErrorShape(self):
        self.assertEqual(self.request("POST", "/feed/events", {"type": "teleport"}), (400, {"error": "invalidRequest"}))
        self.assertEqual(self.request("POST", "/emergency", {"hospitalId": "H05"}), (400, {"error": "invalidRequest"}))
        self.assertEqual(self.request("GET", "/noSuchEndpoint"), (404, {"error": "notFound"}))


if __name__ == "__main__":
    unittest.main()
