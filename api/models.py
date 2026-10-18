"""Request body shapes from contract sections 5 and 8."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

BloodGroup = Literal["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
UnitStatus = Literal["available", "reserved", "inTransit", "transfused", "expired"]


class Unit(BaseModel):
    unitId: str
    bloodGroup: BloodGroup
    collectedAt: str
    expiresAt: str
    hospitalId: str
    status: UnitStatus


class ReservationRequest(BaseModel):
    unitId: str
    toHospitalId: str


class EmergencyRequest(BaseModel):
    hospitalId: str
    bloodGroup: BloodGroup
    unitsNeeded: int = Field(gt=0)


class DeliveryEvent(BaseModel):
    type: Literal["delivery"]
    unit: Unit


class TransfusionEvent(BaseModel):
    type: Literal["transfusion"]
    unitId: str


class ExpiryEvent(BaseModel):
    type: Literal["expiry"]
    unitId: str


class DemandUnmetEvent(BaseModel):
    type: Literal["demandUnmet"]
    hospitalId: str
    bloodGroup: BloodGroup
    units: int = Field(gt=0)


class ClockEvent(BaseModel):
    type: Literal["clock"]
    simTime: str


FeedEvent = Annotated[
    Union[DeliveryEvent, TransfusionEvent, ExpiryEvent, DemandUnmetEvent, ClockEvent],
    Field(discriminator="type"),
]
