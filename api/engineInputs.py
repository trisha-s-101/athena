"""Builds the engine's inputs (contract section 6) from the database and shared/compatibility.json.

The engine is pure, so the API gathers everything it needs here and passes plain dicts and lists.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from api.database import toIsoTime

compatibilityPath = Path(__file__).resolve().parent.parent / "shared" / "compatibility.json"
historyDays = 28  # Four weeks gives the weekday forecaster each weekday up to four times.


def loadCompatibility() -> dict:
    """Read on every call: the file is tiny, and edits apply without a restart."""
    return json.loads(compatibilityPath.read_text())


def fetchAvailableStock(cursor) -> list[dict]:
    cursor.execute(
        "SELECT unit_id, blood_group, collected_at, expires_at, hospital_id, status "
        "FROM units WHERE status = 'available' ORDER BY unit_id"
    )
    return [{"unitId": unitId, "bloodGroup": bloodGroup, "collectedAt": toIsoTime(collectedAt),
             "expiresAt": toIsoTime(expiresAt), "hospitalId": hospitalId, "status": status}
            for unitId, bloodGroup, collectedAt, expiresAt, hospitalId, status in cursor.fetchall()]


def fetchTravelTimes(cursor) -> list[dict]:
    cursor.execute("SELECT from_hospital_id, to_hospital_id, minutes FROM travel_times")
    return [{"fromHospitalId": fromId, "toHospitalId": toId, "minutes": minutes}
            for fromId, toId, minutes in cursor.fetchall()]


def fetchDemandHistory(cursor, simTime: str) -> list[dict]:
    """DemandRecords for the complete sim days before today: units transfused plus units unmet.

    Transfusions count under the transfused unit's blood group, because the feed doesn't say
    the recipient's group. The forecaster treats the day after the latest record as today, so
    every hospital/group pair gets a zero record for yesterday when it had no demand then.
    """
    today = date.fromisoformat(simTime[:10])
    yesterday = today - timedelta(days=1)
    cursor.execute(
        """
        SELECT (at AT TIME ZONE 'UTC')::date, hospital_id, blood_group, sum(units)
        FROM events
        WHERE type IN ('transfusion', 'demandUnmet')
          AND at >= %s::date AND at < %s::date
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """,
        (today - timedelta(days=historyDays), today),
    )
    history = [{"date": day.isoformat(), "hospitalId": hospitalId, "bloodGroup": bloodGroup, "units": int(units)}
               for day, hospitalId, bloodGroup, units in cursor.fetchall()]
    pairsYesterday = {(record["hospitalId"], record["bloodGroup"]) for record in history
                      if record["date"] == yesterday.isoformat()}
    allPairs = sorted({(record["hospitalId"], record["bloodGroup"]) for record in history})
    history += [{"date": yesterday.isoformat(), "hospitalId": hospitalId, "bloodGroup": bloodGroup, "units": 0}
                for hospitalId, bloodGroup in allPairs if (hospitalId, bloodGroup) not in pairsYesterday]
    return history
