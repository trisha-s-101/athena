# Platelet Exchange: Team Contract (v1.2)

**This file is the source of truth.** If your code disagrees with it, your code is wrong.
Only Neil changes this file. Every change bumps the version number and gets announced in the group chat.

**Changes in v1.2** (everything here describes code already on `main`):
- §7: `comparison.json` gains multi-seed `seeds`, `statistics` and `stressScenarios` keys alongside the original ones. `sim.live` flags documented.
- §8: every error code listed; new `GET /benchmark/results`; `/emergency` returns every compatible source; `/events` leaves out clock ticks; how sim time, `/metrics` and `/recommendations` are computed.
- §10: team docs live in `shared/`; `results/benchmark.json` shape.

---

## 1. What we're building

A live platelet exchange for ~10 Greater Manchester hospitals. It tracks each hospital's platelet stock, forecasts demand, and recommends moving units that are about to expire to hospitals likely to use them. Every transfer is an atomic reservation in a database on the IBM Z instance, so no unit can be promised twice and every handoff is logged. A simulation proves the effect (waste and shortages, baseline vs. exchange), and a benchmark proves correctness and speed on the mainframe.

---

## 2. Architecture

```
 shared/*.json  (Person 5: hospitals, travel times, compatibility, assumptions)
      │ read by everyone
      ▼
 sim/  (Person 2) ──── function calls ────►  engine/  (Person 3)
      │                                        ▲   pure functions:
      │ HTTP POST /api/feed/events             │   forecast, transfers,
      ▼                                        │   emergency ranking
 api/  (Neil) ──── function calls ─────────────┘
      │  │
      │  └──► PostgreSQL  (db/, Neil)
      ▲
      │ HTTP GET/POST only
 web/  (Person 4: dashboard, starts on mock JSON)

 bench/ (Neil): concurrency + latency tests against api/
 docs/  (Persons 5 and 6): assumptions, validation, pitch
```

### Golden rules (these are what make the pieces fit)

1. **`engine/` is pure.** No database, no HTTP, no file reads. Plain dicts and lists in, plain dicts and lists out. That lets the simulator and the API both call it.
2. **Only `api/` talks to Postgres.**
3. **`sim/` reaches the API only over HTTP** (live demo mode) and calls `engine/` directly (offline experiments).
4. **`web/` reaches the API only over HTTP** and runs on mock JSON (`web/mock/`) until the API is live.
5. **Work only in your own folder.** Need something from another module? Ask its owner; don't edit their code.
6. **Stubs first.** Within the first hour, every module ships a stub that matches this contract, even if it returns fake data. Real logic replaces stubs later without anyone else noticing.

---

## 3. Conventions

- **Environment:** IBM LinuxONE, s390x, Ubuntu 24.04, Python 3.12, no Docker. Allowed third-party Python packages: `fastapi`, `uvicorn`, `psycopg2`, `networkx`. Everything else uses the standard library. The app runs on port 8000, and FastAPI serves `web/` at `/`. The database URL comes from the `DATABASE_URL` environment variable and is never committed.
- **Language:** Python 3.12 for `api/`, `engine/`, `sim/`, `bench/`. Plain HTML/CSS/JS for `web/` (no build step on the mainframe).
- **Naming:** camelCase for variables and functions, PascalCase for classes. JSON keys are camelCase.
- **SQL:** columns are snake_case (Postgres lowercases unquoted names). `api/` converts rows to camelCase JSON.
- **Times:** ISO 8601 UTC strings, e.g. `"2026-01-05T14:00:00Z"`. Dates are `"2026-01-05"`. The sim clock starts Monday `2026-01-05T00:00:00Z`.
- **IDs are strings:** hospitals `"H01"`–`"H10"`, units `"U000001"`, reservations `"R000001"`, events `"E000001"`.
- **Blood groups:** exactly one of `"O+" "O-" "A+" "A-" "B+" "B-" "AB+" "AB-"`.
- **Shelf life:** 7 days from collection, so `expiresAt = collectedAt + 7 days`.
- **Unit status:** `available | reserved | inTransit | transfused | expired`.
- **Spelling:** American English in code, UI and docs.

---

## 4. Shared data files (`shared/`, owned by Person 5)

Placeholder values below let everyone start immediately. Person 5 replaces them with researched values and keeps the shapes **identical**.

### `shared/hospitals.json`
```json
[
  {"hospitalId": "H01", "name": "Manchester Royal Infirmary", "lat": 53.4627, "lng": -2.2265, "sizeCategory": "large", "hasHaematology": true}
]
```
`sizeCategory` is one of `small | medium | large`. Use around 10 Greater Manchester hospitals.

### `shared/travelTimes.json`
```json
[{"fromHospitalId": "H01", "toHospitalId": "H02", "minutes": 25}]
```
Include every ordered pair. Driving time by road with a courier, not straight-line distance.

### `shared/compatibility.json`
Keys are recipient groups. Each lists the donor groups allowed, with a penalty (0 = identical and preferred, higher = less preferred). A missing donor means not allowed.
```json
{
  "A+": [{"donor": "A+", "penalty": 0}, {"donor": "A-", "penalty": 1}, {"donor": "O+", "penalty": 3}]
}
```

### `shared/assumptions.json`
```json
{
  "simDays": 90,
  "baselineWasteRate": 0.048,
  "dailyDemandMean": {"small": 1, "medium": 3, "large": 8},
  "weekendDemandFactor": 0.6,
  "bloodGroupMix": {"O+": 0.35, "A+": 0.30, "B+": 0.08, "AB+": 0.02, "O-": 0.13, "A-": 0.08, "B-": 0.02, "AB-": 0.01},
  "remainingShelfLifeOnArrivalDays": {"min": 1, "max": 4},
  "targetStockDays": {"small": 2, "medium": 2, "large": 1.5},
  "maxTransferMinutes": 240,
  "minHoursLeftToTransfer": 12
}
```
Every value is a **placeholder** until Person 5 signs it off in `docs/assumptions.md` with a source.

---

## 5. Core data shapes

```jsonc
// Hospital
{"hospitalId": "H01", "name": "...", "lat": 53.46, "lng": -2.23, "sizeCategory": "large", "hasHaematology": true}

// Unit
{"unitId": "U000123", "bloodGroup": "A+", "collectedAt": "2026-01-05T08:00:00Z",
 "expiresAt": "2026-01-12T08:00:00Z", "hospitalId": "H03", "status": "available"}

// DemandRecord (history input to the forecaster)
{"date": "2026-01-05", "hospitalId": "H03", "bloodGroup": "A+", "units": 2}

// Forecast (expected units used per day, index 0 = today)
{"H03": {"A+": [2.1, 1.8, 2.4], "O+": [3.0, 2.7, 2.9]}}

// Transfer (engine recommendation)
{"unitId": "U000123", "fromHospitalId": "H03", "toHospitalId": "H01",
 "travelMinutes": 25, "hoursToExpiry": 30.5, "score": 0.82,
 "reason": "Expires in 30h at H03 (forecast use 0.2); H01 forecast use 2.4"}

// EmergencyRequest
{"hospitalId": "H05", "bloodGroup": "O-", "unitsNeeded": 2}

// EmergencySource (ranked best first)
{"unitId": "U000456", "hospitalId": "H02", "bloodGroup": "O-",
 "hoursToExpiry": 50.0, "travelMinutes": 18, "penalty": 0, "rank": 1}

// SimResult
{"policy": "exchange", "days": 90, "unitsDelivered": 21000, "unitsTransfused": 20400,
 "unitsWasted": 610, "wasteRate": 0.029, "shortageEvents": 4, "transfers": 820,
 "daily": [{"date": "2026-01-05", "wasted": 7, "shortages": 0, "transfers": 9}]}
```

---

## 6. Engine interface (`engine/`, Person 3)

```python
# engine/__init__.py must expose exactly these three functions.

def forecastDemand(history: list[dict], horizonDays: int = 3) -> dict:
    """history: list of DemandRecord. Returns a Forecast."""

def recommendTransfers(stock: list[dict], forecast: dict, travelTimes: list[dict],
                       compatibility: dict, now: str) -> list[dict]:
    """stock: available Units across all hospitals. Returns Transfers, best first.
    Must never recommend the same unitId twice, a unit with fewer than
    minHoursLeftToTransfer hours left, or a trip longer than maxTransferMinutes."""

def rankEmergencySources(request: dict, stock: list[dict], travelTimes: list[dict],
                         compatibility: dict, now: str) -> list[dict]:
    """Returns EmergencySources, best first. Excludes the requesting hospital's own stock
    and incompatible units."""
```

The stub (due at +1h) returns a naive forecast (yesterday's demand repeated), `[]` for transfers, and nearest compatible units for emergencies.

---

## 7. Simulator interface (`sim/`, Person 2)

```python
def generateScenario(assumptions: dict, hospitals: list[dict], seed: int) -> dict:
    """Returns {"deliveries": [Unit...], "demand": [DemandRecord...]} for simDays."""

def runSimulation(scenario: dict, policyName: str, seed: int) -> dict:
    """policyName: "noSharing" | "exchange". Returns a SimResult.
    "exchange" calls engine.forecastDemand and engine.recommendTransfers every 6 sim hours.
    Same scenario + same seed must give identical results."""
```

Commands:
- `python -m sim.run [--seeds 1,2,...,10] [--seed N] [--days 90]` writes `results/comparison.json`:
  ```jsonc
  {"generatedAt": "...",
   "seed": 42, "noSharing": SimResult, "exchange": SimResult,        // one canonical run (seed 42)
   "seeds": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],                          // multi-seed runs, for error bars
   "statistics": {
     "noSharing": {"wasteRate": Stats, "shortageEvents": Stats, "transfers": 0},
     "exchange":  {"wasteRate": Stats, "shortageEvents": Stats, "transfers": Stats}},
   "stressScenarios": {
     "demandSurge": {"description": "...", "noSharing": SimResult, "exchange": SimResult},
     "supplyDip":   {"description": "...", "noSharing": SimResult, "exchange": SimResult}}}
  // Stats = {"mean": 0.031, "stdDev": 0.004, "min": 0.025, "max": 0.038}
  ```
- `python -m sim.live --api http://localhost:8000 --speed 60 [--seed 42] [--days 90] [--policy noSharing] [--dryRun]` streams one scenario's feed events to `POST /api/feed/events`. `--speed` is a time multiplier: 60 means 1 sim hour per real minute. The default policy is `noSharing`, because the feed has no event for a unit changing hospital; in live mode, transfers come from the dashboard reserving through the API. Wipe the database (`python -m db.seed --reset`) before every live run, or the replayed units are rejected as duplicates.

Within a hospital, units are issued oldest first (FIFO) in both policies, so the only difference measured is sharing.

---

## 8. HTTP API (`api/`, Neil). Base path `/api`

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | | `{"status": "ok", "arch": "s390x", "dbOk": true}` |
| GET | `/hospitals` | | `[Hospital + "stockSummary": {"available": 12, "expiringIn24h": 3}]` |
| GET | `/stock?hospitalId=H01` | hospitalId optional | `[Unit]` (non-terminal statuses) |
| GET | `/recommendations` | | `[Transfer]` (engine run on current DB stock) |
| POST | `/reservations` | `{"unitId": "U000123", "toHospitalId": "H01"}` | **201** `{"reservationId": "R000001", "unitId": "U000123", "fromHospitalId": "H03", "toHospitalId": "H01", "status": "accepted", "createdAt": "..."}` or **409** `{"error": "unitNotAvailable"}` |
| POST | `/reservations/{reservationId}/complete` | | **200** reservation with `"status": "completed"`; the unit moves to `toHospitalId` and is `available` again |
| POST | `/emergency` | EmergencyRequest | `[EmergencySource]`: every compatible available unit at other hospitals, best first, not only `unitsNeeded` of them (so a lost reservation race has fallbacks) |
| GET | `/metrics` | | `{"simTime": "...", "unitsAvailable": 140, "expiringIn24h": 18, "wastedToday": 2, "shortagesToday": 0, "transfersToday": 6, "wasteRate": 0.031}` |
| GET | `/events?limit=50` | `limit` 1–500 | `[{"eventId": "E000001", "type": "delivery", "unitId": "U000123", "hospitalId": "H03", "at": "...", "detail": "..."}]` newest first, without `clock` events. `unitId` or `hospitalId` is `null` when the event has none |
| GET | `/simulation/results` | | contents of `results/comparison.json` (§7) |
| GET | `/benchmark/results` | | contents of `results/benchmark.json` (§10), or **404** `{"error": "benchmarkNotFound"}` before the benchmarks have run |
| POST | `/feed/events` | `{"type": "delivery", "unit": Unit}` / `{"type": "transfusion", "unitId": "..."}` / `{"type": "expiry", "unitId": "..."}` / `{"type": "demandUnmet", "hospitalId": "...", "bloodGroup": "...", "units": 1}` / `{"type": "clock", "simTime": "..."}` | **202** `{"accepted": true}` |

Errors are always `{"error": "camelCaseCode"}`, with these codes:

| Status | Code | When |
|---|---|---|
| 400 | `invalidRequest` | The body or query doesn't match the shapes above (including an unparseable time) |
| 400 | `unknownHospital` | A delivery, reservation, emergency or `demandUnmet` names a hospital that doesn't exist |
| 400 | `sameHospital` | A reservation's `toHospitalId` is the hospital the unit is already at |
| 404 | `notFound` | No such endpoint |
| 404 | `unitNotFound` | A transfusion or expiry names a unit the API has never seen |
| 404 | `reservationNotFound` | Completing a reservation that doesn't exist |
| 404 | `benchmarkNotFound` | `/benchmark/results` before `results/benchmark.json` exists |
| 405 | `methodNotAllowed` | Wrong HTTP method for the path |
| 409 | `unitNotAvailable` | Reserving a unit that isn't `available`; completing a reservation whose unit was transfused or expired meanwhile; a transfusion or expiry for a unit already transfused or expired |
| 409 | `unitAlreadyExists` | A delivery for a `unitId` the API already has |
| 503 | `databaseUnavailable` | Postgres can't be reached. The only 5xx; `/health` still answers, with `"dbOk": false` |

**Reservation correctness rule:** reserving is a single conditional update (`... SET status = 'reserved' WHERE unit_id = $1 AND status = 'available'`). Zero rows affected means 409. Backed by a partial unique index allowing one active reservation per unit.

**How the API computes things:**
- **Sim time** is the `simTime` of the latest `clock` feed event, or `2026-01-05T00:00:00Z` before the first one. Every event, `createdAt`, "today" and "next 24h" uses sim time, never the wall clock.
- **Events logged:** `delivery`, `transfusion`, `expiry`, `demandUnmet` and `clock` from the feed, plus `reservation` (unit reserved) and `transfer` (reservation completed) from the API.
- **Reservations:** a reserved unit can still be transfused or expire through the feed; completing its reservation then returns 409. Completing an already completed reservation returns 200 with the same body. The `inTransit` status is never set: completing moves a unit straight from `reserved` to `available` at the destination.
- **`/metrics`:** `unitsAvailable` and `expiringIn24h` count `available` units. `wastedToday`, `shortagesToday` and `transfersToday` count `expiry`, `demandUnmet` and `transfer` events on the current sim day (UTC). `wasteRate` is all `expiry` events divided by all `delivery` events.
- **`/recommendations`:** demand history is the last 28 complete sim days of transfusions (counted under the transfused unit's blood group) plus `demandUnmet` units. It is passed to `engine.forecastDemand`, and the forecast goes to `engine.recommendTransfers` with available stock, `travel_times` and `shared/compatibility.json`. No history (the first sim day) means no recommendations.
- `hoursToExpiry` in `/recommendations` and `/emergency` is rounded to 1 decimal place.

---

## 9. Database (`db/`, Neil)

Tables: `hospitals`, `travel_times`, `units`, `reservations`, `events`.
`db/schema.sql` creates them, and `db/seed.py` loads `shared/*.json`. Nobody else touches the database directly.

---

## 10. Repo and workflow

```
platelet-exchange/
  CLAUDE.md (copy of AGENTS.md)   README.md
  shared/       CONTRACT.md  AGENTS.md  BRIEFS.md  INSTANCE_SETUP.md
                hospitals.json  travelTimes.json  compatibility.json  assumptions.json
  db/           schema.sql  seed.py
  api/          (FastAPI app)
  engine/       __init__.py  forecast.py  transfers.py  emergency.py  tests/
  sim/          generate.py  simulate.py  run.py  live.py  tests/
  web/          index.html  app.js  styles.css  mock/*.json
  bench/        reserveRace.py  latency.py  tests/
  results/      comparison.json  benchmark.json
  docs/         assumptions.md  validation.md  pitch/
```

`results/benchmark.json` (written by `bench/`, served by `GET /api/benchmark/results`). Each script replaces only its own section:
```jsonc
{"generatedAt": "...", "arch": "s390x",          // arch reported by the API's /health
 "reserveRace": {"generatedAt": "...", "attempts": 1000, "accepted": 1, "conflicts": 999, "otherErrors": 0,
                 "passed": true, "durationSeconds": 1.8, "p50Ms": 610.2, "p99Ms": 1490.7},
 "latency": {"generatedAt": "...", "concurrency": 20, "requestsPerEndpoint": 500,
             "endpoints": [{"name": "GET /api/hospitals", "requests": 500, "errors": 0,
                            "throughputPerSecond": 410.5, "p50Ms": 41.2, "p99Ms": 120.9}]}}
```
`passed` is true only when exactly one of the concurrent reservations got 201 and every other one got 409.

- One branch per person (`neil/api`, `sim`, `engine`, `web`, `docs`). Small pull requests into `main`, merged by Neil.
- **`main` must always run.** Before merging: the module's tests pass and the stub-or-real code matches this contract.
- Contract change needed? Message Neil and don't work around it.

---

## 11. Integration checkpoints (relative to kickoff)

| When | Everyone has |
|---|---|
| +1h | Stubs committed: engine stubs, sim writes a fake `comparison.json`, API returns the example JSON above, dashboard renders `web/mock/`, shared files at v0 |
| +4h | **Walking skeleton on the Z instance:** sim → API → Postgres → dashboard, end to end with fake logic |
| +10h | Real logic in every module, first real `comparison.json` |
| +16h | Fully integrated on Z, benchmarks run, headline numbers locked |
| +20h | **Feature freeze.** Bug fixes only |
| End | Two full rehearsals done, backup screen recording saved |

---

## 12. Definition of done (what the judges see)

1. The dashboard on the Z instance shows live stock across hospitals, colored by days to expiry.
2. Live mode: units approach expiry, recommendations appear, and a click reserves and completes a transfer.
3. Emergency request returns ranked compatible units in under a second.
4. A comparison view shows waste and shortages for `noSharing` vs `exchange` over 90 days, with error bars across seeds.
5. Benchmark: 1,000 concurrent reservations on one unit produce exactly one success, with throughput and p50/p99 latency reported from the Z instance.
6. An assumptions slide states what is synthetic and what each number is calibrated against.
