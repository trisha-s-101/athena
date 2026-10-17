"""
sim/live.py  --  Live-mode simulator (CONTRACT §7).

Usage:
    python -m sim.live --api http://localhost:8000 --speed 60

Generates a scenario, runs it through sim.simulate.simulateEvents, and POSTs
each CONTRACT §8 feed event to {api}/api/feed/events at a wall-clock cadence.

--speed is the time multiplier: sim time runs that many times faster than real
time, so --speed 60 gives 1 sim hour per real minute (the contract's example).

This is the only part of sim/ that talks to the API, and it does so over HTTP
only (golden rule 3). Offline experiments call engine/ directly instead.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from sim.generate import generateScenario
from sim.run import _DEFAULT_ASSUMPTIONS, _DEFAULT_HOSPITALS, _loadJson
from sim.simulate import FEED_EVENT_TYPES, _STEP_HOURS, simulateEvents

_SIM_SECONDS_PER_STEP = _STEP_HOURS * 3600
_HTTP_TIMEOUT_SECONDS = 5


def _postEvent(apiBase: str, event: dict) -> None:
    """POST one feed event. Raises urllib.error.URLError if the API is unreachable."""
    body = json.dumps(event).encode("utf-8")
    request = urllib.request.Request(
        f"{apiBase}/api/feed/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        response.read()


def _checkHealth(apiBase: str) -> None:
    """Fail fast with a readable message if the API is not up yet."""
    try:
        with urllib.request.urlopen(f"{apiBase}/api/health", timeout=_HTTP_TIMEOUT_SECONDS) as response:
            print(f"[sim.live] API healthy: {response.read().decode('utf-8').strip()}")
    except (urllib.error.URLError, OSError) as err:
        print(f"[sim.live] Cannot reach {apiBase}/api/health: {err}", file=sys.stderr)
        print("[sim.live] Start the API first, or pass --dryRun to stream without posting.",
              file=sys.stderr)
        raise SystemExit(1)


def streamScenario(scenario: dict, apiBase: str, speed: float,
                   policyName: str = "exchange", dryRun: bool = False) -> dict:
    """
    Stream one scenario's feed events to the API in sim-clock order.
    Returns counts per event type.
    """
    counts: dict[str, int] = {}
    failures = 0
    startedAt = time.monotonic()
    stepsSeen = 0

    for event in simulateEvents(scenario, policyName, seed=0):
        if event["type"] not in FEED_EVENT_TYPES:
            continue  # sim-internal "transfer" / "dayEnd" markers

        if event["type"] == "clock":
            # Hold the sim clock to wall time before emitting this step's events.
            stepsSeen += 1
            targetElapsed = (stepsSeen - 1) * _SIM_SECONDS_PER_STEP / speed
            behind = targetElapsed - (time.monotonic() - startedAt)
            if behind > 0:
                time.sleep(behind)
            print(f"[sim.live] {event['simTime']}  events so far: {sum(counts.values())}")

        counts[event["type"]] = counts.get(event["type"], 0) + 1

        if dryRun:
            continue
        try:
            _postEvent(apiBase, event)
        except (urllib.error.URLError, OSError) as err:
            failures += 1
            if failures == 1:
                print(f"[sim.live] POST failed ({err}); continuing", file=sys.stderr)

    if failures:
        print(f"[sim.live] {failures} event(s) failed to post", file=sys.stderr)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Live platelet exchange simulator")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="Base URL of the API server")
    parser.add_argument("--speed", type=float, default=60.0,
                        help="Time multiplier; 60 = 1 sim hour per real minute")
    parser.add_argument("--seed", type=int, default=42,
                        help="Scenario seed")
    parser.add_argument("--days", type=int, default=None,
                        help="Override simDays from assumptions.json")
    parser.add_argument("--policy", default="exchange", choices=("noSharing", "exchange"),
                        help="Policy to run live")
    parser.add_argument("--dryRun", action="store_true",
                        help="Print events without posting them")
    args = parser.parse_args()

    if args.speed <= 0:
        parser.error("--speed must be greater than 0")

    assumptions = dict(_loadJson("shared/assumptions.json", _DEFAULT_ASSUMPTIONS))
    hospitals = _loadJson("shared/hospitals.json", _DEFAULT_HOSPITALS)
    if args.days is not None:
        assumptions["simDays"] = args.days

    if not args.dryRun:
        _checkHealth(args.api)

    print(f"[sim.live] Streaming {assumptions['simDays']} days of '{args.policy}' "
          f"at {args.speed}x to {args.api}")
    scenario = generateScenario(assumptions, hospitals, args.seed)
    counts = streamScenario(scenario, args.api, args.speed,
                            policyName=args.policy, dryRun=args.dryRun)

    print("[sim.live] Done. Events sent:")
    for eventType in sorted(counts):
        print(f"[sim.live]   {eventType}: {counts[eventType]}")


if __name__ == "__main__":
    main()
