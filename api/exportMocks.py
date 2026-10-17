"""Write web/mock/*.json from the same examples the API stub returns.

Run from the repo root: python -m api.exportMocks
"""

import json
import sys
from pathlib import Path

from api import examples

# Mock file name -> response body of the matching endpoint.
mockFiles = {
    "health.json": {"status": "ok", "arch": "s390x", "dbOk": True},
    "hospitals.json": [examples.exampleHospital],
    "stock.json": [examples.exampleUnit],
    "recommendations.json": [examples.exampleTransfer],
    "reservation.json": examples.exampleReservation,
    "reservationConflict.json": examples.exampleReservationConflict,
    "reservationComplete.json": examples.exampleCompletedReservation,
    "emergency.json": [examples.exampleEmergencySource],
    "metrics.json": examples.exampleMetrics,
    "events.json": [examples.exampleEvent],
    "simulationResults.json": examples.exampleComparison,
    "feedEvents.json": examples.exampleFeedAccepted,
}


def exportMocks(outputDir: Path) -> list[Path]:
    outputDir.mkdir(parents=True, exist_ok=True)
    writtenPaths = []
    for fileName, body in mockFiles.items():
        path = outputDir / fileName
        path.write_text(json.dumps(body, indent=2) + "\n")
        writtenPaths.append(path)
    return writtenPaths


if __name__ == "__main__":
    defaultDir = Path(__file__).resolve().parent.parent / "web" / "mock"
    outputDir = Path(sys.argv[1]) if len(sys.argv) > 1 else defaultDir
    for path in exportMocks(outputDir):
        print(path)
