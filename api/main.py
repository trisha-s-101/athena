"""Platelet exchange HTTP API (CONTRACT.md section 8).

Real (Postgres): /health, /hospitals, /stock, /feed/events, /reservations, /reservations/{id}/complete.
Still stubs returning the contract's example JSON: /recommendations, /emergency, /metrics, /events.
/simulation/results serves results/comparison.json when it exists.

Run from the repo root with DATABASE_URL set: uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

import json
import platform
from pathlib import Path

import psycopg2
from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import examples
from api.database import DatabaseUnavailable, currentSimTime, isDatabaseOk, toIsoTime, transaction
from api.models import EmergencyRequest, FeedEvent, ReservationRequest

repoRoot = Path(__file__).resolve().parent.parent
webDir = repoRoot / "web"
comparisonPath = repoRoot / "results" / "comparison.json"

httpErrorCodes = {404: "notFound", 405: "methodNotAllowed"}
activeStatuses = ("available", "reserved", "inTransit")

unitColumns = "unit_id, blood_group, collected_at, expires_at, hospital_id, status"
reservationColumns = "reservation_id, unit_id, from_hospital_id, to_hospital_id, status, created_at"


class ApiError(Exception):
    """Raise to return {"error": code} with a 4xx status."""

    def __init__(self, statusCode: int, code: str):
        self.statusCode = statusCode
        self.code = code


app = FastAPI(title="Platelet Exchange API")
router = APIRouter(prefix="/api")


def errorResponse(statusCode: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=statusCode, content={"error": code})


@app.exception_handler(ApiError)
async def onApiError(request: Request, exc: ApiError):
    return errorResponse(exc.statusCode, exc.code)


@app.exception_handler(RequestValidationError)
async def onValidationError(request: Request, exc: RequestValidationError):
    return errorResponse(400, "invalidRequest")


# Postgres rejected a value the request models let through, such as an unparseable time.
@app.exception_handler(psycopg2.DataError)
@app.exception_handler(psycopg2.errors.CheckViolation)
async def onBadValue(request: Request, exc: psycopg2.Error):
    return errorResponse(400, "invalidRequest")


@app.exception_handler(DatabaseUnavailable)
@app.exception_handler(psycopg2.OperationalError)
async def onDatabaseDown(request: Request, exc: Exception):
    return errorResponse(503, "databaseUnavailable")


@app.exception_handler(StarletteHTTPException)
async def onHttpError(request: Request, exc: StarletteHTTPException):
    return errorResponse(exc.status_code, httpErrorCodes.get(exc.status_code, "httpError"))


def unitFromRow(row) -> dict:
    unitId, bloodGroup, collectedAt, expiresAt, hospitalId, status = row
    return {"unitId": unitId, "bloodGroup": bloodGroup, "collectedAt": toIsoTime(collectedAt),
            "expiresAt": toIsoTime(expiresAt), "hospitalId": hospitalId, "status": status}


def reservationFromRow(row) -> dict:
    reservationId, unitId, fromHospitalId, toHospitalId, status, createdAt = row
    return {"reservationId": reservationId, "unitId": unitId, "fromHospitalId": fromHospitalId,
            "toHospitalId": toHospitalId, "status": status, "createdAt": toIsoTime(createdAt)}


def logEvent(cursor, eventType: str, at: str, detail: str, unitId=None, hospitalId=None,
             bloodGroup=None, units=None) -> None:
    cursor.execute(
        "INSERT INTO events (type, unit_id, hospital_id, blood_group, units, at, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (eventType, unitId, hospitalId, bloodGroup, units, at, detail),
    )


@router.get("/health")
def getHealth():
    return {"status": "ok", "arch": platform.machine(), "dbOk": isDatabaseOk()}


@router.get("/hospitals")
def getHospitals():
    with transaction() as cursor:
        simTime = currentSimTime(cursor)
        cursor.execute(
            """
            SELECT h.hospital_id, h.name, h.lat, h.lng, h.size_category, h.has_haematology,
                   count(u.unit_id),
                   count(u.unit_id) FILTER (WHERE u.expires_at < %s::timestamptz + interval '24 hours')
            FROM hospitals h
            LEFT JOIN units u ON u.hospital_id = h.hospital_id AND u.status = 'available'
            GROUP BY h.hospital_id
            ORDER BY h.hospital_id
            """,
            (simTime,),
        )
        rows = cursor.fetchall()
    return [
        {"hospitalId": hospitalId, "name": name, "lat": lat, "lng": lng, "sizeCategory": sizeCategory,
         "hasHaematology": hasHaematology, "stockSummary": {"available": available, "expiringIn24h": expiring}}
        for hospitalId, name, lat, lng, sizeCategory, hasHaematology, available, expiring in rows
    ]


@router.get("/stock")
def getStock(hospitalId: str | None = None):
    with transaction() as cursor:
        cursor.execute(
            f"SELECT {unitColumns} FROM units "
            "WHERE status = ANY(%s) AND (%s::text IS NULL OR hospital_id = %s) "
            "ORDER BY expires_at, unit_id",
            (list(activeStatuses), hospitalId, hospitalId),
        )
        return [unitFromRow(row) for row in cursor.fetchall()]


@router.get("/recommendations")
def getRecommendations():
    return [examples.exampleTransfer]


@router.post("/reservations", status_code=201)
def createReservation(request: ReservationRequest):
    with transaction() as cursor:
        # Contract section 8: one conditional update decides the race. Zero rows means 409.
        cursor.execute(
            "UPDATE units SET status = 'reserved' WHERE unit_id = %s AND status = 'available' "
            "RETURNING hospital_id",
            (request.unitId,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ApiError(409, "unitNotAvailable")
        fromHospitalId = row[0]
        if request.toHospitalId == fromHospitalId:
            raise ApiError(400, "sameHospital")
        simTime = currentSimTime(cursor)
        try:
            cursor.execute(
                "INSERT INTO reservations (unit_id, from_hospital_id, to_hospital_id, status, created_at) "
                f"VALUES (%s, %s, %s, 'accepted', %s) RETURNING {reservationColumns}",
                (request.unitId, fromHospitalId, request.toHospitalId, simTime),
            )
        except psycopg2.errors.ForeignKeyViolation:
            raise ApiError(400, "unknownHospital")
        except psycopg2.errors.UniqueViolation:
            raise ApiError(409, "unitNotAvailable")
        reservation = reservationFromRow(cursor.fetchone())
        logEvent(cursor, "reservation", simTime,
                 f"{reservation['reservationId']}: {request.unitId} reserved for {request.toHospitalId}",
                 unitId=request.unitId, hospitalId=fromHospitalId)
    return reservation


@router.post("/reservations/{reservationId}/complete")
def completeReservation(reservationId: str):
    with transaction() as cursor:
        cursor.execute(f"SELECT {reservationColumns} FROM reservations WHERE reservation_id = %s FOR UPDATE",
                       (reservationId,))
        row = cursor.fetchone()
        if row is None:
            raise ApiError(404, "reservationNotFound")
        reservation = reservationFromRow(row)
        if reservation["status"] == "completed":
            return reservation  # Completing twice is harmless, so a retried click just succeeds.
        # The unit may have been transfused or expired by a feed event while reserved.
        cursor.execute(
            "UPDATE units SET status = 'available', hospital_id = %s "
            "WHERE unit_id = %s AND status IN ('reserved', 'inTransit')",
            (reservation["toHospitalId"], reservation["unitId"]),
        )
        if cursor.rowcount == 0:
            raise ApiError(409, "unitNotAvailable")
        simTime = currentSimTime(cursor)
        cursor.execute("UPDATE reservations SET status = 'completed', completed_at = %s WHERE reservation_id = %s",
                       (simTime, reservationId))
        logEvent(cursor, "transfer", simTime,
                 f"{reservationId}: {reservation['unitId']} moved from {reservation['fromHospitalId']}",
                 unitId=reservation["unitId"], hospitalId=reservation["toHospitalId"])
    return {**reservation, "status": "completed"}


@router.post("/emergency")
def createEmergency(request: EmergencyRequest):
    return [examples.exampleEmergencySource]


@router.get("/metrics")
def getMetrics():
    return examples.exampleMetrics


@router.get("/events")
def getEvents(limit: int = 50):
    return [examples.exampleEvent][:limit]


@router.get("/simulation/results")
def getSimulationResults():
    if comparisonPath.exists():
        return json.loads(comparisonPath.read_text())
    return examples.exampleComparison


def recordDelivery(cursor, event, simTime: str) -> None:
    unit = event.unit
    try:
        cursor.execute(
            f"INSERT INTO units ({unitColumns}) VALUES (%s, %s, %s, %s, %s, %s)",
            (unit.unitId, unit.bloodGroup, unit.collectedAt, unit.expiresAt, unit.hospitalId, unit.status),
        )
    except psycopg2.errors.UniqueViolation:
        raise ApiError(409, "unitAlreadyExists")
    except psycopg2.errors.ForeignKeyViolation:
        raise ApiError(400, "unknownHospital")
    logEvent(cursor, "delivery", simTime, f"Unit {unit.unitId} ({unit.bloodGroup}) delivered to {unit.hospitalId}",
             unitId=unit.unitId, hospitalId=unit.hospitalId, bloodGroup=unit.bloodGroup, units=1)


def recordUnitLeaving(cursor, event, simTime: str, newStatus: str, verb: str) -> None:
    """Transfusion or expiry: any active unit can leave, including a reserved one."""
    cursor.execute(
        "UPDATE units SET status = %s WHERE unit_id = %s AND status = ANY(%s) RETURNING hospital_id, blood_group",
        (newStatus, event.unitId, list(activeStatuses)),
    )
    row = cursor.fetchone()
    if row is None:
        cursor.execute("SELECT 1 FROM units WHERE unit_id = %s", (event.unitId,))
        raise ApiError(409, "unitNotAvailable") if cursor.fetchone() else ApiError(404, "unitNotFound")
    hospitalId, bloodGroup = row
    logEvent(cursor, event.type, simTime, f"Unit {event.unitId} ({bloodGroup}) {verb} at {hospitalId}",
             unitId=event.unitId, hospitalId=hospitalId, bloodGroup=bloodGroup, units=1)


def recordDemandUnmet(cursor, event, simTime: str) -> None:
    try:
        logEvent(cursor, "demandUnmet", simTime,
                 f"{event.units} unit(s) of {event.bloodGroup} needed at {event.hospitalId} with none in stock",
                 hospitalId=event.hospitalId, bloodGroup=event.bloodGroup, units=event.units)
    except psycopg2.errors.ForeignKeyViolation:
        raise ApiError(400, "unknownHospital")


@router.post("/feed/events", status_code=202)
def postFeedEvent(event: FeedEvent = Body()):
    with transaction() as cursor:
        if event.type == "clock":
            logEvent(cursor, "clock", event.simTime, f"Sim clock {event.simTime}")
        else:
            simTime = currentSimTime(cursor)
            if event.type == "delivery":
                recordDelivery(cursor, event, simTime)
            elif event.type == "transfusion":
                recordUnitLeaving(cursor, event, simTime, "transfused", "transfused")
            elif event.type == "expiry":
                recordUnitLeaving(cursor, event, simTime, "expired", "expired")
            else:
                recordDemandUnmet(cursor, event, simTime)
    return examples.exampleFeedAccepted


app.include_router(router)

# Mounted last so /api routes take priority over static files.
if webDir.is_dir():
    app.mount("/", StaticFiles(directory=webDir, html=True), name="web")
