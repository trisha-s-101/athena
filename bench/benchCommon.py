"""Shared helpers for the benchmarks. Standard library only, and they talk to the API over HTTP only."""

import http.client
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

defaultOutputPath = Path(__file__).resolve().parent.parent / "results" / "benchmark.json"


class ApiClient:
    """One keep-alive connection per thread, so timings measure the API rather than TCP setup."""

    def __init__(self, apiBase: str, timeoutSeconds: float = 30):
        parts = urlsplit(apiBase)
        self.host = parts.hostname or "localhost"
        self.port = parts.port or 80
        self.timeoutSeconds = timeoutSeconds
        self._local = threading.local()
        self._allConnections = []  # Worker threads can exit before closing theirs, so closeAll tidies up.
        self._allConnectionsLock = threading.Lock()

    def _connection(self) -> http.client.HTTPConnection:
        if getattr(self._local, "connection", None) is None:
            self._local.connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeoutSeconds)
            with self._allConnectionsLock:
                self._allConnections.append(self._local.connection)
        return self._local.connection

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, object, float]:
        """Returns (status, parsed JSON body, elapsed milliseconds). Status 0 means the request never got an answer."""
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        for attempt in range(2):  # Retry once on a dropped keep-alive connection.
            connection = self._connection()
            startedAt = time.perf_counter()
            try:
                connection.request(method, path, body=payload, headers=headers)
                response = connection.getresponse()
                data = response.read()
                elapsedMs = (time.perf_counter() - startedAt) * 1000
                return response.status, json.loads(data) if data else None, elapsedMs
            except (http.client.HTTPException, OSError):
                connection.close()
                self._local.connection = None
                if attempt == 1:
                    return 0, None, (time.perf_counter() - startedAt) * 1000
        return 0, None, 0.0

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def closeAll(self) -> None:
        with self._allConnectionsLock:
            for connection in self._allConnections:
                connection.close()
            self._allConnections.clear()
        self._local = threading.local()


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, e.g. fraction 0.99 for p99. Empty input gives 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def nowIso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plusDays(isoTime: str, days: float) -> str:
    parsed = datetime.fromisoformat(isoTime.replace("Z", "+00:00"))
    return (parsed + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetchArch(client: ApiClient) -> str:
    status, body, _ = client.request("GET", "/api/health")
    if status != 200:
        raise SystemExit(f"API health check failed with status {status}. Is the app running?")
    if not body.get("dbOk"):
        raise SystemExit("The API reports dbOk false. Fix the database connection first (INSTANCE_SETUP Part 8).")
    return body["arch"]


def writeSection(outputPath: Path, sectionName: str, section: dict, arch: str) -> None:
    """Replace one section of benchmark.json, keeping the other script's results."""
    try:
        results = json.loads(outputPath.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        results = {}
    results.update({"generatedAt": nowIso(), "arch": arch, sectionName: section})
    outputPath.parent.mkdir(parents=True, exist_ok=True)
    outputPath.write_text(json.dumps(results, indent=2) + "\n")
