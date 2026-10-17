"""Tests for sim/live.py -- event stream shape and the HTTP path (CONTRACT §8)."""

import json
import sys
import pathlib
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from sim.generate import generateScenario
from sim.live import streamScenario
from sim.simulate import FEED_EVENT_TYPES, runSimulation

ASSUMPTIONS = {
    "simDays": 2,
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
FAST = 1_000_000  # speed multiplier high enough that pacing never sleeps


def _scenario():
    return generateScenario(ASSUMPTIONS, HOSPITALS, SEED)


class _CollectingHandler(BaseHTTPRequestHandler):
    """Stands in for Neil's API: records posted events, answers /api/health."""

    received: Counter = Counter()
    payloads: list = []

    def log_message(self, *args):
        pass

    def _respond(self, status: int, body: dict):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/api/health":
            self._respond(200, {"status": "ok", "arch": "s390x", "dbOk": True})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/feed/events":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        event = json.loads(self.rfile.read(length))
        type(self).received[event["type"]] += 1
        type(self).payloads.append(event)
        self._respond(202, {"accepted": True})


class TestEventStream(unittest.TestCase):
    """Dry-run checks on what streamScenario emits."""

    def test_only_contract_event_types(self):
        counts = streamScenario(_scenario(), "http://unused", FAST, dryRun=True)
        self.assertTrue(counts, "expected at least one event")
        for eventType in counts:
            self.assertIn(eventType, FEED_EVENT_TYPES,
                          f"{eventType} is not a CONTRACT §8 feed event")

    def test_internal_markers_not_emitted(self):
        counts = streamScenario(_scenario(), "http://unused", FAST, dryRun=True)
        self.assertNotIn("transfer", counts)
        self.assertNotIn("dayEnd", counts)

    def test_clock_event_per_six_hour_step(self):
        counts = streamScenario(_scenario(), "http://unused", FAST, dryRun=True)
        self.assertEqual(counts["clock"], ASSUMPTIONS["simDays"] * 4)

    def test_counts_match_sim_result(self):
        """The live stream and the offline SimResult must describe the same run."""
        scenario = _scenario()
        counts = streamScenario(scenario, "http://unused", FAST,
                                policyName="exchange", dryRun=True)
        result = runSimulation(scenario, "exchange", SEED)
        # A short scenario can legitimately have zero of a given event type.
        self.assertEqual(counts.get("delivery", 0), result["unitsDelivered"])
        self.assertEqual(counts.get("transfusion", 0), result["unitsTransfused"])
        self.assertEqual(counts.get("expiry", 0), result["unitsWasted"])

    def test_no_sharing_policy_streams(self):
        counts = streamScenario(_scenario(), "http://unused", FAST,
                                policyName="noSharing", dryRun=True)
        self.assertGreater(counts["delivery"], 0)


class TestHttpPosting(unittest.TestCase):
    """streamScenario against a stand-in API, checking the wire payloads."""

    @classmethod
    def setUpClass(cls):
        _CollectingHandler.received = Counter()
        _CollectingHandler.payloads = []
        cls.server = HTTPServer(("127.0.0.1", 0), _CollectingHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        apiBase = f"http://127.0.0.1:{cls.port}"
        cls.counts = streamScenario(_scenario(), apiBase, FAST, dryRun=False)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_every_event_reached_the_api(self):
        self.assertEqual(dict(_CollectingHandler.received), dict(self.counts))

    def test_delivery_payload_is_contract_unit(self):
        unitKeys = {"unitId", "bloodGroup", "collectedAt", "expiresAt", "hospitalId", "status"}
        deliveries = [e for e in _CollectingHandler.payloads if e["type"] == "delivery"]
        self.assertGreater(len(deliveries), 0)
        for event in deliveries:
            self.assertEqual(set(event.keys()), {"type", "unit"})
            self.assertEqual(set(event["unit"].keys()), unitKeys,
                             "delivery unit must match CONTRACT §5 (no deliveredAt)")

    def test_simple_event_payloads(self):
        expectedKeys = {
            "clock": {"type", "simTime"},
            "transfusion": {"type", "unitId"},
            "expiry": {"type", "unitId"},
            "demandUnmet": {"type", "hospitalId", "bloodGroup", "units"},
        }
        seen = set()
        for event in _CollectingHandler.payloads:
            if event["type"] in expectedKeys:
                self.assertEqual(set(event.keys()), expectedKeys[event["type"]],
                                 f"{event['type']} payload does not match CONTRACT §8")
                seen.add(event["type"])
        self.assertIn("clock", seen)
        self.assertIn("transfusion", seen)

    def test_unreachable_api_does_not_crash(self):
        """A dead API is reported, not raised, so a demo keeps running."""
        counts = streamScenario(_scenario(), f"http://127.0.0.1:{self.port + 1}",
                                FAST, dryRun=False)
        self.assertGreater(sum(counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
