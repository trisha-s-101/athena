"""Race many concurrent reservations for one unit (CONTRACT.md section 8 correctness rule, section 12 item 5).

Exactly one request must get 201 and every other one 409. Results go to the reserveRace section
of results/benchmark.json.

Run from the repo root while the app is running:
    python -m bench.reserveRace --api http://localhost:8000 --attempts 1000

It adds one unit and one reservation to the database, so wipe it afterwards (INSTANCE_SETUP Part 8D).
"""

import argparse
import sys
import threading
import time
from pathlib import Path

from bench.benchCommon import ApiClient, defaultOutputPath, fetchArch, nowIso, percentile, plusDays, writeSection


def deliverRaceUnit(client: ApiClient) -> tuple[str, str, str]:
    """Creates a fresh available unit and returns (unitId, fromHospitalId, toHospitalId)."""
    status, hospitals, _ = client.request("GET", "/api/hospitals")
    if status != 200 or len(hospitals) < 2:
        raise SystemExit("Need at least two hospitals: run python -m db.seed first.")
    fromHospitalId, toHospitalId = hospitals[0]["hospitalId"], hospitals[1]["hospitalId"]
    simTime = client.request("GET", "/api/metrics")[1]["simTime"]
    for attempt in range(20):
        unitId = f"UR{int(time.time() * 1000) % 10**9:09d}{attempt}"
        unit = {"unitId": unitId, "bloodGroup": "O-", "collectedAt": simTime,
                "expiresAt": plusDays(simTime, 7), "hospitalId": fromHospitalId, "status": "available"}
        status, body, _ = client.request("POST", "/api/feed/events", {"type": "delivery", "unit": unit})
        if status == 202:
            return unitId, fromHospitalId, toHospitalId
        if status != 409:
            raise SystemExit(f"Could not create the race unit: {status} {body}")
    raise SystemExit("Could not find a free unit ID for the race unit")


def runRace(apiBase: str, attempts: int) -> tuple[dict, str]:
    setupClient = ApiClient(apiBase)
    arch = fetchArch(setupClient)
    unitId, fromHospitalId, toHospitalId = deliverRaceUnit(setupClient)
    setupClient.closeAll()

    client = ApiClient(apiBase, timeoutSeconds=120)
    statuses, latencies = [], []
    resultsLock = threading.Lock()
    # Every thread connects first, then all fire together when the barrier opens.
    startLine = threading.Barrier(attempts + 1)

    def reserve():
        client.request("GET", "/api/health")  # Opens this thread's connection before the race.
        startLine.wait()
        status, _, elapsedMs = client.request("POST", "/api/reservations",
                                              {"unitId": unitId, "toHospitalId": toHospitalId})
        with resultsLock:
            statuses.append(status)
            latencies.append(elapsedMs)
        client.close()

    threads = [threading.Thread(target=reserve) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    startLine.wait()
    startedAt = time.perf_counter()
    for thread in threads:
        thread.join()
    durationSeconds = time.perf_counter() - startedAt
    client.closeAll()

    accepted = statuses.count(201)
    conflicts = statuses.count(409)
    section = {
        "generatedAt": nowIso(), "attempts": attempts, "accepted": accepted, "conflicts": conflicts,
        "otherErrors": attempts - accepted - conflicts,
        "passed": accepted == 1 and conflicts == attempts - 1,
        "durationSeconds": round(durationSeconds, 3),
        "p50Ms": round(percentile(latencies, 0.50), 1), "p99Ms": round(percentile(latencies, 0.99), 1),
    }
    return section, arch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Race concurrent reservations for one unit")
    parser.add_argument("--api", default="http://localhost:8000", help="Base URL of the API")
    parser.add_argument("--attempts", type=int, default=1000, help="Concurrent reservation requests")
    parser.add_argument("--output", type=Path, default=defaultOutputPath, help="benchmark.json to update")
    args = parser.parse_args(argv)
    if args.attempts < 2:
        parser.error("--attempts must be at least 2")

    section, arch = runRace(args.api, args.attempts)
    writeSection(args.output, "reserveRace", section, arch)
    print(f"[bench.reserveRace] arch {arch}: {section['attempts']} concurrent reservations -> "
          f"{section['accepted']} accepted, {section['conflicts']} conflicts, {section['otherErrors']} other")
    print(f"[bench.reserveRace] {'PASSED' if section['passed'] else 'FAILED'} in {section['durationSeconds']}s "
          f"(p50 {section['p50Ms']} ms, p99 {section['p99Ms']} ms). Wrote {args.output}")
    return 0 if section["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
