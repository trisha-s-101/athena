"""Example payloads from contract sections 5 and 8.

The API stub returns these, and exportMocks.py writes them to web/mock/,
so the stub and the dashboard mocks can never drift apart.
Where the contract shows "...", a concrete value in the right format is used.
"""

exampleHospital = {
    "hospitalId": "H01",
    "name": "Manchester Royal Infirmary",
    "lat": 53.4627,
    "lng": -2.2265,
    "sizeCategory": "large",
    "hasHaematology": True,
    "stockSummary": {"available": 12, "expiringIn24h": 3},
}

exampleUnit = {
    "unitId": "U000123",
    "bloodGroup": "A+",
    "collectedAt": "2026-01-05T08:00:00Z",
    "expiresAt": "2026-01-12T08:00:00Z",
    "hospitalId": "H03",
    "status": "available",
}

exampleTransfer = {
    "unitId": "U000123",
    "fromHospitalId": "H03",
    "toHospitalId": "H01",
    "travelMinutes": 25,
    "hoursToExpiry": 30.5,
    "score": 0.82,
    "reason": "Expires in 30h at H03 (forecast use 0.2); H01 forecast use 2.4",
}

exampleReservation = {
    "reservationId": "R000001",
    "unitId": "U000123",
    "fromHospitalId": "H03",
    "toHospitalId": "H01",
    "status": "accepted",
    "createdAt": "2026-01-05T14:00:00Z",
}

exampleCompletedReservation = {**exampleReservation, "status": "completed"}

exampleReservationConflict = {"error": "unitNotAvailable"}

exampleEmergencySource = {
    "unitId": "U000456",
    "hospitalId": "H02",
    "bloodGroup": "O-",
    "hoursToExpiry": 50.0,
    "travelMinutes": 18,
    "penalty": 0,
    "rank": 1,
}

exampleMetrics = {
    "simTime": "2026-01-05T14:00:00Z",
    "unitsAvailable": 140,
    "expiringIn24h": 18,
    "wastedToday": 2,
    "shortagesToday": 0,
    "transfersToday": 6,
    "wasteRate": 0.031,
}

exampleEvent = {
    "eventId": "E000001",
    "type": "delivery",
    "unitId": "U000123",
    "hospitalId": "H03",
    "at": "2026-01-05T08:00:00Z",
    "detail": "Unit U000123 (A+) delivered to H03",
}

exampleSimResult = {
    "policy": "exchange",
    "days": 90,
    "unitsDelivered": 21000,
    "unitsTransfused": 20400,
    "unitsWasted": 610,
    "wasteRate": 0.029,
    "shortageEvents": 4,
    "transfers": 820,
    "daily": [{"date": "2026-01-05", "wasted": 7, "shortages": 0, "transfers": 9}],
}

# The contract only gives an exchange SimResult, so noSharing reuses its numbers.
exampleComparison = {
    "generatedAt": "2026-01-05T00:00:00Z",
    "seed": 42,
    "noSharing": {**exampleSimResult, "policy": "noSharing"},
    "exchange": exampleSimResult,
}

exampleFeedAccepted = {"accepted": True}
