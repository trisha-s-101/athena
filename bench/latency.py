"""Throughput and p50/p99 latency for the main API endpoints (CONTRACT.md section 12 item 5).

Results go to the latency section of results/benchmark.json.

Run from the repo root while the app is running:
    python -m bench.latency --api http://localhost:8000 --requests 500 --concurrency 20

The write benchmarks add units and reservations to the database, so wipe it afterwards
(INSTANCE_SETUP Part 8D).
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.benchCommon import ApiClient, defaultOutputPath, fetchArch, nowIso, percentile, plusDays, writeSection

bloodGroups = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]


def measure(client: ApiClient, name: str, requests: list[tuple], concurrency: int, okStatus: int) -> dict:
    """Sends (method, path, body) requests from `concurrency` threads; a reply other than okStatus counts as an error."""
    def send(request):
        status, _, elapsedMs = client.request(*request)
        return status, elapsedMs

    startedAt = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(send, requests))
    durationSeconds = time.perf_counter() - startedAt
    latencies = [elapsedMs for _, elapsedMs in results]
    return {
        "name": name, "requests": len(results),
        "errors": sum(1 for status, _ in results if status != okStatus),
        "throughputPerSecond": round(len(results) / durationSeconds, 1),
        "p50Ms": round(percentile(latencies, 0.50), 1), "p99Ms": round(percentile(latencies, 0.99), 1),
    }


def runLatency(apiBase: str, requestsPerEndpoint: int, concurrency: int) -> tuple[dict, str]:
    client = ApiClient(apiBase)
    arch = fetchArch(client)
    hospitalIds = [hospital["hospitalId"] for hospital in client.request("GET", "/api/hospitals")[1]]
    if len(hospitalIds) < 2:
        raise SystemExit("Need at least two hospitals: run python -m db.seed first.")
    simTime = client.request("GET", "/api/metrics")[1]["simTime"]
    runId = f"{int(time.time() * 1000) % 10**8:08d}"
    n = requestsPerEndpoint

    # Writes first: the deliveries create the units that the reservations then claim, one each.
    units = [{"unitId": f"UL{runId}{index:05d}", "bloodGroup": bloodGroups[index % len(bloodGroups)],
              "collectedAt": simTime, "expiresAt": plusDays(simTime, 7),
              "hospitalId": hospitalIds[index % len(hospitalIds)], "status": "available"} for index in range(n)]
    endpoints = [measure(client, "POST /api/feed/events (delivery)",
                         [("POST", "/api/feed/events", {"type": "delivery", "unit": unit}) for unit in units],
                         concurrency, 202)]
    destination = {hospitalId: hospitalIds[(index + 1) % len(hospitalIds)] for index, hospitalId in enumerate(hospitalIds)}
    endpoints.append(measure(client, "POST /api/reservations",
                             [("POST", "/api/reservations", {"unitId": unit["unitId"],
                                                             "toHospitalId": destination[unit["hospitalId"]]})
                              for unit in units], concurrency, 201))

    emergencyBody = {"hospitalId": hospitalIds[0], "bloodGroup": "O-", "unitsNeeded": 2}
    for name, method, path, body in [
        ("GET /api/hospitals", "GET", "/api/hospitals", None),
        ("GET /api/stock", "GET", "/api/stock", None),
        ("GET /api/metrics", "GET", "/api/metrics", None),
        ("GET /api/events", "GET", "/api/events?limit=50", None),
        ("GET /api/recommendations", "GET", "/api/recommendations", None),
        ("POST /api/emergency", "POST", "/api/emergency", emergencyBody),
    ]:
        endpoints.append(measure(client, name, [(method, path, body)] * n, concurrency, 200))

    client.closeAll()
    section = {"generatedAt": nowIso(), "concurrency": concurrency, "requestsPerEndpoint": n, "endpoints": endpoints}
    return section, arch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure API throughput and latency")
    parser.add_argument("--api", default="http://localhost:8000", help="Base URL of the API")
    parser.add_argument("--requests", type=int, default=500, help="Requests per endpoint")
    parser.add_argument("--concurrency", type=int, default=20, help="Requests in flight at once")
    parser.add_argument("--output", type=Path, default=defaultOutputPath, help="benchmark.json to update")
    args = parser.parse_args(argv)
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be at least 1")

    section, arch = runLatency(args.api, args.requests, args.concurrency)
    writeSection(args.output, "latency", section, arch)
    print(f"[bench.latency] arch {arch}, {args.requests} requests per endpoint, {args.concurrency} at once")
    for endpoint in section["endpoints"]:
        print(f"[bench.latency] {endpoint['name']:<34} {endpoint['throughputPerSecond']:>8} req/s  "
              f"p50 {endpoint['p50Ms']:>7} ms  p99 {endpoint['p99Ms']:>7} ms  errors {endpoint['errors']}")
    print(f"[bench.latency] Wrote {args.output}")
    return 0 if all(endpoint["errors"] == 0 for endpoint in section["endpoints"]) else 1


if __name__ == "__main__":
    sys.exit(main())
