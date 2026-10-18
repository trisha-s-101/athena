"""Create the schema and load shared/hospitals.json and shared/travelTimes.json (contract section 9).

Run from the repo root with DATABASE_URL set:
    python -m db.seed            # create missing tables, then insert or update hospitals and travel times
    python -m db.seed --reset    # drop every table first (wipes units, reservations and events)

Units, reservations and events are not seeded: they arrive through the API's feed.
"""

import argparse
import json
import os
import sys
from numbers import Real
from pathlib import Path

import psycopg2

repoRoot = Path(__file__).resolve().parent.parent
schemaPath = Path(__file__).resolve().parent / "schema.sql"
defaultSharedDir = repoRoot / "shared"

hospitalKeys = {"hospitalId", "name", "lat", "lng", "sizeCategory", "hasHaematology"}
travelTimeKeys = {"fromHospitalId", "toHospitalId", "minutes"}
sizeCategories = {"small", "medium", "large"}

# Children first, so foreign keys never block the drop.
dropSql = "DROP TABLE IF EXISTS events, reservations, units, travel_times, hospitals CASCADE;"

upsertHospitalSql = """
INSERT INTO hospitals (hospital_id, name, lat, lng, size_category, has_haematology)
VALUES (%(hospitalId)s, %(name)s, %(lat)s, %(lng)s, %(sizeCategory)s, %(hasHaematology)s)
ON CONFLICT (hospital_id) DO UPDATE SET
    name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
    size_category = EXCLUDED.size_category, has_haematology = EXCLUDED.has_haematology;
"""

upsertTravelTimeSql = """
INSERT INTO travel_times (from_hospital_id, to_hospital_id, minutes)
VALUES (%(fromHospitalId)s, %(toHospitalId)s, %(minutes)s)
ON CONFLICT (from_hospital_id, to_hospital_id) DO UPDATE SET minutes = EXCLUDED.minutes;
"""


class SeedError(Exception):
    """A shared file is missing or doesn't match the contract's shape."""


def loadJsonFile(path: Path):
    if not path.exists():
        raise SeedError(f"Missing {path}. Expected in shared/.")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise SeedError(f"{path} is not valid JSON: {error}") from error


def isNumber(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def validateHospitals(hospitals) -> None:
    if not isinstance(hospitals, list) or not hospitals:
        raise SeedError("hospitals.json must be a non-empty list")
    seenIds = set()
    for hospital in hospitals:
        if not isinstance(hospital, dict) or set(hospital) != hospitalKeys:
            raise SeedError(f"Hospital must have exactly the keys {sorted(hospitalKeys)}: {hospital}")
        hospitalId = hospital["hospitalId"]
        if hospitalId in seenIds:
            raise SeedError(f"Duplicate hospitalId {hospitalId}")
        seenIds.add(hospitalId)
        if hospital["sizeCategory"] not in sizeCategories:
            raise SeedError(f"{hospitalId}: sizeCategory must be one of {sorted(sizeCategories)}")
        if not (isNumber(hospital["lat"]) and isNumber(hospital["lng"])):
            raise SeedError(f"{hospitalId}: lat and lng must be numbers")
        if not isinstance(hospital["hasHaematology"], bool):
            raise SeedError(f"{hospitalId}: hasHaematology must be true or false")


def validateTravelTimes(travelTimes, hospitalIds: set) -> list[str]:
    """Raises on bad rows. Returns warnings for missing ordered pairs (contract section 4 wants every pair)."""
    if not isinstance(travelTimes, list):
        raise SeedError("travelTimes.json must be a list")
    seenPairs = set()
    for route in travelTimes:
        if not isinstance(route, dict) or set(route) != travelTimeKeys:
            raise SeedError(f"Travel time must have exactly the keys {sorted(travelTimeKeys)}: {route}")
        pair = (route["fromHospitalId"], route["toHospitalId"])
        unknownIds = set(pair) - hospitalIds
        if unknownIds:
            raise SeedError(f"Travel time {pair} names unknown hospital(s) {sorted(unknownIds)}")
        if pair in seenPairs:
            raise SeedError(f"Duplicate travel time {pair}")
        seenPairs.add(pair)
        if not isNumber(route["minutes"]) or route["minutes"] < 0:
            raise SeedError(f"Travel time {pair}: minutes must be a nonnegative number")
    missingPairs = [(fromId, toId) for fromId in sorted(hospitalIds) for toId in sorted(hospitalIds)
                    if fromId != toId and (fromId, toId) not in seenPairs]
    if missingPairs:
        return [f"{len(missingPairs)} ordered hospital pair(s) have no travel time, e.g. {missingPairs[0]}"]
    return []


def loadSharedData(sharedDir: Path) -> tuple[list[dict], list[dict], list[str]]:
    hospitals = loadJsonFile(sharedDir / "hospitals.json")
    travelTimes = loadJsonFile(sharedDir / "travelTimes.json")
    validateHospitals(hospitals)
    warnings = validateTravelTimes(travelTimes, {hospital["hospitalId"] for hospital in hospitals})
    return hospitals, travelTimes, warnings


def seedDatabase(connection, hospitals: list[dict], travelTimes: list[dict], reset: bool = False) -> None:
    """One transaction: on any error nothing changes."""
    with connection, connection.cursor() as cursor:
        if reset:
            cursor.execute(dropSql)
        cursor.execute(schemaPath.read_text())
        cursor.executemany(upsertHospitalSql, hospitals)
        cursor.executemany(upsertTravelTimeSql, travelTimes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the schema and load shared/*.json")
    parser.add_argument("--reset", action="store_true",
                        help="drop every table first (wipes units, reservations and events)")
    parser.add_argument("--sharedDir", type=Path, default=defaultSharedDir,
                        help="folder holding hospitals.json and travelTimes.json")
    args = parser.parse_args(argv)

    databaseUrl = os.environ.get("DATABASE_URL")
    if not databaseUrl:
        print("DATABASE_URL is not set. On the instance: source ~/plateletExchange.env", file=sys.stderr)
        return 1
    try:
        hospitals, travelTimes, warnings = loadSharedData(args.sharedDir)
    except SeedError as error:
        print(f"Seed failed: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    connection = psycopg2.connect(databaseUrl)
    try:
        seedDatabase(connection, hospitals, travelTimes, reset=args.reset)
    finally:
        connection.close()
    action = "Reset and seeded" if args.reset else "Seeded"
    print(f"{action}: {len(hospitals)} hospitals, {len(travelTimes)} travel times")
    return 0


if __name__ == "__main__":
    sys.exit(main())
