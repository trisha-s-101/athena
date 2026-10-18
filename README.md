# Project Athena

**A live platelet exchange for Greater Manchester hospitals.**

Platelets last five days, need constant agitation at room temperature, and demand for them is unpredictable. So hospitals face an impossible trade-off: stock too little and a patient waits, stock too much and you bin it. Today both happen at once — one hospital discards a unit of O-negative while another twenty minutes away has none.

Athena tracks every unit across ten hospitals, forecasts demand per hospital and blood group with a Bayesian model, and moves stock that is about to expire to where it will actually be used. Every transfer is a single atomic reservation in PostgreSQL, so no unit can ever be promised twice.

Built for the IBM Z Datathon 2026 and running on IBM LinuxONE (s390x).

## Results

Ninety simulated days, ten random seeds, two policies — hospitals working alone versus hospitals sharing through Athena.

| | No sharing | With Athena |
|---|---|---|
| Waste rate | 19.03% ± 0.88 | **14.40% ± 1.05** |
| Shortage events | 263 | **39** |
| Courier transfers | 0 | 405 |

**85% fewer shortages. Waste down by just under a quarter.** The effect holds under stress: a three-fold demand surge cuts shortages from 356 to 90, and a three-day supply gap from 374 to 160.

Measured on LinuxONE: 1,000 simultaneous reservation requests against a single unit produced exactly **one** success, 999 correct rejections and zero errors.

## Try it yourself

### The dashboard, with no setup

The dashboard ships with synthetic data and needs no database:

```bash
cd web && python3 -m http.server 8080
```

Open <http://localhost:8080> and tick **"Use mock data"** in the top right. You will see live stock across ten hospitals coloured by time to expiry, transfer recommendations, the emergency lookup, and the full comparison charts with error bars.

### Run the simulation

No database needed. From the repository root:

```bash
python3 -m sim.run
```

This runs ten seeds plus two stress scenarios across both policies and writes `results/comparison.json`. It takes a few minutes. For a single quick run:

```bash
python3 -m sim.run --seed 42 --days 90
```

### Run the tests

```bash
python3 -m unittest discover -s sim/tests
python3 -m unittest discover -s engine/tests
cd web && npm test
```

### The full stack

Requires PostgreSQL and `psycopg2`. Create a database, point `DATABASE_URL` at it, then:

```bash
python3 -m db.seed --reset
python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The API serves at `/api` and the dashboard at `/`, so <http://localhost:8000> gives you the whole application. To stream a simulated scenario into it:

```bash
python3 -m sim.live --api http://localhost:8000 --speed 1440
```

`--speed 1440` runs one simulated day per real minute.

## How it works

```
 shared/*.json      hospitals, travel times, ABO compatibility, assumptions
      │
      ▼
 sim/  ──── function calls ────►  engine/      Bayesian forecasting,
      │                              ▲         transfer and emergency ranking
      │ HTTP POST /api/feed/events   │         (pure functions, no I/O)
      ▼                              │
 api/  ──── function calls ──────────┘
      │
      └──►  PostgreSQL
      ▲
      │ HTTP
 web/        dashboard
```

The engine is pure: plain dictionaries in, plain dictionaries out, no database and no network. That lets the simulator and the API both call the same forecasting and allocation code, so what the simulation measures is exactly what runs live.

## The forecaster

Demand for rare blood groups at small hospitals is close to unforecastable — a site might use AB-negative three times in a quarter. Athena treats each hospital and blood group as a Poisson process with a Gamma prior, so pairs with thin history borrow strength from comparable hospitals across the region. How strongly they borrow is learned from the data by the method of moments, not set by hand, so genuine differences between hospitals are preserved rather than averaged away.

Validated with a rolling backtest on ten held-out seeds: forecast error fell 7–8% overall and 12% in the first four weeks, when history is thinnest.

## Layout

| Folder | Contents |
|---|---|
| `api/` | FastAPI application. The only code that talks to PostgreSQL. |
| `db/` | Schema and seed loader. |
| `engine/` | Pure forecasting, transfer and emergency-ranking functions. |
| `sim/` | Scenario generator, offline simulation and live streaming mode. |
| `web/` | Dashboard — plain HTML, CSS and JavaScript, with synthetic data in `web/mock/`. |
| `bench/` | Reservation race and latency benchmarks. |
| `results/` | Simulation and benchmark output. |

## Built with

Python 3.12 · FastAPI · Uvicorn · PostgreSQL · psycopg2 · vanilla JavaScript · Leaflet

No machine-learning frameworks: the Bayesian forecaster is implemented from first principles in the standard library, so the whole system runs natively on s390x with no build step and no containers.

## Limitations

The data is synthetic. The simulated baseline waste rate is higher than the published national figure, so the results above are quoted as relative improvements rather than absolute rates. Authentication and per-user audit are not implemented and would be the first production requirements.
