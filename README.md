# Platelet Exchange

A live platelet exchange for 10 Greater Manchester hospitals. It tracks each hospital's platelet stock, forecasts demand, and recommends moving units that are about to expire to hospitals likely to use them. Every transfer is a single atomic reservation in Postgres, so no unit can be promised twice. A simulator measures the effect (waste and shortages, with and without sharing), and benchmarks prove correctness and speed on IBM LinuxONE (s390x).

`shared/CONTRACT.md` is the source of truth for every interface. `shared/INSTANCE_SETUP.md` is the step-by-step guide for the LinuxONE instance.

## What's where

| Folder | What it is |
|---|---|
| `api/` | FastAPI app. Serves the HTTP API at `/api` and the dashboard at `/`. The only code that talks to Postgres. |
| `db/` | `schema.sql` and `seed.py`, which loads `shared/hospitals.json` and `shared/travelTimes.json`. |
| `engine/` | Pure forecasting, transfer and emergency-ranking functions. |
| `sim/` | Scenario generator, offline simulation (`sim.run`) and live mode (`sim.live`). |
| `web/` | Dashboard: plain HTML, CSS and JS, with mock data in `web/mock/`. |
| `bench/` | Reservation race and latency benchmarks. |
| `shared/` | Team docs and the shared data files. |
| `results/` | `comparison.json` (from the simulator) and `benchmark.json` (from the benchmarks). |
| `docs/` | Assumptions and their sources. |

## Requirements

Python 3.12, PostgreSQL 16 or later, and the four allowed packages: `fastapi`, `uvicorn`, `psycopg2` and `networkx`. Everything else is the standard library. There is no build step and no Docker.

The app reads its database from the `DATABASE_URL` environment variable, for example `postgresql://plateletapp:PASSWORD@localhost:5432/plateletexchange`. It's never committed. On the instance it lives in `~/plateletExchange.env`.

## Run it from a clean start

From the repository root:

```bash
export DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/plateletexchange"
python -m db.seed
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`db.seed` creates the tables and loads the hospitals. It's safe to rerun, and `python -m db.seed --reset` wipes all live data. Open http://localhost:8000 and untick **Use mock data** to see the live API. The dashboard also runs entirely on mock data without the API: `python -m http.server 8080 --directory web`.

On the LinuxONE instance, follow `shared/INSTANCE_SETUP.md` Part 8 (deploy), Part 9 (live mode) and Part 10 (benchmarks). The app runs inside tmux, and the dashboard is reached through an SSH tunnel.

## Live mode

With the app running, in a second terminal:

```bash
python -m db.seed --reset
python -m sim.live --api http://localhost:8000 --speed 1440
```

`--speed 1440` runs one sim day per real minute. Wipe the database before every run, because a run replays the same units from the start. Recommendations appear once there's a day of demand history.

## Simulation results

```bash
python -m sim.run
```

This runs both policies (`noSharing` and `exchange`) over 90 days for seeds 1–10, plus a canonical seed-42 run and two stress scenarios, and writes `results/comparison.json`. It takes about a minute and a half. The dashboard's comparison view shows the canonical run and error bars across seeds.

## Benchmarks

With the app running:

```bash
python -m bench.reserveRace
python -m bench.latency
```

The race sends 1,000 simultaneous reservations for one unit and passes only if exactly one succeeds. The latency benchmark reports throughput, p50 and p99 for the main endpoints. Both write `results/benchmark.json`, which the dashboard's benchmark panel reads from `GET /api/benchmark/results`. They add test data, so wipe the database afterwards.

## Tests

```bash
python -m unittest discover api/tests
python -m unittest discover db/tests
python -m unittest discover bench/tests
python -m unittest discover -s engine/tests
python -m unittest discover -s sim/tests -t .
node --test web/tests/*.test.js
```

The database tests are skipped unless `TEST_DATABASE_URL` points at a **throwaway** database, because they drop every table. Never point it at the real one. The sim suite takes about 5 minutes. Node is only needed for the dashboard tests.
