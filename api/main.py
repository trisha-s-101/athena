"""Platelet exchange HTTP API (CONTRACT.md section 8).

Stub stage: every endpoint returns the contract's example JSON.
Run from the repo root: uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

import json
import platform
from pathlib import Path

from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import examples
from api.models import EmergencyRequest, FeedEvent, ReservationRequest

repoRoot = Path(__file__).resolve().parent.parent
webDir = repoRoot / "web"
comparisonPath = repoRoot / "results" / "comparison.json"

httpErrorCodes = {404: "notFound", 405: "methodNotAllowed"}


class ApiError(Exception):
    """Raise to return {"error": code} with a 4xx status."""

    def __init__(self, statusCode: int, code: str):
        self.statusCode = statusCode
        self.code = code


app = FastAPI(title="Platelet Exchange API")
router = APIRouter(prefix="/api")


@app.exception_handler(ApiError)
async def onApiError(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.statusCode, content={"error": exc.code})


@app.exception_handler(RequestValidationError)
async def onValidationError(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": "invalidRequest"})


@app.exception_handler(StarletteHTTPException)
async def onHttpError(request: Request, exc: StarletteHTTPException):
    code = httpErrorCodes.get(exc.status_code, "httpError")
    return JSONResponse(status_code=exc.status_code, content={"error": code})


@router.get("/health")
def getHealth():
    return {"status": "ok", "arch": platform.machine(), "dbOk": False}


@router.get("/hospitals")
def getHospitals():
    return [examples.exampleHospital]


@router.get("/stock")
def getStock(hospitalId: str | None = None):
    units = [examples.exampleUnit]
    if hospitalId is not None:
        units = [unit for unit in units if unit["hospitalId"] == hospitalId]
    return units


@router.get("/recommendations")
def getRecommendations():
    return [examples.exampleTransfer]


@router.post("/reservations", status_code=201)
def createReservation(request: ReservationRequest):
    # Stub: only the example unit can be reserved, so callers can exercise the 409 path.
    if request.unitId != examples.exampleUnit["unitId"]:
        raise ApiError(409, "unitNotAvailable")
    return {**examples.exampleReservation, "toHospitalId": request.toHospitalId}


@router.post("/reservations/{reservationId}/complete")
def completeReservation(reservationId: str):
    return {**examples.exampleCompletedReservation, "reservationId": reservationId}


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


@router.post("/feed/events", status_code=202)
def postFeedEvent(event: FeedEvent = Body()):
    return examples.exampleFeedAccepted


app.include_router(router)

# Mounted last so /api routes take priority over static files.
if webDir.is_dir():
    app.mount("/", StaticFiles(directory=webDir, html=True), name="web")
