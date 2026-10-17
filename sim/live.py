"""
sim/live.py  --  Live-mode simulator stub (CONTRACT §7).

Usage:
    python -m sim.live --api http://localhost:8000 --speed 60

--speed N means 1 sim-hour passes every (60 / N) real seconds, so
--speed 60 runs at 1 sim-hour per real minute.

At +4h this is a stub: it prints its config and exits cleanly.
At +10h it will load shared/*.json, generate a scenario, then stream
Unit/transfusion/expiry/clock events to POST /api/feed/events at the
right wall-clock cadence.
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Live platelet exchange simulator")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="Base URL of the API server")
    parser.add_argument("--speed", type=float, default=60.0,
                        help="Sim-hours per real minute")
    args = parser.parse_args()

    print(f"[sim.live] STUB: would stream events to {args.api} at {args.speed}x speed")
    print("[sim.live] Real streaming will be implemented at the +10h milestone.")


if __name__ == "__main__":
    main()
