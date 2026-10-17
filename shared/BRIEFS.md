# Team Briefs: Platelet Exchange

Everyone reads `CONTRACT.md` first. Each brief says what you own, what you consume, what you deliver, and how you know you're done.

**AI users:** start your agent session by giving it `AGENTS.md`, `CONTRACT.md`, and your own section below. In Claude Code these load automatically from the repo; still paste your section as your first message.

---

## Neil: Lead, API, database, mainframe

**Goal:** Own the backbone everyone plugs into, and prove the Z story with numbers.

**You own:** `api/`, `db/`, `bench/`, deployment on the Z instance, merging pull requests, `CONTRACT.md`.

**You consume:** `engine/` functions, `shared/*.json`, `results/comparison.json`.

**Milestones**
- **+30m:** Commit the team files to the repo, run the kickoff, and send Person 6 `INSTANCE_SETUP.md`. Answer their questions while they set up.
- **+1h:** API stub returning the contract's example JSON for every endpoint. Generate `web/mock/*.json` from the same examples and commit them for Person 4.
- **+4h:** Postgres schema and seed script, real `/stock`, `/hospitals`, `/feed/events`, `/reservations`; FastAPI also serves `web/` at `/`. Fill in Part 8 of `INSTANCE_SETUP.md` with the exact deploy commands so Person 6 can run them, then get the sim live mode posting into the instance. Walking skeleton done.
- **+10h:** `/recommendations` and `/emergency` calling the real engine; `/metrics` and `/events` working.
- **+16h:** `bench/reserveRace.py` (1,000 concurrent reservations on one unit, exactly one 201) and `bench/latency.py` (throughput, p50/p99), with results in `results/benchmark.json`. Optionally run the same race against a naive version without the conditional update to show it double-books.

**Done when:** Everything in contract section 12 runs on the Z instance from a clean start with one command or a short README.

**Instance environment:** Ubuntu 24.04 (to be confirmed by Person 6), s390x, Python 3.12, git 2.43, no Docker. Postgres runs locally; the connection string is in `~/plateletExchange.env` on the instance as `DATABASE_URL`, never in the repo.

---

## Person 2 (AI): Data generator and simulator

**Goal:** Produce the evidence: a fair, reproducible comparison of no sharing vs. the exchange.

**You own:** `sim/`, `results/comparison.json`.

**You consume:** `shared/assumptions.json`, `shared/hospitals.json`, and `engine.forecastDemand` and `engine.recommendTransfers` (stubs from +1h).

**Milestones**
- **+1h:** `python -m sim.run` writes a correctly shaped but fake `comparison.json`.
- **+4h:** `generateScenario` produces deliveries and demand from the assumptions (weekday/weekend pattern, blood group mix, random shelf life left on arrival). `sim.live` streams events to the API.
- **+10h:** `runSimulation` correct for both policies (FIFO issuing within each hospital, expiry, unmet demand counted as a shortage, transfers taking travel time). The `noSharing` waste rate lands near `baselineWasteRate`; if not, work with Person 5 on calibration.
- **+16h:** Run 10 or more seeds, report mean and spread, plus two stress scenarios (a demand surge at one hospital, a supply dip).

**Tests:** Same seed gives an identical result. No unit is transfused after expiry. Units delivered = transfused + wasted + still in stock at the end.

**Done when:** `comparison.json` is final and Person 5 has sanity-checked it.

---

## Person 3 (AI): Forecasting and optimization engine

**Goal:** The brains: decide which units should move where, and rank emergency sources.

**You own:** `engine/`. Pure functions only (contract section 6), with no database, HTTP, or file access.

**You consume:** inputs passed in as arguments (shapes in contract section 5).

**Milestones**
- **+1h:** Stubs committed with the exact signatures, importable by `sim/` and `api/`.
- **+4h:** Forecaster v1 (day-of-week average per hospital and group). Emergency ranking v1 (compatible, not the requesting hospital, sorted by penalty, travel time, then hours to expiry).
- **+10h:** `recommendTransfers` v1. For each hospital, compare stock expiring before forecast use against other hospitals' forecast shortfall, then solve as a min-cost flow (networkx is pure Python, which is safe on s390x) or a well-documented greedy heuristic. Respect `maxTransferMinutes`, `minHoursLeftToTransfer`, and compatibility penalties.
- **+16h:** Tune with Person 2's simulator. Produce a short explanation of the method for the pitch (Person 6).

**Tests:** Never recommends the same unit twice, an expired unit, or an incompatible move. Small hand-made fixtures with obvious answers (one hospital overstocked, one short) produce the obvious transfer.

**Done when:** The `exchange` policy beats `noSharing` on waste without increasing shortages, across seeds.

---

## Person 4 (AI): Dashboard

**Goal:** The thing judges actually look at. It must be clear in 10 seconds.

**You own:** `web/` (plain HTML/CSS/JS, no build step; Leaflet from a CDN works for the map).

**You consume:** the HTTP API only (contract section 8). Until it's live, use `web/mock/*.json` behind a `useMock` flag.

**Milestones**
- **+1h:** Page loads mock hospitals and stock.
- **+4h:** Map of hospitals with stock colored by days to expiry (red under 1 day, amber 1–2, green 3+), a click-through hospital panel, and a live events feed polling every 5 seconds. Switched to the real API on Z.
- **+10h:** Recommendations panel with "Reserve" and "Complete" buttons (handle 409 gracefully), an emergency request form showing ranked sources, and a metrics bar.
- **+16h:** Comparison view from `/simulation/results` (waste and shortages, noSharing vs exchange, with daily charts) and a benchmark panel from `results/benchmark.json`.

**Done when:** Person 6 can run the whole demo script without touching anything except the dashboard.

---

## Person 5 (no AI): Domain, data, and validation

**Goal:** Make the numbers defensible. Judges will ask "is this realistic?" and you're the answer.

**You own:** `shared/*.json` (the values, not the shapes), `docs/assumptions.md`, `docs/validation.md`.

**Milestones**
- **+1h:** Check that the placeholder `shared/` files are committed. Ask Neil to commit them if you're not using git.
- **+4h:** `hospitals.json`: about 10 real Greater Manchester hospitals with coordinates and size category, noting which have haematology or cancer units (heavy platelet users). `travelTimes.json`: driving times between each pair (Google Maps is fine; record the time of day used).
- **+8h:** `compatibility.json`: platelet ABO/RhD compatibility with preference penalties, from UK transfusion guidelines. `assumptions.json`: demand per hospital size, blood group mix, shelf life left on arrival, the national waste rate. Every value gets a source line in `docs/assumptions.md`.
- **+12h to +16h:** Review Person 2's results. Are waste rates, shortages, and transfer counts plausible? Write `docs/validation.md` with what you checked and any limitations.
- **Throughout:** Gather 3–5 real-world facts and examples for the pitch (national waste figures, BloodMove in Australia, the Ontario program, the Atlanta two-hospital study).

**Done when:** Every number in the pitch traces to a source or a clearly stated assumption.

**Hand-off format:** Edit the JSON files directly, keeping the exact shapes in the contract. If editing JSON is awkward, use a spreadsheet with the same columns and Neil or Person 2 will convert it.

---

## Person 6 (no AI): Instance setup, then pitch, demo, and quality assurance

**Goal:** First, get the IBM Z instance ready and keep it running. Then win the room by turning the build into a story judges remember.

**You own:** the instance (following `INSTANCE_SETUP.md`), `docs/pitch/` (slides, script), the demo script, rehearsals, the backup recording.

**Milestones**
- **+1h:** Work through `INSTANCE_SETUP.md` Parts 0–7 and post the report in the group chat. Send the database password to Neil privately.
- **+1h30:** Get the judging criteria and submission requirements from the organizers. Share them with the team and check them against the contract's definition of done.
- **From +4h:** Whenever Neil says there's a new version, run the deploy routine in `INSTANCE_SETUP.md` Part 8.
- **+4h:** Slide outline: the problem (platelets last 5 days, waste and shortages coexist), why now (hospitals track units internally but nothing sees across them), the solution, live demo, results, why IBM Z, limitations, next steps.
- **+10h:** Draft demo script built around one story: a unit about to expire at a small hospital, a busy hospital about to run short, the exchange spotting it, reserve, complete. Then an emergency request.
- **+16h:** Test the dashboard as a user. File clear bug reports to Person 4 (what you clicked, what you expected, what happened).
- **+20h onward:** Final slides with real numbers from Persons 2 and 5 and Neil's benchmark. Run two full timed rehearsals. Record a backup video of the demo working.

**Done when:** Anyone on the team could deliver the pitch from your script, and the backup video exists.
